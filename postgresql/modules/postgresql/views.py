import requests
import os
import stat
import json
import subprocess
import binascii
import zipfile
import shutil
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.http import JsonResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.views import View
from django.contrib.auth.decorators import login_required
from users.models import *
from users.server_core import *
from users.database import *
from django.db import connection
from users.function import *
from users.bandwidth import *
from django.contrib.auth.hashers import make_password
from file_manager.function_file import *
from urllib.parse import urlparse
from django.contrib.auth import update_session_auth_hash, authenticate, logout, login
from django.conf import settings
from users.decorators import *
from whm.decorators import *
from django.views.decorators.clickjacking import xframe_options_exempt
from users.plugin import *
from whm.models import *
from file_manager.models import *
from .postgresql import *


@login_required
@admincheck
def index(request):
    """Main PostgreSQL database management page matching MySQL layout."""
    username = request.user.username
    prefix = f"{username}_"

    database_info = postgresql_filter(prefix)
    databases = database_info.get("databases", [])
    userlists = list_postgresql_users(username)

    return render(request, 'postgresql/index.html', {
        'databases': databases,
        'userlists': userlists,
    })


@login_required
@admincheck
def dbs(request):
    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_make(request):
    """Create a new PostgreSQL database with user prefix."""
    if request.method == 'POST':
        db_name = request.POST.get('dbname', '').strip()

        if not db_name:
            messages.error(request, 'Database name is required.')
            return redirect('/module/postgresql/')

        if len(db_name) < 2:
            messages.error(request, 'Database name must be at least 2 characters long.')
            return redirect('/module/postgresql/')

        # Package database limit check
        try:
            user_data = get_user_data_by_id(request.user.id)
            pkg_id = user_data.get('pkg_id') if user_data else None
            if pkg_id:
                user_package = Package.objects.filter(id=pkg_id).first()
                if user_package and user_package.databases != 0:
                    current_dbs = postgresql_filter(f"{request.user.username}_").get("matched", 0)
                    if current_dbs >= user_package.databases:
                        messages.error(request, 'Database limit exceeded.')
                        return redirect('/module/postgresql/')
        except Exception:
            pass

        success, msg = create_postgresql_db(request.user.username, db_name)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, f"Failed to create database: {msg}")

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_delete(request, db_name):
    """Drop a PostgreSQL database."""
    if request.method == 'POST':
        success, msg = delete_postgresql_db(request.user.username, db_name)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, f"Failed to delete database: {msg}")

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_edit(request, db_name):
    """Rename a PostgreSQL database."""
    username = request.user.username
    prefix = f"{username}_"

    if not db_name.startswith(prefix):
        messages.error(request, 'You are not authorized to edit this database.')
        return redirect('/module/postgresql/')

    suffix = db_name[len(prefix):]

    if request.method == 'POST':
        new_name = request.POST.get('dbname', '').strip()
        if not new_name:
            messages.error(request, 'Database name cannot be empty.')
            return render(request, 'postgresql/db_make.html', {'db_name': suffix, 'full_db': db_name})

        if len(new_name) < 2:
            messages.error(request, 'Database name must be at least 2 characters long.')
            return render(request, 'postgresql/db_make.html', {'db_name': suffix, 'full_db': db_name})

        success, msg = rename_postgresql_db(username, db_name, new_name)
        if success:
            messages.success(request, msg)
            return redirect('/module/postgresql/')
        else:
            messages.error(request, msg)
            return render(request, 'postgresql/db_make.html', {'db_name': suffix, 'full_db': db_name})

    return render(request, 'postgresql/db_make.html', {
        'db_name': suffix,
        'full_db': db_name
    })


@login_required
@admincheck
def postgresql_delete_view(request, db_name):
    """Backward compatibility alias for pdb_delete."""
    return pdb_delete(request, db_name)


@login_required
@admincheck
def pdb_user_add(request):
    """Create a new PostgreSQL database user."""
    if request.method == 'POST':
        db_user = request.POST.get('dbuser', '').strip()
        db_pass = request.POST.get('dbpass', '')
        db_passc = request.POST.get('dbpassc', '')

        if not db_user or not db_pass or not db_passc:
            messages.error(request, 'All fields are required.')
            return redirect('/module/postgresql/')

        if len(db_user) < 2:
            messages.error(request, 'Username must be at least 2 characters long.')
            return redirect('/module/postgresql/')

        if len(db_pass) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return redirect('/module/postgresql/')

        if db_pass != db_passc:
            messages.error(request, 'Passwords do not match.')
            return redirect('/module/postgresql/')

        success, msg = create_postgresql_user(request.user.username, db_user, db_pass)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, f"Failed to create database user: {msg}")

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_user_delete(request):
    """Delete a PostgreSQL database user."""
    if request.method == 'POST':
        db_user = request.POST.get('dbuser', '').strip()
        if not db_user:
            messages.error(request, 'Database user not specified.')
            return redirect('/module/postgresql/')

        success, msg = delete_postgresql_user(request.user.username, db_user)
        if success:
            messages.success(request, msg)
        else:
            messages.error(request, f"Failed to delete database user: {msg}")

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_user_edit(request, db_user):
    """Change password for a PostgreSQL database user."""
    prefix = f"{request.user.username}_"
    if not db_user.startswith(prefix):
        messages.error(request, 'You are not authorized to edit this database user.')
        return redirect('/module/postgresql/')

    if request.method == 'POST':
        db_pass = request.POST.get('dbpass', '')
        db_passc = request.POST.get('dbpassc', '')

        if not db_pass or not db_passc:
            messages.error(request, 'Both password fields are required.')
            return render(request, 'postgresql/pdb_user_edit.html', {'db_user': db_user})

        if len(db_pass) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'postgresql/pdb_user_edit.html', {'db_user': db_user})

        if db_pass != db_passc:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'postgresql/pdb_user_edit.html', {'db_user': db_user})

        success, msg = change_postgresql_user_password(request.user.username, db_user, db_pass)
        if success:
            messages.success(request, msg)
            return redirect('/module/postgresql/')
        else:
            messages.error(request, f"Failed to update password: {msg}")

    return render(request, 'postgresql/pdb_user_edit.html', {'db_user': db_user})


@login_required
@admincheck
def pdb_pass(request, db):
    """Backward compatibility alias for pdb_user_edit."""
    return pdb_user_edit(request, db)


@login_required
@admincheck
def pdb_assign_user(request):
    """Assign user to database (redirects to fine-grained privileges editor)."""
    if request.method == 'POST':
        db_user = request.POST.get('dbuser', '').strip()
        db_name = request.POST.get('dbname', '').strip()

        if not db_user or not db_name:
            messages.error(request, 'Please select both a user and a database.')
            return redirect('/module/postgresql/')

        return redirect('pdb_privileges', db=db_name, db_user=db_user)

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_privileges(request, db, db_user):
    """Manage fine-grained PostgreSQL privileges for user on database."""
    username = request.user.username
    prefix = f"{username}_"

    if not db.startswith(prefix) or not db_user.startswith(prefix):
        messages.error(request, 'You are not authorized to manage privileges for this database/user.')
        return redirect('/module/postgresql/')

    if request.method == 'POST':
        priv_list = [
            'select', 'insert', 'update', 'delete', 'truncate',
            'references', 'trigger', 'create', 'connect', 'temporary',
            'execute', 'usage'
        ]
        selected_privs = []
        for p in priv_list:
            if request.POST.get(p):
                selected_privs.append(p)

        if request.POST.get('all_privileges'):
            selected_privs = ['ALL PRIVILEGES']

        if not selected_privs:
            # Revoke all privileges if none selected
            success, msg = revoke_postgresql_user_privileges(username, db_user, db)
            if success:
                messages.success(request, f"All privileges revoked for {db_user} on {db}.")
            else:
                messages.error(request, f"Failed to revoke privileges: {msg}")
            return redirect('/module/postgresql/')

        success, msg = grant_postgresql_user_privileges(username, db_user, db, selected_privs)
        if success:
            messages.success(request, f"Privileges updated successfully for {db_user} on {db}.")
            return redirect('/module/postgresql/')
        else:
            messages.error(request, f"Failed to update privileges: {msg}")

    current_privs = get_postgresql_user_db_privileges(username, db_user, db)

    return render(request, 'postgresql/pdb_privileges.html', {
        'db': db,
        'db_user': db_user,
        'current_privs': current_privs
    })


@login_required
@admincheck
def pdb_revoke_user(request, db, db_user):
    """Unlink a database user from a PostgreSQL database."""
    username = request.user.username
    prefix = f"{username}_"

    if not db.startswith(prefix) or not db_user.startswith(prefix):
        messages.error(request, 'You are not authorized to unlink this database/user.')
        return redirect('/module/postgresql/')

    success, msg = revoke_postgresql_user_privileges(username, db_user, db)
    if success:
        messages.success(request, f"User {db_user} unlinked from database {db} successfully.")
    else:
        messages.error(request, f"Failed to unlink user: {msg}")

    return redirect('/module/postgresql/')


@login_required
@admincheck
def pdb_export(request, db_name):
    """Export PostgreSQL database snapshot using pg_dump."""
    username = request.user.username
    res = export_postgresql_db(username, db_name)
    status_code = 200 if res.get('status') == 'success' else 400
    return JsonResponse(res, status=status_code)


@login_required
@admincheck
def pdb_repair(request, db_name):
    """Perform table maintenance (REINDEX and VACUUM ANALYZE) on PostgreSQL database."""
    username = request.user.username
    success, msg = repair_postgresql_db(username, db_name)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, f"Repair failed: {msg}")
    return redirect('/module/postgresql/')


@alogin_required
def phppgadmin_admin(request):
    parsed_username = "postgres"

    passw = get_phpmypostgresql_password("admin")
    auto_login_is_enable = (
        passw
        and not passw.startswith("Password file for user")
        and not passw.startswith("An error occurred")
    )

    if not auto_login_is_enable:
        messages.error(request, "Auto login failed.")
        return redirect('/whm/')

    plugin_item = "postgresql"
    headers = get_plugin_headers(plugin_item)
    if not headers:
        headers = {"HTTP_AUTOLOGINUSER": "%dbusername%", "HTTP_AUTOLOGINPASS": "%dbuserpass%"}

    replaced_headers = {}
    for key, val in headers.items():
        val = val.replace('%dbusername%', parsed_username)
        val = val.replace('%dbuserpass%', passw)
        replaced_headers[key] = val

    auto_login_url = get_plugin_config_value('auto_login_url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('auto_login_url', "postgresql")
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', "postgresql")
    if not auto_login_url:
        auto_login_url = "/3rdparty/phppgadmin/redirect.php?auto_login=1"

    target_db = request.GET.get('db')
    if target_db:
        auto_login_url += f"&db={target_db}"

    response = redirect(auto_login_url)

    cookie_prefix = "CUSTOMCOOK_"
    for cookie_name, cookie_value in replaced_headers.items():
        response.set_cookie(
            cookie_prefix + cookie_name,
            cookie_value,
            path='/',
            httponly=True,
            secure=request.is_secure(),
            samesite='Lax',
        )

    return response


@login_required
def phppgadmin(request):
    parsed_username = request.user.username

    passw = get_phpmypostgresql_password(parsed_username)
    if not passw or passw.startswith("Password file") or passw.startswith("An error"):
        ensure_main_pg_user(parsed_username)
        passw = get_phpmypostgresql_password(parsed_username)

    auto_login_is_enable = (
        passw
        and not passw.startswith("Password file for user")
        and not passw.startswith("An error occurred")
    )

    if not auto_login_is_enable:
        messages.error(request, "Auto login failed. Please ensure a PostgreSQL database exists.")
        return redirect('/module/postgresql/')

    plugin_item = "postgresql"
    headers = get_plugin_headers(plugin_item)
    if not headers:
        headers = {"HTTP_AUTOLOGINUSER": "%dbusername%", "HTTP_AUTOLOGINPASS": "%dbuserpass%"}

    replaced_headers = {}
    for key, val in headers.items():
        val = val.replace('%dbusername%', parsed_username)
        val = val.replace('%dbuserpass%', passw)
        replaced_headers[key] = val

    auto_login_url = get_plugin_config_value('auto_login_url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('auto_login_url', "postgresql")
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', "postgresql")
    if not auto_login_url:
        auto_login_url = "/3rdparty/phppgadmin/redirect.php?auto_login=1"

    target_db = request.GET.get('db')
    if target_db:
        prefix = f"{parsed_username}_"
        if not (target_db.startswith(prefix) or target_db == parsed_username):
            return HttpResponseForbidden("You do not have access to this database.")
        auto_login_url += f"&db={target_db}"

    response = redirect(auto_login_url)

    cookie_prefix = "CUSTOMCOOK_"
    for cookie_name, cookie_value in replaced_headers.items():
        response.set_cookie(
            cookie_prefix + cookie_name,
            cookie_value,
            path='/',
            httponly=True,
            secure=request.is_secure(),
            samesite='Lax',
        )

    return response


@login_required
@admincheck
def home(request):
    username_string = request.user.username
    prefix = f"{username_string}_"
    database_info = postgresql_filter(prefix)
    db_count = database_info.get("matched", 0)
    db_size = database_info.get("total_size", "0 MB")

    user_package = Package.objects.filter(
        id=get_user_data_by_id(request.user.id).get('pkg_id')
    ).first()

    if user_package:
        pkg_data = {
            'pdisk_space': check_limit(user_package.disk_space),
            'pdisk_use_db': db_size,
            'pdatabases': check_limit(user_package.databases),
            'pdatabases_use': db_count,
        }
    else:
        pkg_data = {
            'pdisk_space': 0,
            'pdisk_use_db': "0 MB",
            'pdatabases': 0,
            'pdatabases_use': 0,
        }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get("format") == "json":
        return JsonResponse(pkg_data)

    return render(request, "postgresql/home_right.html", {"pkg_data": pkg_data})


@alogin_required
def admin_home(request):
    database_info = postgresql_total_info()
    db_count = database_info.get("total_databases", 0)
    db_size = database_info.get("total_size", "0 MB")

    pkg_data = {
        'pdbsize': db_size,
        'pdb_count': db_count,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get("format") == "json":
        return JsonResponse(pkg_data)

    return render(request, "postgresql/admin_home_top.html", {"pkg_data": pkg_data})