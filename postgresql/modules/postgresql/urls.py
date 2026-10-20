from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='example_index'),
    path('pdb_make/', views.pdb_make, name='pdb_make'),
    path('postgresql_delete_view/<str:db_name>/', views.postgresql_delete_view, name='postgresql_delete_view'),
    path('phppgadmin/', views.phppgadmin, name='phppgadmin'),
    path('phppgadmin_admin/', views.phppgadmin_admin, name='phppgadmin_admin'),
    path('pdb_pass/<str:db>/', views.pdb_pass, name='pdb_pass'),
    path('home/', views.home, name='psqlhome'),
    path('admin_home/', views.admin_home, name='psqladmin_home'),


]
