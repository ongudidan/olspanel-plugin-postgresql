from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='postgresql_index'),
    path('dbs/', views.dbs, name='postgresql_dbs'),
    path('pdb_make/', views.pdb_make, name='pdb_make'),
    path('pdb_delete/<str:db_name>/', views.pdb_delete, name='pdb_delete'),
    path('pdb_user_add/', views.pdb_user_add, name='pdb_user_add'),
    path('pdb_user_delete/', views.pdb_user_delete, name='pdb_user_delete'),
    path('pdb_user_edit/<str:db_user>/', views.pdb_user_edit, name='pdb_user_edit'),
    path('pdb_assign_user/', views.pdb_assign_user, name='pdb_assign_user'),
    path('pdb_privileges/<str:db>/<str:db_user>/', views.pdb_privileges, name='pdb_privileges'),
    path('pdb_revoke_user/<str:db>/<str:db_user>/', views.pdb_revoke_user, name='pdb_revoke_user'),
    path('pdb_export/<str:db_name>/', views.pdb_export, name='pdb_export'),
    path('pdb_repair/<str:db_name>/', views.pdb_repair, name='pdb_repair'),
    path('phppgadmin/', views.phppgadmin, name='phppgadmin'),
    path('phppgadmin_admin/', views.phppgadmin_admin, name='phppgadmin_admin'),
    path('home/', views.home, name='psqlhome'),
    path('admin_home/', views.admin_home, name='psqladmin_home'),

    # Aliases / backward compatibility
    path('example_index', views.index, name='example_index'),
    path('pdb_pass/<str:db>/', views.pdb_pass, name='pdb_pass'),
    path('postgresql_delete_view/<str:db_name>/', views.postgresql_delete_view, name='postgresql_delete_view'),
]
