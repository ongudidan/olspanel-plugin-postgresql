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
from django.http import JsonResponse,Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy,reverse
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.views import View
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from users.models import * 
from users.server_core import *  # Import your function
from users.database import *  # Import your function
from django.db import connection
from users.function import *  # Import your function
from users.bandwidth import *  # Import your function
from django.contrib.auth.hashers import make_password
from ftplib import FTP, error_perm
from file_manager.function_file import *
from ftplib import FTP
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
    db_username = request.user.username  # Get the logged-in user's username
   
    
    # Example: could be fetched dynamically or from request
    prefix = f"{db_username}_"
    #prefix = f"sabinaxx_"

    database_info = postgresql_filter(prefix)

    
   
    databases = database_info.get("databases", [])
   

    return render(request, 'postgresql/index.html', {
        'databases': databases,
        
    })
    
    
    

@login_required
@admincheck
def dbs(request):
    return render(request, 'postgresql/index.html', {'title': 'Example Plugin'})
    
@login_required
@admincheck
def pdb_make(request):
    username_string = request.user.username
    if request.method == 'POST':
        db = request.POST.get('db') 
        db_user = request.POST.get('dbuser')  # Get the database user from the form
        db_pass = request.POST.get('dbpass')  # Get the database password from the form
        db_passc = request.POST.get('dbpassc')  # Get the confirm password from the form
        user_package = Package.objects.filter(id=get_user_data_by_id(request.user.id).get('pkg_id')).first()
        prefix = f"{username_string}_"
        database_info = postgresql_filter(prefix)
        db_count = database_info.get("matched", 0)
        
         # Check if the user's package allows more databases
        if user_package.databases != 0 and db_count >= user_package.databases:
            messages.error(request, 'Database limit exceeded.')
            return render(request, 'postgresql/db_user_make.html')  # Correct template to re-render the form
            
            
        # Validate inputs
        if not db_user or not db_pass or not db_passc or not db:
            messages.error(request, 'All fields are required.')
            return render(request, 'postgresql/db_user_make.html')  # Re-render the form with the error message

        if len(db_user) < 2:
            messages.error(request, 'Username must be at least 2 characters long.')
            return render(request, 'postgresql/db_user_make.html')  # Re-render the form with the error message
            
        if len(db) < 2:
            messages.error(request, 'Databse must be at least 2 characters long.')
            return render(request, 'postgresql/db_user_make.html')  # Re-render the form with the error message    

        if len(db_pass) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'postgresql/db_user_make.html')  # Re-render the form with the error message

        if db_pass != db_passc:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'postgresql/db_user_make.html')  # Re-render the form with the error message
            
             

        
       
       
        
        
        # Call your shell function
        creation_result = create_postgresql_account(
            db_name=f"{username_string}_{db}",
            second_user=f"{username_string}_{db_user}",
            second_pass=db_pass,
            main_user=username_string
        )

        # Check result and respond
        if creation_result.get("status") == "success":
            messages.success(request, f"✅ Database '{db}' and user '{db_user}' created successfully.")
            return redirect('/module/postgresql/')  # redirect page
        else:
            messages.error(request, f"❌ Failed: {creation_result.get('message')}")

    return render(request, 'postgresql/db_user_make.html')  # Render the database creation form  



    
    

    
    
@login_required
@admincheck
def postgresql_delete_view(request, db_name):
    dbx = replace_first_with_underscore(db_name)
    db_username = request.user.username
    full_db_name = f"{db_username}_{dbx}"

    if request.method == 'POST':
        info = get_users_for_pdatabase(full_db_name)
        owner = info.get("owner")

        if info["status"] == "success" and owner:
            result = delete_pdatabase(full_db_name, owner)
            messages.success(request,f"Database {full_db_name} deleted with owner {owner}")
        else:
            messages.error(request,f"Could not find owner for {full_db_name}: {info}")

    return redirect('/module/postgresql/')


    

            

@login_required
@admincheck
def pdb_pass(request, db):
    dbx = replace_first_with_underscore(db)  # Modify the database name if needed
    db_username = request.user.username
    db = f"{db_username}_{dbx}"

    if request.method == 'POST':
        db_pass = request.POST.get('dbpass')   # New password
        db_passc = request.POST.get('dbpassc') # Confirm password

        # Validate required input
        if not db_pass or not db_passc:
            messages.error(request, 'Both password fields are required.')
            return render(request, 'postgresql/db_pass_change.html')

        if len(db_pass) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
            return render(request, 'postgresql/db_pass_change.html')

        if db_pass != db_passc:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'postgresql/db_pass_change.html')

        # Admin credentials (replace with your secure fetch method later)
        

        # Get user linked to this database
        info = get_users_for_pdatabase(db)
        owner = info.get("owner")

        

        if not owner:
            messages.error(request, f"No postgresql user found for database '{db}'.")
            return redirect('/module/postgresql/')

        # Change password using Python function
        creation_result = change_postgresql_password(
            second_user=owner,
            second_pass=db_pass
        )

        # Handle result
        if creation_result.get("status") == "success":
            messages.success(request, f"✅ Password updated successfully for user '{owner}'.")
            return redirect('/module/postgresql/')
        else:
            messages.error(request, f"❌ Failed: {creation_result.get('message')}")

    return render(request, 'postgresql/db_pass_change.html' ,{'db': db})
    
    


@alogin_required
def phppgadmin_admin(request):
    
    parsed_username = "postgres"
    

    # Get stored password for this user
    passw = get_phpmypostgresql_password("admin")
    auto_login_is_enable = (
        passw
        and not passw.startswith("Password file for user")
        and not passw.startswith("An error occurred")
    )

    if not auto_login_is_enable:
        messages.error(request, "Auto login failed.")
        return redirect('/whm/')

    plugin_item = "phppgadmin"
    headers = get_plugin_headers(plugin_item)
    if not headers:
        headers = get_plugin_headers("postgresql")
    if not headers:
        headers = {"HTTP_AUTOLOGINUSER": "%dbusername%", "HTTP_AUTOLOGINPASS": "%dbuserpass%"}

    # Replace placeholders in headers
    replaced_headers = {}
    for key, val in headers.items():
        val = val.replace('%dbusername%', parsed_username)
        val = val.replace('%dbuserpass%', passw)
        replaced_headers[key] = val

    # Get login URL
    auto_login_url = get_plugin_config_value('auto_login_url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('auto_login_url', "postgresql")
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', "postgresql")
    if not auto_login_url:
        auto_login_url = "/3rdparty/phppgadmin/redirect.php?auto_login=1"

    response = redirect(auto_login_url)

    # Set secure cookies
    cookie_prefix = "CUSTOMCOOK_"
    for cookie_name, cookie_value in replaced_headers.items():
        response.set_cookie(
            cookie_prefix + cookie_name,
            cookie_value,
            httponly=True,
            secure=True,
            samesite='Lax',
        )

    return response


@login_required
def phppgadmin(request):
    
    parsed_username = request.user.username
    

    # Get stored password for this user
    passw = get_phpmypostgresql_password(parsed_username)
    auto_login_is_enable = (
        passw
        and not passw.startswith("Password file for user")
        and not passw.startswith("An error occurred")
    )

    if not auto_login_is_enable:
        messages.error(request, "Auto login failed add at a databse for auto login.")
        return redirect('/')

    plugin_item = "phppgadmin"
    headers = get_plugin_headers(plugin_item)
    if not headers:
        headers = get_plugin_headers("postgresql")
    if not headers:
        headers = {"HTTP_AUTOLOGINUSER": "%dbusername%", "HTTP_AUTOLOGINPASS": "%dbuserpass%"}

    # Replace placeholders in headers
    replaced_headers = {}
    for key, val in headers.items():
        val = val.replace('%dbusername%', parsed_username)
        val = val.replace('%dbuserpass%', passw)
        replaced_headers[key] = val

    # Get login URL
    auto_login_url = get_plugin_config_value('auto_login_url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('auto_login_url', "postgresql")
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', plugin_item)
    if not auto_login_url:
        auto_login_url = get_plugin_config_value('url', "postgresql")
    if not auto_login_url:
        auto_login_url = "/3rdparty/phppgadmin/redirect.php?auto_login=1"

    response = redirect(auto_login_url)

    # Set secure cookies
    cookie_prefix = "CUSTOMCOOK_"
    for cookie_name, cookie_value in replaced_headers.items():
        response.set_cookie(
            cookie_prefix + cookie_name,
            cookie_value,
            httponly=True,
            secure=True,
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

    # ✅ If it's an AJAX/JSON request → return JSON
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get("format") == "json":
        return JsonResponse(pkg_data)

    # ✅ Otherwise → render HTML
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
    

    # ✅ If it's an AJAX/JSON request → return JSON
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get("format") == "json":
        return JsonResponse(pkg_data)

    # ✅ Otherwise → render HTML
    return render(request, "postgresql/admin_home_top.html", {"pkg_data": pkg_data})   