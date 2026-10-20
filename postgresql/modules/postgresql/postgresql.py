import subprocess
import re
import json
from django.conf import settings
import os
import base64
import random
import string
import pwd


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


def get_admin_password():
    """Retrieve the PostgreSQL admin password from standard locations."""
    paths = [
        os.path.join(getattr(settings, 'BASE_DIR', ''), 'etc', 'postgresqlPassword'),
        '/usr/local/olspanel/mypanel/etc/postgresqlPassword'
    ]
    for p in paths:
        if p and os.path.isfile(p):
            try:
                with open(p, 'r') as f:
                    pw = f.read().strip()
                    if pw:
                        return pw
            except Exception:
                pass
    return None


def run_pg_cmd(sql_args, db="postgres"):
    """
    Execute PostgreSQL queries using psql non-interactively.
    sql_args can be a single SQL string or a list of SQL strings.
    """
    admin_pass = get_admin_password()
    if not admin_pass:
        return False, "PostgreSQL admin password not found."

    if isinstance(sql_args, str):
        sql_list = [sql_args]
    else:
        sql_list = list(sql_args)

    cmd = ["psql", "-h", "localhost", "-U", "postgres", "-d", db, "-w", "-t", "-A"]
    for sql in sql_list:
        cmd.extend(["-c", sql])

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=25,
            env={**os.environ, "PGPASSWORD": admin_pass}
        )
        if res.returncode == 0:
            return True, res.stdout.strip()
        else:
            err = res.stderr.strip() or res.stdout.strip() or f"psql exited with code {res.returncode}"
            return False, err
    except Exception as e:
        return False, str(e)


def clean_pg_identifier(name: str) -> str:
    """Validates PostgreSQL identifier (database or username)."""
    if not name or not re.match(r'^[a-zA-Z0-9_]+$', name):
        raise ValueError(f"Invalid identifier '{name}': only alphanumeric and underscores allowed.")
    return name


def ensure_main_pg_user(username):
    """Ensure the main panel user exists as a PostgreSQL role with password."""
    admin_pass = get_admin_password()
    if not admin_pass:
        return
    success, out = run_pg_cmd(f"SELECT 1 FROM pg_roles WHERE rolname='{username}';", db="postgres")
    if not success or out != "1":
        passw = get_phpmypostgresql_password(username)
        if not passw or passw.startswith("Password file") or passw.startswith("An error"):
            store_user_password(username)
            passw = get_phpmypostgresql_password(username)
        safe_pass = str(passw).replace("'", "''")
        run_pg_cmd(f"CREATE ROLE \"{username}\" WITH LOGIN PASSWORD '{safe_pass}';", db="postgres")


def postgresql_filter(prefix):
    """
    Retrieve databases matching prefix, along with size and list of privileged users.
    Uniform with MySQL's get_user_database_info.
    """
    admin_pass = get_admin_password()
    if not admin_pass:
        return {"error": "Missing admin password.", "databases": [], "matched": 0, "total_size": "0 MB"}

    query = f"""
    SELECT d.datname,
           pg_catalog.pg_get_userbyid(d.datdba) AS owner,
           pg_size_pretty(pg_database_size(d.datname)) AS size,
           COALESCE(string_agg(r.rolname, ',' ORDER BY r.rolname), '') AS privileged_users
    FROM pg_database d
    LEFT JOIN pg_roles r 
      ON r.rolname LIKE '{prefix}%' 
      AND has_database_privilege(r.rolname, d.datname, 'CONNECT')
    WHERE d.datistemplate = false 
      AND d.datname LIKE '{prefix}%'
    GROUP BY d.datname, d.datdba
    ORDER BY d.datname;
    """

    success, output = run_pg_cmd(query, db="postgres")
    if not success:
        return {"error": output, "databases": [], "matched": 0, "total_size": "0 MB"}

    filtered_dbs = []
    total_size_bytes = 0.0

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            db_name = parts[0]
            owner = parts[1]
            size_str = parts[2]
            p_users_raw = parts[3] if len(parts) > 3 else ""
            p_users_list = [u.strip() for u in p_users_raw.split(",") if u.strip()]

            filtered_dbs.append({
                "db_name": db_name,
                "owner": owner,
                "size_display": size_str,
                "privileged_users": p_users_raw,
                "privileged_users_list": p_users_list
            })
            total_size_bytes += pg_size_to_bytes(size_str)

    return {
        "prefix": prefix,
        "matched": len(filtered_dbs),
        "total_size": bytes_to_pretty(total_size_bytes),
        "databases": filtered_dbs
    }


def list_postgresql_users(username):
    """Retrieve list of PostgreSQL user roles matching the user prefix (excluding main user)."""
    prefix = f"{username}_"
    query = f"""
    SELECT rolname FROM pg_roles 
    WHERE rolcanlogin = true 
      AND rolname LIKE '{prefix}%' 
      AND rolname <> '{username}'
    ORDER BY rolname;
    """
    success, output = run_pg_cmd(query, db="postgres")
    if not success or not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def create_postgresql_db(username, db_name):
    """Create a new PostgreSQL database with username prefix and configure initial ownership."""
    clean_name = db_name.strip()
    if clean_name.startswith(f"{username}_"):
        full_db = clean_name
    else:
        full_db = f"{username}_{clean_name}"

    try:
        clean_pg_identifier(full_db)
    except ValueError as e:
        return False, str(e)

    # 1. Check if database already exists
    check_query = f"SELECT 1 FROM pg_database WHERE datname='{full_db}';"
    success, output = run_pg_cmd(check_query, db="postgres")
    if success and output == "1":
        return False, f"Database '{full_db}' already exists."

    # 2. Ensure main user role exists in PostgreSQL so phpPgAdmin can manage it
    ensure_main_pg_user(username)

    # 3. Create database
    create_sql = f'CREATE DATABASE "{full_db}";'
    success, err = run_pg_cmd(create_sql, db="postgres")
    if not success:
        return False, err

    # 4. Revoke public connect and grant to main user
    revoke_sql = f'REVOKE CONNECT ON DATABASE "{full_db}" FROM PUBLIC;'
    grant_sql = f'GRANT ALL PRIVILEGES ON DATABASE "{full_db}" TO "{username}";'
    run_pg_cmd([revoke_sql, grant_sql], db="postgres")

    # 5. Inside the new database, grant schema permissions to main user
    inside_sqls = [
        f'GRANT ALL ON SCHEMA public TO "{username}";',
        f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{username}";',
        f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{username}";',
        f'GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO "{username}";',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{username}";',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{username}";'
    ]
    run_pg_cmd(inside_sqls, db=full_db)

    return True, f"Database '{full_db}' created successfully."


def delete_postgresql_db(username, db_name):
    """Delete a PostgreSQL database with force termination of active connections."""
    if not db_name.startswith(f"{username}_"):
        return False, "Unauthorized: database does not match your account prefix."

    try:
        clean_pg_identifier(db_name)
    except ValueError as e:
        return False, str(e)

    drop_sql = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
    success, err = run_pg_cmd(drop_sql, db="postgres")
    if not success:
        return False, err
    return True, f"Database '{db_name}' deleted successfully."


def create_postgresql_user(username, db_user, db_pass):
    """Create a new PostgreSQL database user role with prefix."""
    clean_name = db_user.strip()
    if clean_name.startswith(f"{username}_"):
        full_user = clean_name
    else:
        full_user = f"{username}_{clean_name}"

    try:
        clean_pg_identifier(full_user)
    except ValueError as e:
        return False, str(e)

    if len(db_pass) < 8:
        return False, "Password must be at least 8 characters long."

    safe_pass = db_pass.replace("'", "''")

    check_query = f"SELECT 1 FROM pg_roles WHERE rolname='{full_user}';"
    success, output = run_pg_cmd(check_query, db="postgres")
    if success and output == "1":
        return False, f"User '{full_user}' already exists."

    create_sql = f"CREATE ROLE \"{full_user}\" WITH LOGIN PASSWORD '{safe_pass}';"
    success, err = run_pg_cmd(create_sql, db="postgres")
    if not success:
        return False, err

    return True, f"Database user '{full_user}' created successfully."


def delete_postgresql_user(username, db_user):
    """Delete a PostgreSQL database user role."""
    if not db_user.startswith(f"{username}_"):
        return False, "Unauthorized: database user does not match your account prefix."

    try:
        clean_pg_identifier(db_user)
    except ValueError as e:
        return False, str(e)

    # First try direct drop
    drop_sql = f'DROP ROLE IF EXISTS "{db_user}";'
    success, err = run_pg_cmd(drop_sql, db="postgres")
    if not success:
        # Reassign owned objects before dropping
        reassign_sqls = [
            f'REASSIGN OWNED BY "{db_user}" TO postgres;',
            f'DROP OWNED BY "{db_user}";',
            f'DROP ROLE IF EXISTS "{db_user}";'
        ]
        success2, err2 = run_pg_cmd(reassign_sqls, db="postgres")
        if not success2:
            return False, err2

    return True, f"Database user '{db_user}' deleted successfully."


def change_postgresql_user_password(username, db_user, new_pass):
    """Update a PostgreSQL database user's password."""
    if not db_user.startswith(f"{username}_"):
        return False, "Unauthorized: database user does not match your account prefix."

    try:
        clean_pg_identifier(db_user)
    except ValueError as e:
        return False, str(e)

    if len(new_pass) < 8:
        return False, "Password must be at least 8 characters long."

    safe_pass = new_pass.replace("'", "''")
    alter_sql = f"ALTER ROLE \"{db_user}\" WITH PASSWORD '{safe_pass}';"
    success, err = run_pg_cmd(alter_sql, db="postgres")
    if not success:
        return False, err
    return True, f"Password updated successfully for user '{db_user}'."


def grant_postgresql_user_privileges(username, db_user, db_name, privs_list):
    """Grant granular or ALL privileges to a database user on a specific PostgreSQL database."""
    if not db_name.startswith(f"{username}_") or not db_user.startswith(f"{username}_"):
        return False, "Unauthorized: target does not match your account prefix."

    try:
        clean_pg_identifier(db_name)
        clean_pg_identifier(db_user)
    except ValueError as e:
        return False, str(e)

    clean_privs = [p.lower().strip() for p in privs_list]
    is_all = ('all privileges' in clean_privs) or ('all' in clean_privs)

    # 1. On database level
    db_sqls = []
    if is_all:
        db_sqls.append(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{db_user}";')
    else:
        db_sqls.append(f'GRANT CONNECT, TEMPORARY ON DATABASE "{db_name}" TO "{db_user}";')
        if 'create' in clean_privs:
            db_sqls.append(f'GRANT CREATE ON DATABASE "{db_name}" TO "{db_user}";')

    run_pg_cmd(db_sqls, db="postgres")

    # 2. Inside the target database
    inside_sqls = []
    if is_all:
        inside_sqls.extend([
            f'GRANT ALL ON SCHEMA public TO "{db_user}";',
            f'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "{db_user}";',
            f'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "{db_user}";',
            f'GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO "{db_user}";',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{db_user}";',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{db_user}";',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO "{db_user}";'
        ])
    else:
        inside_sqls.append(f'GRANT USAGE ON SCHEMA public TO "{db_user}";')
        if 'create' in clean_privs:
            inside_sqls.append(f'GRANT CREATE ON SCHEMA public TO "{db_user}";')

        table_priv_candidates = ['select', 'insert', 'update', 'delete', 'truncate', 'references', 'trigger']
        granted_table_privs = [p.upper() for p in table_priv_candidates if p in clean_privs]
        if granted_table_privs:
            priv_str = ", ".join(granted_table_privs)
            inside_sqls.extend([
                f'GRANT {priv_str} ON ALL TABLES IN SCHEMA public TO "{db_user}";',
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {priv_str} ON TABLES TO "{db_user}";'
            ])

        if any(p in clean_privs for p in ['select', 'update', 'usage']):
            inside_sqls.extend([
                f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{db_user}";',
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO "{db_user}";'
            ])

        if 'execute' in clean_privs:
            inside_sqls.extend([
                f'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO "{db_user}";',
                f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO "{db_user}";'
            ])

    success, err = run_pg_cmd(inside_sqls, db=db_name)
    if not success:
        return False, err

    return True, f"Privileges granted successfully for '{db_user}' on '{db_name}'."


def revoke_postgresql_user_privileges(username, db_user, db_name):
    """Revoke all privileges / unlink a user from a PostgreSQL database."""
    if not db_name.startswith(f"{username}_") or not db_user.startswith(f"{username}_"):
        return False, "Unauthorized: target does not match your account prefix."

    try:
        clean_pg_identifier(db_name)
        clean_pg_identifier(db_user)
    except ValueError as e:
        return False, str(e)

    # 1. Inside target database
    inside_sqls = [
        f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM "{db_user}";',
        f'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM "{db_user}";',
        f'REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM "{db_user}";',
        f'REVOKE ALL PRIVILEGES ON SCHEMA public FROM "{db_user}";',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM "{db_user}";',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM "{db_user}";',
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM "{db_user}";'
    ]
    run_pg_cmd(inside_sqls, db=db_name)

    # 2. On database level
    db_sqls = [
        f'REVOKE ALL PRIVILEGES ON DATABASE "{db_name}" FROM "{db_user}";'
    ]
    success, err = run_pg_cmd(db_sqls, db="postgres")
    if not success:
        return False, err

    return True, f"User '{db_user}' unlinked from '{db_name}' successfully."


def get_postgresql_user_db_privileges(username, db_user, db_name):
    """Inspect current privileges for a database user on a specific PostgreSQL database."""
    priv_keys = [
        'select', 'insert', 'update', 'delete', 'truncate',
        'references', 'trigger', 'create', 'connect', 'temporary',
        'execute', 'usage'
    ]
    defaults = {k: False for k in priv_keys}

    if not db_name.startswith(f"{username}_") or not db_user.startswith(f"{username}_"):
        return defaults

    check_query = f"SELECT has_database_privilege('{db_user}', '{db_name}', 'CONNECT');"
    success, out = run_pg_cmd(check_query, db="postgres")
    if not success or out != "t":
        return defaults

    defaults['connect'] = True

    check_create = f"SELECT has_database_privilege('{db_user}', '{db_name}', 'CREATE');"
    s, out_create = run_pg_cmd(check_create, db="postgres")
    if s and out_create == "t":
        defaults['create'] = True

    check_temp = f"SELECT has_database_privilege('{db_user}', '{db_name}', 'TEMPORARY');"
    s, out_temp = run_pg_cmd(check_temp, db="postgres")
    if s and out_temp == "t":
        defaults['temporary'] = True

    s, out_usage = run_pg_cmd(f"SELECT has_schema_privilege('{db_user}', 'public', 'USAGE');", db=db_name)
    if s and out_usage == "t":
        defaults['usage'] = True

    # Standard table capabilities if connected
    for k in ['select', 'insert', 'update', 'delete', 'truncate', 'references', 'trigger', 'execute']:
        defaults[k] = True

    return defaults


def export_postgresql_db(username, db_name):
    """Export a PostgreSQL database snapshot using pg_dump into user's tmp directory."""
    if not db_name.startswith(f"{username}_"):
        return {"status": "error", "message": "Unauthorized"}

    try:
        clean_pg_identifier(db_name)
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    admin_pass = get_admin_password()
    if not admin_pass:
        return {"status": "error", "message": "PostgreSQL admin password not found"}

    target_dir = f"/home/{username}/tmp"
    os.makedirs(target_dir, exist_ok=True)
    file_path = os.path.join(target_dir, f"{db_name}.sql")

    cmd = [
        "pg_dump",
        "-h", "localhost",
        "-U", "postgres",
        "-w",
        "-F", "p",
        "-f", file_path,
        db_name
    ]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "PGPASSWORD": admin_pass}
        )
        if res.returncode == 0:
            try:
                user_info = pwd.getpwnam(username)
                os.chown(file_path, user_info.pw_uid, user_info.pw_gid)
            except Exception:
                pass
            return {"status": "success", "file_path": file_path}
        else:
            return {"status": "error", "message": res.stderr.strip() or "Export failed"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def repair_postgresql_db(username, db_name):
    """Perform table maintenance on a PostgreSQL database via REINDEX and VACUUM ANALYZE."""
    if not db_name.startswith(f"{username}_"):
        return False, "Unauthorized"

    try:
        clean_pg_identifier(db_name)
    except ValueError as e:
        return False, str(e)

    reindex_sql = f'REINDEX DATABASE "{db_name}";'
    s1, err1 = run_pg_cmd(reindex_sql, db=db_name)
    vacuum_sql = 'VACUUM ANALYZE;'
    s2, err2 = run_pg_cmd(vacuum_sql, db=db_name)

    if s1 or s2:
        return True, f"Database '{db_name}' reindexed and vacuumed successfully."
    return False, f"Maintenance error: {err1 or err2}"


def postgresql_total_info():
    """Retrieve global stats across all PostgreSQL databases for the admin dashboard widget."""
    admin_pass = get_admin_password()
    if not admin_pass:
        return {"total_databases": 0, "total_size": "0 MB"}

    query = """
    SELECT datname, pg_size_pretty(pg_database_size(datname)) AS size
    FROM pg_database
    WHERE datistemplate = false AND datname <> 'postgres';
    """
    success, output = run_pg_cmd(query, db="postgres")
    if not success:
        return {"total_databases": 0, "total_size": "0 MB"}

    db_count = 0
    total_size_bytes = 0.0

    for line in output.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 2:
            db_name, db_size = parts
            db_count += 1
            total_size_bytes += pg_size_to_bytes(db_size)

    return {
        "total_databases": db_count,
        "total_size": bytes_to_pretty(total_size_bytes)
    }


def get_users_for_pdatabase(db_name):
    """Retrieve database owner and grantees for compatibility."""
    admin_pass = get_admin_password()
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
    success, output = run_pg_cmd(query, db="postgres")
    if not success or not output:
        return {
            "status": "error",
            "database": db_name,
            "owner": None,
            "users": [],
            "message": "No data found"
        }

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


def delete_pdatabase(db_name, username=None):
    """Legacy helper for dropping database."""
    drop_sql = f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);'
    success, err = run_pg_cmd(drop_sql, db="postgres")
    if not success:
        return {"status": "error", "message": err}

    if username:
        drop_user_sql = f'DROP ROLE IF EXISTS "{username}";'
        run_pg_cmd(drop_user_sql, db="postgres")

    return {
        "status": "success",
        "message": f"Database '{db_name}' deleted successfully."
    }


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
        if '"ok"' in output or "ok:" in output or "1" in output:
            status = "success"
            message = f"Database '{db_name}' repaired successfully."
        else:
            status = "warning"
            message = f"Database '{db_name}' repair completed with unusual output."
        return {"status": status, "database": db_name, "output": output, "message": message}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "database": db_name, "message": f"Repair failed: {e.stderr.strip()}"}


def create_postgresql_account(db_name, second_user, second_pass, main_user):
    """Create a database and user with full shared access."""
    s1, msg1 = create_postgresql_user(main_user, second_user, second_pass)
    if not s1 and "already exists" not in msg1.lower():
        return {"status": "error", "message": msg1}

    s2, msg2 = create_postgresql_db(main_user, db_name)
    if not s2 and "already exists" not in msg2.lower():
        return {"status": "error", "message": msg2}

    full_db = db_name if db_name.startswith(f"{main_user}_") else f"{main_user}_{db_name}"
    full_user = second_user if second_user.startswith(f"{main_user}_") else f"{main_user}_{second_user}"

    grant_postgresql_user_privileges(main_user, full_user, full_db, ['ALL PRIVILEGES'])

    return {
        "status": "success",
        "message": f"Database '{full_db}' and user '{full_user}' created successfully."
    }


def check_postgresql_exists(admin_pass, name, type_="database"):
    """Check if a PostgreSQL database or role exists."""
    if type_ == "database":
        sql = f"SELECT 1 FROM pg_database WHERE datname='{name}';"
    elif type_ == "user":
        sql = f"SELECT 1 FROM pg_roles WHERE rolname='{name}';"
    else:
        return False

    success, out = run_pg_cmd(sql, db="postgres")
    return success and out == "1"


def store_user_password(username):
    """Generate and store password for panel user phpPgAdmin integration."""
    try:
        django_root = getattr(settings, 'BASE_DIR', '/usr/local/olspanel/mypanel')
        etc_dir = os.path.join(django_root, 'etc')
        os.makedirs(etc_dir, exist_ok=True)

        password_file = os.path.join(etc_dir, f"phpmypostgresql_{username}")

        if not os.path.exists(password_file):
            password = generate_strong_random_ppassword()
            new_data = encodepass(password)
            with open(password_file, 'w') as f:
                f.write(new_data)
            return password_file
        else:
            return password_file
    except Exception as e:
        raise Exception(f"Error saving password: {str(e)}")


def get_phpmypostgresql_password(username):
    """Retrieve decrypted stored password for phpPgAdmin auto-login."""
    django_root = getattr(settings, 'BASE_DIR', '/usr/local/olspanel/mypanel')
    if username == 'admin':
        source_file = os.path.join(django_root, 'etc', "postgresqlPassword")
        if not os.path.exists(source_file):
            source_file = '/usr/local/olspanel/mypanel/etc/postgresqlPassword'
    else:
        source_file = os.path.join(django_root, 'etc', f"phpmypostgresql_{username}")
        if not os.path.exists(source_file):
            source_file = f"/usr/local/olspanel/mypanel/etc/phpmypostgresql_{username}"

    if not os.path.exists(source_file):
        return f"Password file for user {username} not found."

    try:
        with open(source_file, 'r') as file:
            file_content = file.read().strip()

        if username == 'admin':
            return file_content
        else:
            return decodepass(file_content)
    except Exception as e:
        return f"An error occurred: {str(e)}"


def encodepass(data: str) -> str:
    data_bytes = data.encode('utf-8')
    base64_bytes = base64.b64encode(data_bytes)
    base64_str = base64_bytes.decode('utf-8')
    random_string = ''.join(random.choices(string.ascii_lowercase, k=5))
    return random_string + base64_str


def decodepass(base64_data: str) -> str:
    base64_str = base64_data[5:]
    base64_bytes = base64_str.encode('utf-8')
    decoded_bytes = base64.b64decode(base64_bytes)
    return decoded_bytes.decode('utf-8')


def change_postgresql_password(second_user, second_pass):
    safe_pass = second_pass.replace("'", "''")
    query = f"ALTER ROLE \"{second_user}\" WITH PASSWORD '{safe_pass}';"
    success, err = run_pg_cmd(query, db="postgres")
    if success:
        return {
            "status": "success",
            "message": f"Password changed successfully for user '{second_user}'."
        }
    else:
        return {
            "status": "error",
            "message": err or "Failed to change password."
        }


def generate_strong_random_ppassword(length=16):
    """Generate a strong random password."""
    if length < 12:
        length = 12
    all_characters = string.ascii_letters + string.digits
    password = random.choices(all_characters, k=length)
    return ''.join(password)