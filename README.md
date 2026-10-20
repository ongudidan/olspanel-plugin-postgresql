# OLSPanel PostgreSQL & phpPgAdmin Plugin

An official plugin for **OLSPanel** providing complete lifecycle management for **PostgreSQL** relational database servers, user self-service provisioning, administrative metrics, and integrated **phpPgAdmin** web GUI with seamless single sign-on (SSO).

---

## Features

- **PostgreSQL Server Management**: Automated installation, service control, and secure configuration out-of-the-box.
- **phpPgAdmin Web GUI**: Pre-bundled and configured phpPgAdmin 7.13.0 interface with automated 1-click SSO login for both WHM Admins and end users.
- **User Self-Service Provisioning**: End users can create databases, manage database users, change passwords, and drop databases directly from their user dashboard.
- **Role & Privilege Automation**: Smart role architecture (`owner_user` + `app_user` + main account) with automated cross-grants and default table/sequence privileges ensuring zero permission issues in web applications and phpPgAdmin.
- **Dashboard Widgets & Quotas**: Real-time storage usage monitoring, database quotas, and interactive metrics banners integrated into both WHM Admin and User dashboards.
- **PHP Driver Auto-Provisioning**: Automated setup for system PHP CLI and OpenLiteSpeed LSPHP PostgreSQL extensions (`pdo_pgsql`, `pgsql`, `lsphp*-pgsql`).

---

## Installation

*Note: The command line installation instructions must be run with root/administrative privileges (e.g. prefix with `sudo` or run directly as root depending on your system configuration).*

### Method 1: Direct Command Line (Recommended)
You can install the latest release directly:
```bash
install_cp_plugin https://github.com/ongudidan/olspanel-plugin-postgresql/releases/latest/download/postgresql.zip
```

Or target a specific version (e.g., `v1.0.0`):
```bash
install_cp_plugin https://github.com/ongudidan/olspanel-plugin-postgresql/releases/download/v1.0.0/postgresql_v1.0.0.zip
```

### Method 2: Manual Web UI
1. Go to the **Releases** page of this repository.
2. Download either `postgresql.zip` or the version-specific `postgresql_vX.Y.Z.zip` asset.
3. Log into your **OLSPanel Admin Control Panel**.
4. Navigate to **Plugins** -> **Install Plugin** and upload the downloaded zip.
5. Wait for the automatic reload to complete.

---

## Directory Structure

```text
olspanel-plugin-postgresql/
├── .github/
│   └── workflows/
│       └── release.yml              # Automated release pipeline
├── .gitignore
├── README.md
└── postgresql/                      # Plugin payload directory
    ├── plugin.cmd                   # Installation & orchestration hook
    ├── plugin_icon.png              # Panel navigation icon (PNG)
    ├── plugin_icon.svg              # Vector logo (SVG)
    ├── plugin_postgresql.conf       # OLSPanel plugin descriptor
    ├── plugin_postgresql.json       # Panel navigation menu registration
    ├── plugin_phppgadmin.conf       # phpPgAdmin descriptor
    ├── plugin_phppgadmin.json       # phpPgAdmin navigation links
    ├── modules/
    │   └── postgresql/              # Django application module
    │       ├── __init__.py
    │       ├── apps.py              # AppConfig definition
    │       ├── version              # Version tracker
    │       ├── psql.sh              # Database & user creation script
    │       ├── postgresql.py        # Management helper methods
    │       ├── urls.py              # Django URL routing
    │       ├── views.py             # Django views & SSO handlers
    │       └── templates/           # User & Admin templates
    │           └── postgresql/
    └── phppgadmin/                  # phpPgAdmin web management application
```

---

## Development & Packing

To pack the plugin manually into a deployable zip archive, run this from the root of the repository:
```bash
zip -r postgresql.zip postgresql/ -x "*/.git*" -x "*.git*"
```

---

## Release Automation

### Option 1: Trigger via GitHub UI (Auto-increment)
1. Navigate to the **Actions** tab on GitHub.
2. Select the **Build and Release OLSPanel PostgreSQL Plugin** workflow.
3. Click the **Run workflow** button, select version level increment (`patch`, `minor`, `major`), and run.
4. The system will automatically compute the next version, tag it, and publish the release.

### Option 2: Manual Tag Push
If you prefer manual versioning:
```bash
git tag v1.0.0
git push origin v1.0.0
```
This triggers the Action to compile and publish that exact version.
