from django.db import models
from django.contrib.auth.models import User


class HostVM(models.Model):
    name = models.CharField(max_length=100)
    ip_address = models.GenericIPAddressField()
    username = models.CharField(max_length=50)
    ssh_key = models.TextField(blank=True)
    password = models.CharField(max_length=255, blank=True)
    zfs_pool = models.CharField(max_length=100, blank=True)
    storage_config = models.ForeignKey('StorageConfiguration', on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Docker host flag
    is_docker_host = models.BooleanField(default=False)
    
    # Validation status
    last_validated = models.DateTimeField(null=True, blank=True)
    validation_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('valid', 'Valid'),
        ('warning', 'Warning'),
        ('invalid', 'Invalid'),
        ('error', 'Error')
    ], default='pending')
    validation_report = models.JSONField(default=dict, blank=True)
    
    # System information
    os_info = models.JSONField(default=dict, blank=True)
    docker_version = models.CharField(max_length=50, blank=True)
    docker_compose_version = models.CharField(max_length=50, blank=True)
    zfs_version = models.CharField(max_length=50, blank=True)
    zfs_pools = models.JSONField(default=list, blank=True)
    system_resources = models.JSONField(default=dict, blank=True)
    
    @classmethod
    def get_or_create_docker_host(cls):
        """Get or create Docker host entry"""
        docker_host, created = cls.objects.get_or_create(
            name='docker-host',
            defaults={
                'ip_address': '172.17.0.1',  # Docker host IP
                'username': 'docker-host',
                'is_active': True,
                'is_docker_host': True,
                'zfs_pool': ''
            }
        )
        return docker_host, created
    
    def validate_host_system(self):
        """Run validation on this host system"""
        from .host_validator import HostValidator
        
        validator = HostValidator()
        validation_results = validator.validate_all()
        
        # Update validation status
        self.validation_status = validation_results.get('overall_status', 'unknown')
        self.validation_report = validation_results
        self.last_validated = validator.validation_timestamp
        
        # Extract system info
        system_info = validation_results.get('system_info', {})
        if system_info:
            self.os_info = system_info
        
        # Extract component versions
        docker_info = validation_results.get('docker_engine', {}).get('info', {})
        if 'docker_version' in docker_info:
            self.docker_version = docker_info['docker_version']
        
        docker_compose_info = validation_results.get('docker_compose', {}).get('info', {})
        if 'docker_compose_version' in docker_compose_info:
            self.docker_compose_version = docker_compose_info['docker_compose_version']
        
        zfs_info = validation_results.get('zfs_utilities', {}).get('info', {})
        if 'zfs_version' in zfs_info:
            self.zfs_version = zfs_info['zfs_version']
        
        # Extract ZFS pools
        pools_info = validation_results.get('zfs_pools', {}).get('info', {})
        if 'pools' in pools_info:
            self.zfs_pools = pools_info['pools']
            # Set default pool if available and not already set
            healthy_pools = [p for p in pools_info['pools'] if p.get('health') == 'ONLINE']
            if healthy_pools and not self.zfs_pool:
                self.zfs_pool = healthy_pools[0]['name']
        
        self.save()
        return validation_results
    
    def can_create_databases(self):
        """Check if this host can create databases"""
        return self.validation_status in ['valid', 'warning'] and self.is_active
    
    def has_databases(self):
        """Check if this host has any databases"""
        return self.database_set.filter(is_active=True).exists()
    
    def get_database_count(self):
        """Get count of active databases on this host"""
        return self.database_set.filter(is_active=True).count()
    
    def can_be_removed(self):
        """Check if this host can be safely removed"""
        return not self.has_databases()
    
    def get_removal_blockers(self):
        """Get list of reasons why host cannot be removed"""
        blockers = []
        
        if self.has_databases():
            db_count = self.get_database_count()
            blockers.append(f"{db_count} active database{'s' if db_count != 1 else ''} running on this host")
        
        return blockers
    
    def get_validation_summary(self):
        """Get a summary of validation status"""
        if not self.validation_report:
            return {
                'status': 'not_validated',
                'message': 'Host validation not yet performed',
                'can_create_databases': False
            }
        
        return {
            'status': self.validation_status,
            'message': self.validation_report.get('message', 'No message'),
            'last_validated': self.last_validated.isoformat() if self.last_validated else None,
            'can_create_databases': self.can_create_databases(),
            'components': self._get_component_summary()
        }
    
    def _get_component_summary(self):
        """Extract component summary from validation report"""
        if not self.validation_report:
            return {}
        
        components = {}
        component_mapping = {
            'container_environment': 'Container Environment',
            'docker_access': 'Docker Access',
            'docker_engine': 'Docker Engine',
            'docker_compose': 'Docker Compose',
            'zfs_utilities': 'ZFS Utilities',
            'zfs_pools': 'ZFS Pools',
            'host_resources': 'Host Resources',
            'network_ports': 'Network Ports'
        }
        
        for key, name in component_mapping.items():
            component_data = self.validation_report.get(key, {})
            components[name] = {
                'status': component_data.get('status', 'unknown'),
                'message': component_data.get('message', 'No information available')
            }
        
        return components
    
    def __str__(self):
        return f"{self.name} ({self.ip_address})"


class Database(models.Model):
    name = models.CharField(max_length=100)
    host_vm = models.ForeignKey(HostVM, on_delete=models.CASCADE)
    db_type = models.CharField(max_length=50, default='postgresql')
    db_version = models.CharField(max_length=20, default='15')
    container_name = models.CharField(max_length=100, unique=True)
    zfs_dataset = models.CharField(max_length=200)
    port = models.IntegerField()
    username = models.CharField(max_length=50, default='postgres')
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} on {self.host_vm.name}"


class DatabaseBranch(models.Model):
    database = models.ForeignKey(Database, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    snapshot_name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['database', 'name']
    
    def __str__(self):
        return f"{self.database.name}:{self.name}"


# Storage Configuration Models
class StorageConfiguration(models.Model):
    """Storage configuration for database hosting"""
    
    STORAGE_TYPES = [
        ('existing_pool', 'Use Existing ZFS Pool'),
        ('dedicated_disk', 'Dedicate Disk for ZFS Pool'),
        ('image_file', 'Create ZFS Pool from Image File'),
        ('directory', 'Directory-based Storage (Development)'),
        ('multi_disk', 'Multi-disk ZFS Pool'),
        ('hybrid', 'Hybrid Storage (SSD Cache + HDD Data)')
    ]
    
    POOL_TYPES = [
        ('single', 'Single Disk'),
        ('mirror', 'Mirror (RAID 1)'),
        ('raidz1', 'RAID-Z1 (Single Parity)'),
        ('raidz2', 'RAID-Z2 (Double Parity)'),
        ('raidz3', 'RAID-Z3 (Triple Parity)')
    ]
    
    name = models.CharField(max_length=100, unique=True)
    storage_type = models.CharField(max_length=20, choices=STORAGE_TYPES)
    pool_type = models.CharField(max_length=10, choices=POOL_TYPES, default='single')
    
    # Existing pool configuration
    existing_pool_name = models.CharField(max_length=100, blank=True)
    
    # Dedicated disk configuration
    dedicated_disks = models.JSONField(default=list, blank=True)  # List of disk paths
    
    # Image file configuration
    image_file_path = models.CharField(max_length=500, blank=True)
    image_file_size_gb = models.IntegerField(null=True, blank=True)
    sparse_file = models.BooleanField(default=True)
    
    # Directory-based configuration
    storage_directory = models.CharField(max_length=500, blank=True)
    
    # Hybrid storage configuration
    cache_disks = models.JSONField(default=list, blank=True)  # SSD cache disks
    data_disks = models.JSONField(default=list, blank=True)   # HDD data disks
    
    # Pool configuration
    pool_name = models.CharField(max_length=100, blank=True)
    compression = models.CharField(max_length=20, default='lz4')
    dedup = models.BooleanField(default=False)
    
    # Status
    is_configured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    configuration_error = models.TextField(blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.get_storage_type_display()})"
    
    def clean(self):
        """Validate configuration based on storage type"""
        from django.core.exceptions import ValidationError
        
        if self.storage_type == 'existing_pool' and not self.existing_pool_name:
            raise ValidationError("Existing pool name is required for existing pool storage")
        
        if self.storage_type == 'dedicated_disk' and not self.dedicated_disks:
            raise ValidationError("At least one disk is required for dedicated disk storage")
        
        if self.storage_type == 'image_file':
            if not self.image_file_path:
                raise ValidationError("Image file path is required")
            if not self.image_file_size_gb or self.image_file_size_gb < 1:
                raise ValidationError("Image file size must be at least 1GB")
        
        if self.storage_type == 'directory' and not self.storage_directory:
            raise ValidationError("Storage directory is required for directory-based storage")
        
        if self.storage_type == 'multi_disk' and len(self.dedicated_disks) < 2:
            raise ValidationError("Multi-disk configuration requires at least 2 disks")
        
        if self.storage_type == 'hybrid':
            if not self.cache_disks or not self.data_disks:
                raise ValidationError("Hybrid storage requires both cache and data disks")
    
    def get_required_space_gb(self):
        """Calculate required space for this configuration"""
        if self.storage_type == 'image_file':
            return self.image_file_size_gb or 0
        elif self.storage_type == 'directory':
            return 20  # Minimum recommended
        return 0
    
    def get_pool_name(self):
        """Get the pool name that will be used"""
        if self.storage_type == 'existing_pool':
            return self.existing_pool_name
        return self.pool_name or f"stagdb_{self.name.lower().replace(' ', '_')}"
    
    def validate_configuration(self):
        """Validate that this configuration can be applied"""
        from .storage_utils import StorageUtils
        
        storage_utils = StorageUtils()
        
        if self.storage_type == 'existing_pool':
            return storage_utils.validate_existing_pool(self.existing_pool_name)
        
        elif self.storage_type == 'dedicated_disk':
            return storage_utils.validate_dedicated_disks(self.dedicated_disks)
        
        elif self.storage_type == 'image_file':
            return storage_utils.validate_image_file_config(
                self.image_file_path, 
                self.image_file_size_gb
            )
        
        elif self.storage_type == 'directory':
            return storage_utils.validate_directory_storage(self.storage_directory)
        
        elif self.storage_type == 'multi_disk':
            return storage_utils.validate_multi_disk_config(
                self.dedicated_disks, 
                self.pool_type
            )
        
        elif self.storage_type == 'hybrid':
            return storage_utils.validate_hybrid_config(
                self.cache_disks, 
                self.data_disks, 
                self.pool_type
            )
        
        return {'valid': False, 'message': 'Unknown storage type'}
    
    def apply_configuration(self):
        """Apply this storage configuration"""
        from .storage_utils import StorageUtils
        
        storage_utils = StorageUtils()
        
        try:
            if self.storage_type == 'existing_pool':
                result = storage_utils.setup_existing_pool(self.existing_pool_name)
            
            elif self.storage_type == 'dedicated_disk':
                result = storage_utils.create_dedicated_disk_pool(
                    self.get_pool_name(),
                    self.dedicated_disks,
                    self.pool_type,
                    compression=self.compression,
                    dedup=self.dedup
                )
            
            elif self.storage_type == 'image_file':
                result = storage_utils.create_image_file_pool(
                    self.get_pool_name(),
                    self.image_file_path,
                    self.image_file_size_gb,
                    sparse=self.sparse_file,
                    compression=self.compression,
                    dedup=self.dedup
                )
            
            elif self.storage_type == 'directory':
                result = storage_utils.setup_directory_storage(self.storage_directory)
            
            elif self.storage_type == 'multi_disk':
                result = storage_utils.create_multi_disk_pool(
                    self.get_pool_name(),
                    self.dedicated_disks,
                    self.pool_type,
                    compression=self.compression,
                    dedup=self.dedup
                )
            
            elif self.storage_type == 'hybrid':
                result = storage_utils.create_hybrid_pool(
                    self.get_pool_name(),
                    self.cache_disks,
                    self.data_disks,
                    self.pool_type,
                    compression=self.compression,
                    dedup=self.dedup
                )
            
            else:
                result = {'success': False, 'message': 'Unknown storage type'}
            
            if result.get('success'):
                self.is_configured = True
                self.configuration_error = ''
                self.pool_name = result.get('pool_name', self.pool_name)
            else:
                self.is_configured = False
                self.configuration_error = result.get('message', 'Configuration failed')
            
            self.save()
            return result
            
        except Exception as e:
            self.is_configured = False
            self.configuration_error = str(e)
            self.save()
            return {'success': False, 'message': str(e)}
    
    def get_storage_info(self):
        """Get detailed storage information"""
        info = {
            'name': self.name,
            'type': self.get_storage_type_display(),
            'pool_name': self.get_pool_name(),
            'is_configured': self.is_configured,
            'configuration_error': self.configuration_error
        }
        
        if self.storage_type == 'existing_pool':
            info['existing_pool'] = self.existing_pool_name
        
        elif self.storage_type in ['dedicated_disk', 'multi_disk']:
            info['disks'] = self.dedicated_disks
            info['pool_type'] = self.get_pool_type_display()
        
        elif self.storage_type == 'image_file':
            info['image_path'] = self.image_file_path
            info['size_gb'] = self.image_file_size_gb
            info['sparse'] = self.sparse_file
        
        elif self.storage_type == 'directory':
            info['directory'] = self.storage_directory
        
        elif self.storage_type == 'hybrid':
            info['cache_disks'] = self.cache_disks
            info['data_disks'] = self.data_disks
            info['pool_type'] = self.get_pool_type_display()
        
        return info


class StorageQuota(models.Model):
    """Storage quotas for database datasets"""
    
    storage_config = models.ForeignKey(StorageConfiguration, on_delete=models.CASCADE)
    dataset_name = models.CharField(max_length=200)
    quota_gb = models.IntegerField()
    used_gb = models.FloatField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['storage_config', 'dataset_name']
    
    def __str__(self):
        return f"{self.dataset_name}: {self.used_gb}GB / {self.quota_gb}GB"
    
    def is_quota_exceeded(self):
        return self.used_gb >= self.quota_gb
    
    def get_usage_percentage(self):
        if self.quota_gb == 0:
            return 0
        return (self.used_gb / self.quota_gb) * 100


