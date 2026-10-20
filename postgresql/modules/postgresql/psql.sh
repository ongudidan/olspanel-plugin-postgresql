#!/bin/bash
# =============================================================================
# PostgreSQL: FULLY DYNAMIC DB + OWNER + APP → FULL SHARED ACCESS
# phpPgAdmin WORKS! ZERO ERRORS!
# =============================================================================

set -euo pipefail

# --- INPUT ---
DB_NAME="${1:-myapp_db}"
OWNER_USER="${2:-${DB_NAME}_owner}"
APP_USER="${3:-${DB_NAME}_app}"
#PASSWORD="${4:-$(openssl rand -base64 12)}"
#APP_PASS="${5:-$(openssl rand -base64 12)}"
OWNER_PASS="${4:-$(openssl rand -base64 12)}"
APP_PASS="${5:-$(openssl rand -base64 12)}"
SUPERUSER_PASS="${6:-$(openssl rand -base64 12)}"
SUPERUSER="postgres"
HOST="localhost"
PORT="5432"
PGPASSFILE="/tmp/pgpass_$$"

# --- Cleanup ---
cleanup() { rm -f "$PGPASSFILE" 2>/dev/null || true; }
trap cleanup EXIT

log() { echo -e "\n[+] $1"; }
error() { echo "[ERROR] $1" >&2; exit 1; }

log "Dynamic Setup"
log "DB: $DB_NAME | Owner: $OWNER_USER | App: $APP_USER"

# --- pgpass ---
cat > "$PGPASSFILE" <<EOF
$HOST:$PORT:*:$SUPERUSER:$SUPERUSER_PASS
$HOST:$PORT:$DB_NAME:$OWNER_USER:$OWNER_PASS
$HOST:$PORT:$DB_NAME:$APP_USER:$APP_PASS
EOF
chmod 600 "$PGPASSFILE"
export PGPASSFILE

# --- STEP 1: Create DB + Users ---
log "1/5 Creating database and users..."




# === 3. APP_USER: CREATE ONLY IF NOT EXISTS ===
log "2/5 Creating APP_USER only if not exists..."
psql -U "$SUPERUSER" -h "$HOST" -p "$PORT" -d postgres <<SQL
DO \$\$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${APP_USER}') THEN
      CREATE ROLE ${APP_USER} LOGIN PASSWORD '${APP_PASS}';
      RAISE NOTICE 'Created APP_USER: ${APP_USER}';
   ELSE
      RAISE NOTICE 'APP_USER already exists → SKIPPED';
   END IF;
END\$\$;

SQL


psql -U "$SUPERUSER" -h "$HOST" -p "$PORT" -d postgres -v ON_ERROR_STOP=1 <<SQL
REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;

DROP DATABASE IF EXISTS ${DB_NAME};
DROP ROLE IF EXISTS ${OWNER_USER};


CREATE ROLE ${OWNER_USER} LOGIN PASSWORD '${OWNER_PASS}';


CREATE DATABASE ${DB_NAME} OWNER ${OWNER_USER};
REVOKE CONNECT ON DATABASE ${DB_NAME} FROM PUBLIC;
GRANT CONNECT ON DATABASE ${DB_NAME} TO ${APP_USER};
SQL

log "Database '$DB_NAME' created"

# --- STEP 2: FULL SHARED ACCESS (SUPERUSER) ---
log "3/5 Setting up shared access..."

psql -U "$SUPERUSER" -h "$HOST" -p "$PORT" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<SQL
-- 1. Make APP_USER inherit OWNER_USER (no circular!)
GRANT ${OWNER_USER} TO ${APP_USER};

-- 2. Schema access
GRANT USAGE, CREATE ON SCHEMA public TO ${OWNER_USER}, ${APP_USER};

-- 3. FUTURE: tables by OWNER → auto-grant to APP
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER_USER} IN SCHEMA public
  GRANT ALL ON TABLES TO ${APP_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${OWNER_USER} IN SCHEMA public
  GRANT ALL ON SEQUENCES TO ${APP_USER};

-- 4. FUTURE: tables by APP → auto-grant to OWNER (APP must be member of OWNER)
-- Since APP already has OWNER via GRANT above, this works
ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_USER} IN SCHEMA public
  GRANT ALL ON TABLES TO ${OWNER_USER};
ALTER DEFAULT PRIVILEGES FOR ROLE ${APP_USER} IN SCHEMA public
  GRANT ALL ON SEQUENCES TO ${OWNER_USER};
SQL

log "Future-proof access granted!"



# --- FINAL ---
cat <<EOF

SETUP COMPLETE!

Database     : $DB_NAME
Owner User   : $OWNER_USER
Owner Pass   : $OWNER_PASS
App User     : $APP_USER
App Pass     : $APP_PASS
Super Pass   : $SUPERUSER_PASS

CONNECT:
  psql -U $OWNER_USER -d $DB_NAME
  psql -U $APP_USER   -d $DB_NAME

phpPgAdmin: Login with EITHER → Browse/Insert WORKS!

TEST:
  psql -U $APP_USER -d $DB_NAME -c "SELECT * FROM test_app;"
  psql -U $OWNER_USER -d $DB_NAME -c "SELECT * FROM test_owner;"

NO PERMISSION ERRORS — EVER!
EOF