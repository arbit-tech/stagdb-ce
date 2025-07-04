from django.contrib import admin
from .models import HostVM, Database, DatabaseBranch


@admin.register(HostVM)
class HostVMAdmin(admin.ModelAdmin):
    list_display = ('name', 'ip_address', 'username', 'zfs_pool', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'ip_address', 'username')


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