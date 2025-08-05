from django.contrib import admin
from .models import HostVM, Database, DatabaseBranch, StorageConfiguration, StorageQuota


@admin.register(HostVM)
class HostVMAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'username', 'zfs_pool', 'storage_config', 'validation_status', 'is_docker_host', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_docker_host', 'validation_status', 'created_at')
    search_fields = ('name', 'ip_address', 'username', 'zfs_pool')
    readonly_fields = ('created_at', 'updated_at', 'last_validated')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'ip_address', 'username', 'ssh_key', 'password')
        }),
        ('Storage Configuration', {
            'fields': ('storage_config', 'zfs_pool')
        }),
        ('Host Type', {
            'fields': ('is_docker_host',)
        }),
        ('Validation Status', {
            'fields': ('validation_status', 'last_validated', 'validation_report'),
            'classes': ('collapse',)
        }),
        ('System Information', {
            'fields': ('os_info', 'docker_version', 'docker_compose_version', 'zfs_version', 'zfs_pools', 'system_resources'),
            'classes': ('collapse',)
        }),
        ('Status & Timestamps', {
            'fields': ('is_active', 'created_at', 'updated_at')
        })
    )


@admin.register(Database)
class DatabaseAdmin(admin.ModelAdmin):
    list_display = ('name', 'host_vm', 'db_type', 'db_version', 'port', 'is_active', 'created_at')
    list_filter = ('db_type', 'db_version', 'is_active', 'created_at')
    search_fields = ('name', 'host_vm__name')


@admin.register(DatabaseBranch)
class DatabaseBranchAdmin(admin.ModelAdmin):
    list_display = ('database', 'name', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('database__name', 'name')


@admin.register(StorageConfiguration)
class StorageConfigurationAdmin(admin.ModelAdmin):
    list_display = ('name', 'storage_type', 'get_pool_name', 'is_configured', 'is_active', 'created_at')
    list_filter = ('storage_type', 'pool_type', 'is_configured', 'is_active', 'created_at')
    search_fields = ('name', 'existing_pool_name', 'pool_name')
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'storage_type', 'pool_type')
        }),
        ('Configuration Details', {
            'fields': ('existing_pool_name', 'dedicated_disks', 'image_file_path', 'image_file_size_gb', 
                      'sparse_file', 'storage_directory', 'cache_disks', 'data_disks'),
            'classes': ('collapse',)
        }),
        ('Pool Settings', {
            'fields': ('pool_name', 'compression', 'dedup')
        }),
        ('Status', {
            'fields': ('is_configured', 'is_active', 'configuration_error')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_pool_name(self, obj):
        return obj.get_pool_name()
    get_pool_name.short_description = 'Pool Name'


@admin.register(StorageQuota)
class StorageQuotaAdmin(admin.ModelAdmin):
    list_display = ('storage_config', 'dataset_name', 'quota_gb', 'used_gb', 'get_usage_percentage', 'is_quota_exceeded')
    list_filter = ('storage_config', 'created_at')
    search_fields = ('dataset_name', 'storage_config__name')
    readonly_fields = ('created_at', 'updated_at')
    
    def get_usage_percentage(self, obj):
        return f"{obj.get_usage_percentage():.1f}%"
    get_usage_percentage.short_description = 'Usage %'