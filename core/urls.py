from django.urls import path
from . import views
from . import storage_views
from . import docker_host_views
from . import storage_sync_views
from . import database_views

urlpatterns = [
    # Main app URLs
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('hosts/<int:host_id>/', views.host_detail, name='host_detail'),
    path('hosts/<int:host_id>/databases/add/', views.add_database, name='add_database'),
    path('databases/<int:database_id>/', views.database_detail_page, name='database_detail_page'),
    path('databases/<int:database_id>/connect/', views.database_connect, name='database_connect'),
    path('hosts/add/', views.add_host, name='add_host'),
    path('hosts/add-database-host/', views.add_database_host, name='add_database_host'),
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
    path('api/hosts/validate-remote/', views.validate_remote_host, name='validate_remote_host'),
    path('api/hosts/create-database-host/', views.create_database_host, name='create_database_host'),
    
    # Database management URLs
    path('api/databases/list/', database_views.list_databases, name='list_databases'),
    path('api/databases/create/', database_views.create_database, name='create_database'),
    path('api/databases/<int:database_id>/', database_views.database_detail, name='database_detail'),
    path('api/databases/<int:database_id>/delete/', database_views.delete_database, name='delete_database'),
    path('api/databases/<int:database_id>/dependencies/', database_views.check_database_dependencies, name='check_database_dependencies'),
    
    # Database lifecycle management
    path('api/databases/<int:database_id>/start/', database_views.start_database, name='start_database'),
    path('api/databases/<int:database_id>/stop/', database_views.stop_database, name='stop_database'),
    path('api/databases/<int:database_id>/restart/', database_views.restart_database, name='restart_database'),
    
    # Database monitoring
    path('api/databases/<int:database_id>/status/', database_views.database_status, name='database_status'),
    path('api/databases/<int:database_id>/logs/', database_views.database_logs, name='database_logs'),
    path('api/databases/<int:database_id>/connection/', database_views.database_connection_info, name='database_connection_info'),
    
    # Database utilities
    path('api/databases/postgres-versions/', database_views.available_postgres_versions, name='available_postgres_versions'),
    path('api/databases/validate-name/', database_views.validate_database_name, name='validate_database_name'),
    path('api/databases/check-image/', database_views.check_image_availability, name='check_image_availability'),
    path('api/databases/pull-image/', database_views.pull_postgres_image, name='pull_postgres_image'),
    path('api/databases/check-ports/', database_views.check_port_availability, name='check_port_availability'),
    path('api/databases/snapshots/', database_views.list_available_snapshots, name='list_available_snapshots'),
    path('api/databases/cleanup-snapshots/', database_views.cleanup_orphaned_snapshots, name='cleanup_orphaned_snapshots'),
    
    # Storage configuration URLs
    path('api/storage/options/', storage_views.storage_options, name='storage_options'),
    path('api/storage/configurations/', storage_views.storage_configurations, name='storage_configurations'),
    path('api/storage/configurations/create/', storage_views.create_storage_configuration, name='create_storage_configuration'),
    path('api/storage/configurations/<int:config_id>/apply/', storage_views.apply_storage_configuration, name='apply_storage_configuration'),
    path('api/storage/configurations/<int:config_id>/delete/', storage_views.delete_storage_configuration, name='delete_storage_configuration'),
    path('api/storage/validate/', storage_views.validate_storage_configuration, name='validate_storage_configuration'),
    path('api/storage/recommendations/', storage_views.storage_recommendations, name='storage_recommendations'),
    path('api/storage/disks/<str:disk_name>/info/', storage_views.disk_info, name='disk_info'),
    path('api/storage/discover/', views.discover_storage_options, name='discover_storage_options'),
    path('api/storage/create-pool/', views.create_zfs_pool, name='create_zfs_pool'),
    
    # Docker host setup URLs
    path('api/hosts/docker-host/status/', docker_host_views.docker_host_status, name='docker_host_status'),
    path('api/hosts/docker-host/setup/', docker_host_views.setup_docker_host, name='setup_docker_host'),
    path('api/hosts/docker-host/validate/', docker_host_views.run_docker_host_validation, name='run_docker_host_validation'),
    path('api/hosts/docker-host/validation-status/', docker_host_views.docker_host_validation_status, name='docker_host_validation_status'),
    path('api/hosts/docker-host/summary/', docker_host_views.docker_host_summary, name='docker_host_summary'),
    path('api/hosts/docker-host/remove/', docker_host_views.remove_docker_host, name='remove_docker_host'),
    path('api/hosts/docker-host/detect-os/', docker_host_views.detect_host_os, name='detect_host_os'),
    path('api/hosts/docker-host/install-zfs/', docker_host_views.install_zfs_utilities, name='install_zfs_utilities'),
    path('api/hosts/docker-host/zfs-install-script/', docker_host_views.get_zfs_install_script, name='get_zfs_install_script'),
    path('api/hosts/docker-host/link-storage/', docker_host_views.link_storage_pool, name='link_storage_pool'),
    
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