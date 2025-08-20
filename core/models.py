from django.db import models
from django.db.models import Q
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
        # Look for existing Docker host first (active or inactive)
        docker_host = cls.objects.filter(is_docker_host=True).first()
        if docker_host:
            # Ensure it's properly configured and active
            needs_update = False
            if not docker_host.is_active:
                docker_host.is_active = True
                needs_update = True
            if docker_host.ip_address != '172.17.0.1':
                docker_host.ip_address = '172.17.0.1'
                needs_update = True
            if docker_host.username != 'docker-host':
                docker_host.username = 'docker-host'
                needs_update = True
            
            if needs_update:
                docker_host.save()
            
            return docker_host, False
        
        # Look for existing host by name that could be converted to Docker host
        try:
            docker_host = cls.objects.get(name='docker-host')
            # Convert existing host to Docker host
            docker_host.is_docker_host = True
            docker_host.is_active = True
            docker_host.ip_address = '172.17.0.1'
            docker_host.username = 'docker-host'
            docker_host.save()
            return docker_host, False
        except cls.DoesNotExist:
            pass
        
        # Create new Docker host
        docker_host = cls.objects.create(
            name='docker-host',
            ip_address='172.17.0.1',
            username='docker-host',
            is_active=True,
            is_docker_host=True,
            zfs_pool=''
        )
        
        return docker_host, True
    
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
            
            # Set pool based on storage configuration if available
            if self.storage_config and self.storage_config.is_configured:
                expected_pool_name = self.storage_config.get_pool_name()
                # Verify the expected pool exists and is healthy
                available_pools = {p['name']: p for p in pools_info['pools']}
                if expected_pool_name in available_pools and available_pools[expected_pool_name].get('health') == 'ONLINE':
                    self.zfs_pool = expected_pool_name
                else:
                    # Log a warning but don't override - might be a temporary state
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Expected pool '{expected_pool_name}' not found or unhealthy. Available pools: {list(available_pools.keys())}")
            else:
                # Fall back to auto-selecting the first healthy pool if no storage config
                healthy_pools = [p for p in pools_info['pools'] if p.get('health') == 'ONLINE']
                if healthy_pools and not self.zfs_pool:
                    self.zfs_pool = healthy_pools[0]['name']
        
        self.save()
        
        # If validation passed and we have a ZFS pool, ensure parent datasets exist
        if validation_results.get('overall_status') == 'valid' and self.storage_config:
            try:
                self._ensure_stagdb_parent_datasets()
            except Exception as e:
                logger.warning(f"Failed to create parent datasets on host {self.name}: {str(e)}")
        
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
    
    def cleanup_storage_configuration(self):
        """Clean up storage configuration resources for this host"""
        if not self.storage_config or not self.storage_config.is_configured:
            return {
                'success': True,
                'message': 'No storage configuration to clean up',
                'storage_config': None
            }
        
        from .storage_utils import StorageUtils
        storage_utils = StorageUtils()
        cleanup_result = storage_utils.cleanup_storage_configuration(self.storage_config)
        
        # Mark storage config as inactive after cleanup attempt
        if cleanup_result['success']:
            self.storage_config.is_active = False
            self.storage_config.save()
        
        return cleanup_result
    
    def _ensure_stagdb_parent_datasets(self):
        """Ensure StagDB parent datasets exist for this host"""
        if not self.storage_config or not self.storage_config.is_configured:
            return
            
        from .zfs_dataset import ZFSDatasetManager
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            zfs_manager = ZFSDatasetManager(self)
            pool_name = self.storage_config.get_pool_name()
            
            logger.info(f"Ensuring parent datasets exist for pool {pool_name}")
            result = zfs_manager._ensure_parent_datasets(pool_name)
            
            if result['success']:
                logger.info(f"Parent datasets ready for host {self.name}")
            else:
                logger.error(f"Failed to create parent datasets: {result['message']}")
                
        except Exception as e:
            logger.error(f"Error ensuring parent datasets for host {self.name}: {str(e)}")
            raise
    
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
    # Core database info
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
    
    # Container management fields
    container_id = models.CharField(max_length=64, blank=True)  # Docker container ID
    container_status = models.CharField(max_length=20, choices=[
        ('creating', 'Creating'),
        ('running', 'Running'),
        ('stopped', 'Stopped'),
        ('error', 'Error'),
        ('removing', 'Removing')
    ], default='creating')
    
    # Health monitoring
    last_health_check = models.DateTimeField(null=True, blank=True)
    health_status = models.CharField(max_length=20, choices=[
        ('healthy', 'Healthy'),
        ('unhealthy', 'Unhealthy'),
        ('starting', 'Starting'),
        ('unknown', 'Unknown')
    ], default='unknown')
    
    # Storage info
    storage_used_mb = models.IntegerField(default=0)
    storage_quota_gb = models.IntegerField(null=True, blank=True)
    
    # Connection info
    database_name = models.CharField(max_length=100, default='')  # Actual DB name inside PostgreSQL
    connection_string = models.TextField(blank=True)  # Cached connection string
    
    # ZFS lineage tracking
    created_from_operation = models.ForeignKey('ZFSOperation', on_delete=models.SET_NULL, null=True, blank=True, 
                                               help_text="The ZFS operation that created this database's dataset")
    creation_type = models.CharField(max_length=20, choices=[
        ('empty', 'Empty Dataset'),
        ('clone', 'Cloned from Database'),
        ('snapshot', 'Restored from Snapshot'),
    ], default='empty')
    source_database = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                                        help_text="Source database if this was cloned")
    source_snapshot = models.CharField(max_length=200, blank=True,
                                       help_text="Source snapshot name if restored from snapshot")
    
    # Metadata
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} on {self.host_vm.name}"
    
    def get_connection_string(self, include_password=True):
        """Generate PostgreSQL connection string"""
        base = f"postgresql://{self.username}"
        if include_password:
            base += f":{self.password}"
        base += f"@{self.host_vm.ip_address}:{self.port}/{self.database_name}"
        return base
    
    def get_connection_info(self):
        """Get structured connection information"""
        return {
            'host': self.host_vm.ip_address,
            'port': self.port,
            'database': self.database_name,
            'username': self.username,
            'password': self.password,
            'connection_string': self.get_connection_string(),
            'connection_string_safe': self.get_connection_string(include_password=False)
        }
    
    def is_container_running(self):
        """Check if container is currently running"""
        return self.container_status == 'running' and self.health_status in ['healthy', 'starting']
    
    def get_storage_metrics(self):
        """Get ZFS dataset storage metrics"""
        from .zfs_dataset import ZFSDatasetManager
        
        try:
            zfs_manager = ZFSDatasetManager(self.host_vm)
            return zfs_manager.get_dataset_metrics(self.zfs_dataset)
        except Exception as e:
            return {
                'used': 'Unknown',
                'available': 'Unknown', 
                'referenced': 'Unknown',
                'error': str(e)
            }
    
    def get_snapshot_hierarchy(self):
        """Get ZFS snapshot hierarchy from root to current state"""
        from .zfs_dataset import ZFSDatasetManager
        
        try:
            zfs_manager = ZFSDatasetManager(self.host_vm)
            return zfs_manager.get_snapshot_hierarchy(self.zfs_dataset)
        except Exception as e:
            return {
                'snapshots': [],
                'error': str(e)
            }
    
    def get_zfs_lineage(self):
        """Get the complete ZFS lineage for this database"""
        lineage = []
        
        # Add creation operation
        if self.created_from_operation:
            lineage.append(self.created_from_operation.get_lineage_info())
        
        # Get all ZFS operations related to this database's dataset
        operations = ZFSOperation.objects.filter(
            Q(source_dataset=self.zfs_dataset) |
            Q(target_dataset=self.zfs_dataset) |
            Q(initiated_by_database=self)
        ).order_by('started_at')
        
        for op in operations:
            lineage.append(op.get_lineage_info())
        
        return lineage
    
    def get_creation_info(self):
        """Get information about how this database was created"""
        if self.creation_type == 'clone' and self.source_database:
            return {
                'type': 'Cloned from Database',
                'source': self.source_database.name,
                'details': f"Cloned from {self.source_database.name}"
            }
        elif self.creation_type == 'snapshot' and self.source_snapshot:
            return {
                'type': 'Restored from Snapshot',
                'source': self.source_snapshot,
                'details': f"Restored from snapshot {self.source_snapshot}"
            }
        else:
            return {
                'type': 'Empty Dataset',
                'source': None,
                'details': "Created as new empty database"
            }
    
    def get_child_databases(self):
        """Get databases that were cloned from this one"""
        return Database.objects.filter(source_database=self, is_active=True)


class ZFSOperation(models.Model):
    """Track all ZFS operations for audit trail and lineage"""
    
    OPERATION_TYPES = [
        ('create', 'Create Dataset'),
        ('snapshot', 'Create Snapshot'),
        ('clone', 'Clone from Snapshot'),
        ('destroy', 'Destroy Dataset/Snapshot'),
        ('rollback', 'Rollback to Snapshot'),
        ('rename', 'Rename Dataset/Snapshot'),
    ]
    
    # Operation details
    operation_type = models.CharField(max_length=20, choices=OPERATION_TYPES)
    source_dataset = models.CharField(max_length=500, blank=True)  # Source dataset/snapshot
    target_dataset = models.CharField(max_length=500, blank=True)  # Target dataset
    snapshot_name = models.CharField(max_length=200, blank=True)   # Snapshot name if applicable
    
    # Execution details
    command_executed = models.TextField()  # Actual ZFS command run
    success = models.BooleanField()
    stdout = models.TextField(blank=True)  # Command output
    stderr = models.TextField(blank=True)  # Error output
    
    # Context
    host_vm = models.ForeignKey(HostVM, on_delete=models.CASCADE)
    initiated_by_database = models.ForeignKey(Database, on_delete=models.SET_NULL, null=True, blank=True)
    operation_context = models.JSONField(default=dict, blank=True)  # Additional context (user actions, etc.)
    
    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    
    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['operation_type', 'success']),
            models.Index(fields=['source_dataset']),
            models.Index(fields=['target_dataset']),
            models.Index(fields=['host_vm', '-started_at']),
        ]
    
    def __str__(self):
        if self.operation_type == 'clone':
            return f"Clone {self.source_dataset} → {self.target_dataset}"
        elif self.operation_type == 'snapshot':
            return f"Snapshot {self.source_dataset}@{self.snapshot_name}"
        else:
            return f"{self.get_operation_type_display()}: {self.target_dataset or self.source_dataset}"
    
    def get_full_source_path(self):
        """Get full source path including snapshot if applicable"""
        if self.snapshot_name and self.source_dataset:
            return f"{self.source_dataset}@{self.snapshot_name}"
        return self.source_dataset
    
    def get_lineage_info(self):
        """Get information about this operation's place in dataset lineage"""
        return {
            'operation': self.get_operation_type_display(),
            'source': self.get_full_source_path(),
            'target': self.target_dataset,
            'timestamp': self.started_at,
            'success': self.success,
            'context': self.operation_context
        }


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
    
    # Storage Monitoring Fields
    health_status = models.CharField(
        max_length=20,
        choices=[
            ('healthy', 'Healthy'),
            ('degraded', 'Degraded'),
            ('failed', 'Failed'),
            ('missing', 'Missing'),
            ('unknown', 'Unknown')
        ],
        default='unknown'
    )
    health_details = models.JSONField(default=dict, blank=True)
    last_health_check = models.DateTimeField(null=True, blank=True)
    last_reconciliation = models.DateTimeField(null=True, blank=True)
    actual_pool_info = models.JSONField(default=dict, blank=True)
    sync_status = models.CharField(
        max_length=20,
        choices=[
            ('synced', 'Synced'),
            ('drift_detected', 'Drift Detected'),
            ('out_of_sync', 'Out of Sync'),
            ('unknown', 'Unknown')
        ],
        default='unknown'
    )
    
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
    
    def cleanup_resources(self):
        """Clean up all storage resources for this configuration"""
        from .storage_utils import StorageUtils
        storage_utils = StorageUtils()
        return storage_utils.cleanup_storage_configuration(self)


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


