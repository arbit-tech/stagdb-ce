from django.urls import path
from . import views
from . import storage_views
from . import docker_host_views
from . import storage_sync_views

urlpatterns = [
    # Main app URLs
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hosts/<int:host_id>/', views.host_detail, name='host_detail'),
    path('hosts/add/', views.add_host, name='add_host'),
    path('hosts/docker-setup/', docker_host_views.docker_host_setup_wizard, name='docker_host_setup'),
    path('storage/', views.storage_config, name='storage_config'),
    path('storage/sync/', views.storage_sync_dashboard, name='storage_sync_dashboard'),
    
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
    
    # Docker host setup URLs
    path('api/hosts/docker-host/status/', docker_host_views.docker_host_status, name='docker_host_status'),
    path('api/hosts/docker-host/setup/', docker_host_views.setup_docker_host, name='setup_docker_host'),
    path('api/hosts/docker-host/validate/', docker_host_views.run_docker_host_validation, name='run_docker_host_validation'),
    path('api/hosts/docker-host/validation-status/', docker_host_views.docker_host_validation_status, name='docker_host_validation_status'),
    path('api/hosts/docker-host/summary/', docker_host_views.docker_host_summary, name='docker_host_summary'),
    path('api/hosts/docker-host/remove/', docker_host_views.remove_docker_host, name='remove_docker_host'),
    
    # Storage synchronization URLs
    path('api/storage/sync/status/', storage_sync_views.storage_sync_status, name='storage_sync_status'),
    path('api/storage/sync/health-check/', storage_sync_views.run_storage_health_check, name='run_storage_health_check'),
    path('api/storage/sync/reconcile/', storage_sync_views.run_reality_reconciliation, name='run_reality_reconciliation'),
    path('api/storage/sync/drift-detection/', storage_sync_views.run_drift_detection, name='run_drift_detection'),
    path('api/storage/sync/auto-remediate/', storage_sync_views.run_auto_remediation, name='run_auto_remediation'),
    path('api/storage/sync/full-sync/', storage_sync_views.run_full_sync, name='run_full_sync'),
    path('api/storage/sync/validate-operation/', storage_sync_views.validate_storage_before_operation, name='validate_storage_before_operation'),
    path('api/storage/sync/health/<int:config_id>/', storage_sync_views.get_storage_health_details, name='get_storage_health_details'),
    path('api/storage/sync/orphaned-pools/', storage_sync_views.list_orphaned_pools, name='list_orphaned_pools'),
    path('api/storage/sync/adopt-pool/', storage_sync_views.adopt_orphaned_pool, name='adopt_orphaned_pool'),
]