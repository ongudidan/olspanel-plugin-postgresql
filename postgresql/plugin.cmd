#!/bin/bash
set -e

# ==============================================================================
# OLSPanel PostgreSQL & phpPgAdmin Plugin Installer Script
# ==============================================================================

# Detect OLSPanel base directory
BASE_DIR="/usr/local/olspanel/mypanel"
if [ ! -d "$BASE_DIR" ]; then
  BASE_DIR="$(pwd)"
  if [ ! -f "$BASE_DIR/manage.py" ]; then
    BASE_DIR="$(dirname "$(dirname "$BASE_DIR")")"
  fi
fi

echo "🚀 OLSPanel base directory detected: $BASE_DIR"

# 1. Deploy the Django PostgreSQL module
MODULE_SRC="$BASE_DIR/3rdparty/postgresql/modules/postgresql"
MODULE_DEST="$BASE_DIR/modules/postgresql"

if [ -d "$MODULE_SRC" ]; then
  mkdir -p "$MODULE_DEST"
  cp -rf "$MODULE_SRC"/* "$MODULE_DEST"/
  sed -i 's/\r$//' "$MODULE_DEST/psql.sh" 2>/dev/null || true
  chmod +x "$MODULE_DEST/psql.sh" 2>/dev/null || true
  chown -R www-data:www-data "$MODULE_DEST" 2>/dev/null || true
  chmod -R 755 "$MODULE_DEST" 2>/dev/null || true
  echo "✅ Django PostgreSQL module deployed to $MODULE_DEST"
else
  echo "⚠️ Warning: Django module source not found at $MODULE_SRC"
fi

# 2. Deploy phpPgAdmin web interface to 3rdparty
PGADMIN_SRC="$BASE_DIR/3rdparty/postgresql/phppgadmin"
PGADMIN_DEST="$BASE_DIR/3rdparty/phppgadmin"

if [ -d "$PGADMIN_SRC" ]; then
  mkdir -p "$PGADMIN_DEST"
  cp -rf "$PGADMIN_SRC"/* "$PGADMIN_DEST"/
  chown -R www-data:www-data "$PGADMIN_DEST" 2>/dev/null || true
  chmod -R 755 "$PGADMIN_DEST" 2>/dev/null || true
  echo "✅ phpPgAdmin web interface deployed to $PGADMIN_DEST"
fi

# 3. Deploy configuration files to $BASE_DIR/plugin/
mkdir -p "$BASE_DIR/plugin"

for conf_name in "plugin_postgresql.conf" "plugin_phppgadmin.conf" "postgresql.conf" "phppgadmin.conf"; do
  if [ -f "$BASE_DIR/3rdparty/postgresql/$conf_name" ]; then
    target_name=$(echo "$conf_name" | sed 's/^plugin_//')
    cp -f "$BASE_DIR/3rdparty/postgresql/$conf_name" "$BASE_DIR/plugin/$target_name"
    chown www-data:www-data "$BASE_DIR/plugin/$target_name" 2>/dev/null || true
  fi
done

for json_name in "plugin_postgresql.json" "plugin_phppgadmin.json" "postgresql.json" "phppgadmin.json"; do
  if [ -f "$BASE_DIR/3rdparty/postgresql/$json_name" ]; then
    target_name=$(echo "$json_name" | sed 's/^plugin_//')
    cp -f "$BASE_DIR/3rdparty/postgresql/$json_name" "$BASE_DIR/plugin/$target_name"
    chown www-data:www-data "$BASE_DIR/plugin/$target_name" 2>/dev/null || true
  fi
done
echo "✅ Plugin configurations deployed to $BASE_DIR/plugin"

# 4. Deploy SVG & PNG Icons
mkdir -p "$BASE_DIR/media/icon"
if [ -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.svg" ]; then
  cp -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.svg" "$BASE_DIR/media/icon/postgresql.svg"
  cp -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.svg" "$BASE_DIR/media/icon/phppgadmin.svg" 2>/dev/null || true
  chown www-data:www-data "$BASE_DIR/media/icon/postgresql.svg" "$BASE_DIR/media/icon/phppgadmin.svg" 2>/dev/null || true
  chmod 644 "$BASE_DIR/media/icon/postgresql.svg" "$BASE_DIR/media/icon/phppgadmin.svg" 2>/dev/null || true
fi

if [ -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.png" ]; then
  cp -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.png" "$BASE_DIR/media/icon/postgresql.png"
  cp -f "$BASE_DIR/3rdparty/postgresql/plugin_icon.png" "$BASE_DIR/media/icon/phppgadmin.png" 2>/dev/null || true
  chown www-data:www-data "$BASE_DIR/media/icon/postgresql.png" "$BASE_DIR/media/icon/phppgadmin.png" 2>/dev/null || true
  chmod 644 "$BASE_DIR/media/icon/postgresql.png" "$BASE_DIR/media/icon/phppgadmin.png" 2>/dev/null || true
fi
echo "✅ Vector and PNG icons deployed to $BASE_DIR/media/icon/"

# 5. Detect and Install PostgreSQL Server if not installed
if ! command -v psql >/dev/null 2>&1; then
  echo "📦 Installing PostgreSQL server & client packages..."
  if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y 2>/dev/null || true
    apt-get install -y --no-install-recommends postgresql postgresql-contrib
  elif command -v dnf >/dev/null 2>&1; then
    dnf -y install postgresql-server postgresql-contrib postgresql || true
    /usr/bin/postgresql-setup --initdb 2>/dev/null || true
  elif command -v yum >/dev/null 2>&1; then
    yum -y install postgresql-server postgresql-contrib postgresql || true
    /usr/bin/postgresql-setup --initdb 2>/dev/null || true
  fi
fi

# Ensure PostgreSQL service is enabled and started
systemctl enable postgresql 2>/dev/null || true
systemctl restart postgresql 2>/dev/null || systemctl start postgresql 2>/dev/null || true

# 6. Setup PostgreSQL Admin User & Password
mkdir -p "$BASE_DIR/etc"
ADMIN_PASS_FILE="$BASE_DIR/etc/postgresqlPassword"
if [ ! -f "$ADMIN_PASS_FILE" ] || [ ! -s "$ADMIN_PASS_FILE" ]; then
  # Generate strong random 16-character alphanumeric password
  ADMIN_PASS=$(head -c 32 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9' | head -c 16)
  echo "$ADMIN_PASS" > "$ADMIN_PASS_FILE"
  chmod 600 "$ADMIN_PASS_FILE"
  chown www-data:www-data "$ADMIN_PASS_FILE" 2>/dev/null || true
  echo "🔑 Generated new PostgreSQL admin password in $ADMIN_PASS_FILE"
else
  ADMIN_PASS=$(head -n 1 "$ADMIN_PASS_FILE" | tr -d '\r\n')
  echo "🔑 Using existing PostgreSQL admin password from $ADMIN_PASS_FILE"
fi

# Secure postgres user password and client authentication
if command -v psql >/dev/null 2>&1; then
  echo "🔒 Setting PostgreSQL postgres superuser password..."
  PG_HBA=$(find /etc/postgresql /var/lib/pgsql /var/lib/postgresql -type f -name "pg_hba.conf" 2>/dev/null | head -n1)
  if [ -n "$PG_HBA" ]; then
    cp -a "$PG_HBA" "${PG_HBA}.bak" 2>/dev/null || true
  fi

  # Attempt password change via runuser/su as postgres user
  runuser -l postgres -c "psql -v ON_ERROR_STOP=1 -q -c \"ALTER USER postgres WITH PASSWORD '$ADMIN_PASS';\"" 2>/dev/null || \
  su - postgres -c "psql -v ON_ERROR_STOP=1 -q -c \"ALTER USER postgres WITH PASSWORD '$ADMIN_PASS';\"" 2>/dev/null || \
  PGPASSWORD="$ADMIN_PASS" psql -U postgres -h localhost -c "SELECT 1;" 2>/dev/null || true

  # Ensure password authentication is enabled in pg_hba.conf
  if [ -n "$PG_HBA" ]; then
    sed -i -E 's/(local\s+all\s+(postgres|all)\s+)peer/\1scram-sha-256/g' "$PG_HBA" 2>/dev/null || true
    sed -i -E 's/(local\s+all\s+(postgres|all)\s+)ident/\1scram-sha-256/g' "$PG_HBA" 2>/dev/null || true
    sed -i -E 's/(host\s+all\s+all\s+127\.0\.0\.1\/32\s+)ident/\1scram-sha-256/g' "$PG_HBA" 2>/dev/null || true
    sed -i -E 's/(host\s+all\s+all\s+::1\/128\s+)ident/\1scram-sha-256/g' "$PG_HBA" 2>/dev/null || true
    systemctl restart postgresql 2>/dev/null || true
  fi
fi

# 7. Install PHP PostgreSQL extensions for CLI and OpenLiteSpeed LSPHP
echo "🐘 Installing PHP PostgreSQL client extensions..."
if command -v apt-get >/dev/null 2>&1; then
  apt-get install -y --no-install-recommends php-pgsql 2>/dev/null || true
  apt-get install -y --no-install-recommends lsphp81-pgsql lsphp82-pgsql lsphp83-pgsql lsphp84-pgsql lsphp85-pgsql 2>/dev/null || true
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y php-pgsql lsphp81-pgsql lsphp82-pgsql lsphp83-pgsql lsphp84-pgsql 2>/dev/null || true
elif command -v yum >/dev/null 2>&1; then
  yum install -y php-pgsql lsphp81-pgsql lsphp82-pgsql lsphp83-pgsql lsphp84-pgsql 2>/dev/null || true
fi

# 8. Asynchronously restart OLSPanel backend & OpenLiteSpeed web server
if systemctl is-active --quiet cp 2>/dev/null; then
  (sleep 2 && systemctl restart cp) &
  echo "🔄 Scheduled OLSPanel backend restart..."
fi

if [ -x /usr/local/lsws/bin/lswsctrl ]; then
  (sleep 3 && /usr/local/lsws/bin/lswsctrl restart) &
  echo "🔄 Scheduled OpenLiteSpeed web server reload..."
fi

echo "🎉 PostgreSQL & phpPgAdmin plugin installed successfully!"
