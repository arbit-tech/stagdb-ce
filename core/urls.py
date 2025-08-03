from django.urls import path
from . import views
from . import storage_views

urlpatterns = [
    # Main app URLs
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hosts/<int:host_id>/', views.host_detail, name='host_detail'),
    path('hosts/add/', views.add_host, name='add_host'),
    path('storage/', views.storage_config, name='storage_config'),
    
    # API URLs
    path('api/health/', views.health_check, name='health'),
    path('api/vms/', views.vm_list, name='vm_list'),
    path('api/databases/', views.database_list, name='database_list'),
    
    # System validation URLs
    path('api/system/validate/', views.validate_docker_host, name='validate_docker_host'),
    path('api/system/status/', views.docker_host_status, name='docker_host_status'),
    path('api/system/requirements/', views.system_requirements, name='system_requirements'),
    path('api/system/setup/', views.setup_docker_host, name='setup_docker_host'),
    
    # Host validation URLs
    path('api/hosts/<int:host_id>/validate/', views.validate_host, name='validate_host'),
    path('api/hosts/<int:host_id>/remove/', views.remove_host, name='remove_host'),
    path('api/hosts/<int:host_id>/removal-check/', views.host_removal_check, name='host_removal_check'),
    path('api/databases/create/', views.create_database, name='create_database'),
    
    # Storage configuration URLs
    path('api/storage/options/', storage_views.storage_options, name='storage_options'),
    path('api/storage/configurations/', storage_views.storage_configurations, name='storage_configurations'),
    path('api/storage/configurations/create/', storage_views.create_storage_configuration, name='create_storage_configuration'),
    path('api/storage/configurations/<int:config_id>/apply/', storage_views.apply_storage_configuration, name='apply_storage_configuration'),
    path('api/storage/configurations/<int:config_id>/delete/', storage_views.delete_storage_configuration, name='delete_storage_configuration'),
    path('api/storage/validate/', storage_views.validate_storage_configuration, name='validate_storage_configuration'),
    path('api/storage/recommendations/', storage_views.storage_recommendations, name='storage_recommendations'),
    path('api/storage/disks/<str:disk_name>/info/', storage_views.disk_info, name='disk_info'),
]