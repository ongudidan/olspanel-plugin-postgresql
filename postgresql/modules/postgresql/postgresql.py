import subprocess
import re
import json
from django.conf import settings
import os
import base64
import random
import string


def pg_size_to_bytes(size_str):
    """Convert PostgreSQL pg_size_pretty output to bytes."""
    size_str = size_str.strip().upper()
    if size_str.endswith("KB"):
        return float(size_str[:-2]) * 1024
    elif size_str.endswith("MB"):
        return float(size_str[:-2]) * 1024**2
    elif size_str.endswith("GB"):
        return float(size_str[:-2]) * 1024**3
    elif size_str.endswith("TB"):
        return float(size_str[:-2]) * 1024**4
    elif size_str.endswith("BYTES"):
        return float(size_str[:-5])
    else:
        try:
            return float(size_str)
        except ValueError:
            return 0.0


def bytes_to_pretty(num_bytes):
    """Convert bytes to human-readable format."""
    for unit in ["bytes", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.2f} PB"


def postgresql_filter(prefix):
    admin_user = "postgres"
    admin_pass = get_phpmypostgresql_password("admin")
    host = "localhost"
    port = "5432"

    if not all([prefix, admin_user, admin_pass]):
        return {"error": "Missing required parameters."}

    try:
        query = """
        SELECT datname, pg_catalog.pg_get_userbyid(datdba) AS owner,
               pg_size_pretty(pg_database_size(datname)) AS size
        FROM pg_database
        WHERE datistemplate = false;
        """
        cmd = [
            "psql",
            f"postgresql://{admin_user}:{admin_pass}@{host}:{port}/postgres",
            "-t", "-A", "-F", "|", "-c", query
        ]
        psql_output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        return {"error": f"PostgreSQL connection failed: {e}"}

    filtered_dbs = []
    total_size_bytes = 0.0

    for line in psql_output.strip().splitlines():
        # Each line looks like: mydb|postgres|8 MB
        parts = line.split("|")
        if len(parts) == 3:
            db_name, owner, db_size = parts
            if db_name.startswith(prefix):
                filtered_dbs.append({
                    "db_name": db_name,
                    "owner": owner,
                    "size_display": db_size
                })
                total_size_bytes += pg_size_to_bytes(db_size)

    return {
        "prefix": prefix,
        "matched": len(filtered_dbs),
        "total_size": bytes_to_pretty(total_size_bytes),
        "databases": filtered_dbs
    }


def postgresql_total_info():
    admin_user = "postgres"
    admin_pass = get_phpmypostgresql_password("admin")
    host = "localhost"
    port = "5432"

    try:
        query = """
        SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
        FROM pg_database
        WHERE datistemplate = false AND datname <> 'postgres';
        """
        cmd = [
            "psql",
            f"postgresql://{admin_user}:{admin_pass}@{host}:{port}/postgres",
            "-t", "-A", "-F", "|", "-c", query
        ]
        psql_output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        return {"error": f"PostgreSQL connection failed: {e}"}

    db_count = 0
    total_size_bytes = 0.0

    for line in psql_output.strip().splitlines():
        # Example line: mydb|8 MB
        parts = line.split("|")
        if len(parts) == 2:
            db_name, db_size = parts
            db_count += 1
            total_size_bytes += pg_size_to_bytes(db_size)

    return {
        "total_databases": db_count,
        "total_size": bytes_to_pretty(total_size_bytes)
    }



def get_users_for_pdatabase(db_name):
    admin_user = "postgres"
    admin_pass = get_phpmypostgresql_password("admin")

    # SQL query to get database owner and grantees
    query = f"""
        SELECT
            d.datname AS db_name,
            r.rolname AS owner,
            ARRAY(
                SELECT grantee
                FROM information_schema.role_table_grants
                WHERE table_catalog = d.datname
            ) AS grantees
        FROM pg_database d
        JOIN pg_roles r ON d.datdba = r.oid
        WHERE d.datname = '{db_name}';
    """

    cmd = [
        "psql",
        "-U", admin_user,
        "-d", "postgres",
        "-t", "-A",
        "-c", query
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            env={"PGPASSWORD": admin_pass}
        )
        output = result.stdout.strip()

        if not output:
            return {
                "status": "error",
                "database": db_name,
                "owner": None,
                "users": [],
                "message": "No data found"
            }

        # Example output:  mydb|myuser|{user1,user2}
        parts = output.split("|")
        owner = parts[1] if len(parts) > 1 else "Unknown"
        raw_users = parts[2] if len(parts) > 2 else "{}"
        users = re.findall(r'\w+', raw_users)

        return {
            "status": "success",
            "database": db_name,
            "owner": owner,
            "users": users if users else []
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "database": db_name,
            "owner": None,
            "users": [],
            "message": f"Failed to fetch users: {e.stderr.strip() or str(e)}"
        }



def delete_pdatabase(db_name, username=None):
    
    admin_pass = get_phpmypostgresql_password("admin")

    try:
        # --- Step 1: Check if the database exists ---
        check_cmd = [
            "psql",
            "-U", "postgres",
            "-d", "postgres",
            "-t", "-A",
            "-c", f"SELECT 1 FROM pg_database WHERE datname='{db_name}';"
        ]
        check_result = subprocess.run(
            check_cmd, capture_output=True, text=True, env={"PGPASSWORD": admin_pass}
        )

        if check_result.stdout.strip() != "1":
            return {"status": "skip", "message": f"Database '{db_name}' does not exist."}

        # --- Step 2: Drop database ---
        drop_db_cmd = [
            "psql",
            "-U", "postgres",
            "-d", "postgres",
            "-c", f"DROP DATABASE IF EXISTS \"{db_name}\";"
        ]
        db_result = subprocess.run(
            drop_db_cmd, capture_output=True, text=True, env={"PGPASSWORD": admin_pass}
        )

        if db_result.returncode != 0:
            return {
                "status": "error",
                "message": db_result.stderr.strip() or "Failed to delete database."
            }

        # --- Step 3: Drop user if provided ---
        if username:
            drop_user_cmd = [
                "psql",
                "-U", "postgres",
                "-d", "postgres",
                "-c", f"DROP ROLE IF EXISTS \"{username}\";"
            ]
            user_result = subprocess.run(
                drop_user_cmd, capture_output=True, text=True, env={"PGPASSWORD": admin_pass}
            )

            if user_result.returncode != 0:
                return {
                    "status": "partial",
                    "message": f"Database '{db_name}' deleted, but failed to remove user '{username}'.",
                    "output": user_result.stderr.strip()
                }

        return {
            "status": "success",
            "message": f"Database '{db_name}' and user '{username or '(none)'}' deleted successfully."
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


def repair_mongo_database(db_name):
    admin_pass = get_phpmypostgresql_password("admin")
    admin_user = "admin"        
    auth_db = "admin"
    cmd = [
        "mongosh", "--quiet",
        "--username", admin_user,
        "--password", admin_pass,
        "--authenticationDatabase", auth_db,
        "--eval", f'db.getSiblingDB("{db_name}").repairDatabase();'
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        output = result.stdout.strip()

        # Detect success based on typical response pattern
        if '"ok"' in output or "ok:" in output or "1" in output:
            status = "success"
            message = f"Database '{db_name}' repaired successfully."
        else:
            status = "warning"
            message = f"Database '{db_name}' repair completed with unusual output."

        return {
            "status": status,
            "database": db_name,
            "output": output,
            "message": message
        }

    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "database": db_name,
            "message": f"Repair failed for database '{db_name}': {e.stderr.strip() or e.stdout.strip()}",
        }
        
        
        

   
        
        
def create_postgresql_account(db_name, second_user, second_pass,main_user):
    store_user_password(main_user)
    admin_pass = get_phpmypostgresql_password("admin")       
    main_user_pass = get_phpmypostgresql_password(main_user)
    try:
        db_exists = check_postgresql_exists(admin_pass, db_name, "database")
        user_exists = check_postgresql_exists(admin_pass, second_user, "user")
        if db_exists:
            return {
                "status": "skip",
                "message": f"Database '{db_name}' already exist.",
            }
            
        if user_exists:
            return {
                "status": "skip",
                "message": f"User '{second_user}' already exist.",
            }
            
        script_path = os.path.join(settings.BASE_DIR, 'modules', 'postgresql', 'psql.sh')
        print("Step 2: Removing Windows-style line endings from upgrade.sh...")
        subprocess.run(f"sed -i 's/\\r$//' {script_path}", shell=True, check=True)

        print("Step 3: Running upgrade.sh...")
        subprocess.run(f"chmod +x {script_path}", shell=True)


        cmd = [
            "bash", script_path,
            db_name, second_user, main_user, second_pass, main_user_pass, admin_pass
           
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            
            
            return {
                "status": "success",
                "message": f"Database '{db_name}' and user '{second_user}' created successfully.",
                "output": result.stdout.strip()
            }
        else:
            error_message = result.stderr.strip() or result.stdout.strip() or "Unknown error during account creation."

            return {
                "status": "error",
                "message": error_message,
                "output": result.stdout.strip()
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}

def check_postgresql_exists(admin_pass, name, type_="database"):
    """Check if a PostgreSQL database or role exists."""
    try:
        # Build SQL query based on type
        if type_ == "database":
            sql = f"SELECT 1 FROM pg_database WHERE datname='{name}';"
        elif type_ == "user":
            sql = f"SELECT 1 FROM pg_roles WHERE rolname='{name}';"
        else:
            return False

        cmd = [
            "psql",
            "-U", "postgres",
            "-d", "postgres",
            "-t", "-A", "-c", sql
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, env={"PGPASSWORD": admin_pass}
        )

        return result.stdout.strip() == "1"

    except Exception as e:
        print(f"Check failed: {e}")
        return False

def store_user_password(username):
    try:
        
        django_root = settings.BASE_DIR
        etc_dir = os.path.join(django_root, 'etc')
        os.makedirs(etc_dir, exist_ok=True)

        password_file = os.path.join(etc_dir, f"phpmypostgresql_{username}")

        # Only create the file if it doesn't exist
        if not os.path.exists(password_file):
            password = generate_strong_random_ppassword()
            new_data = encodepass(password)
            with open(password_file, 'w') as f:
                f.write(new_data)
            return password_file
        else:
            # Skip creation if already exists
            return password_file  # Or return a message like "Already exists"

    except Exception as e:
        raise Exception(f"Error saving password: {str(e)}")
       
        
        
        
def get_phpmypostgresql_password(username):
    # Get the path of the project directory
    django_root = settings.BASE_DIR
    if username == 'admin':
        source_file = os.path.join(django_root, 'etc', "postgresqlPassword")
    else:
        source_file = os.path.join(django_root, 'etc', f"phpmypostgresql_{username}")
    
    # Check if the file exists
    if not os.path.exists(source_file):
        return f"Password file for user {username} not found."

    try:
        # Read the content of the file
        with open(source_file, 'r') as file:
            file_content = file.read().strip()
        
        if username == 'admin':
            return file_content
        else:
            return decodepass(file_content)
            
        
    
    except Exception as e:
        # Handle unexpected errors and return the error message
        return f"An error occurred: {str(e)}"        
        
        
def encodepass(data: str) -> str:
    
    # Convert the string to bytes
    data_bytes = data.encode('utf-8')
    # Encode the bytes to Base64
    base64_bytes = base64.b64encode(data_bytes)
    # Convert Base64 bytes back to string
    base64_str = base64_bytes.decode('utf-8')
    # Generate a random 5-character string of lowercase letters
    random_string = ''.join(random.choices(string.ascii_lowercase, k=5))
    # Prepend the random string to the Base64 string
    return random_string + base64_str

def decodepass(base64_data: str) -> str:
    
    # Remove the first 5 characters (random string) from the string
    base64_str = base64_data[5:]
    # Convert Base64 string to bytes
    base64_bytes = base64_str.encode('utf-8')
    # Decode the Base64 bytes back to original bytes
    decoded_bytes = base64.b64decode(base64_bytes)
    # Convert bytes back to string
    return decoded_bytes.decode('utf-8')   


def change_postgresql_password(second_user, second_pass):
    admin_user = "postgres"
    admin_pass = get_phpmypostgresql_password("admin")

    try:
        # SQL command to change the user's password
        query = f"ALTER USER {second_user} WITH PASSWORD '{second_pass}';"

        # Connect to the global postgres database (not specific one)
        cmd = [
            "psql",
            "-U", admin_user,
            "-d", "postgres",
            "-t", "-A",
            "-c", query
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={"PGPASSWORD": admin_pass}
        )

        if result.returncode == 0:
            
            return {
                "status": "success",
                "message": f"Password changed successfully for user '{second_user}'.",
                "output": result.stdout.strip()
            }
        else:
            return {
                "status": "error",
                "message": result.stderr.strip() or "Failed to change password.",
                "output": result.stdout.strip()
            }

    except Exception as e:
        return {"status": "error", "message": str(e)}

        
        
        
def generate_strong_random_ppassword(length=16):
    """Generate a strong random password using only A-Z and a-z characters."""
    if length < 12:  # Enforce a minimum length for security
        length = 12

    # Create a pool of characters (A-Z and a-z)
    all_characters = string.ascii_letters  # This includes both uppercase and lowercase letters

    # Generate a random password by selecting random characters from the pool
    password = random.choices(all_characters, k=length)

    return ''.join(password)            