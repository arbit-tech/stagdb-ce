import secrets
import string
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from django.utils import timezone
from .models import HostVM, Database, DatabaseBranch
from .container_utils import ContainerUtils
from .zfs_dataset import ZFSDatasetManager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages PostgreSQL database containers with ZFS storage"""
    
    # Supported PostgreSQL versions
    SUPPORTED_VERSIONS = ['11', '12', '13', '14', '15', '16']
    DEFAULT_VERSION = '15'
    
    # Port range for database allocation
    PORT_RANGE_START = 5432
    PORT_RANGE_END = 5500
    
    def __init__(self, host_vm: HostVM):
        if not host_vm.can_create_databases():
            raise ValueError(f"Host {host_vm.name} cannot create databases. Status: {host_vm.validation_status}")
        
        self.host_vm = host_vm
        self.container_utils = ContainerUtils(host_vm)
        self.zfs_manager = ZFSDatasetManager(host_vm)
        
    def create_database(self, name: str, pg_version: str = None, 
                       description: str = '', **kwargs) -> Dict:
        """
        Create new PostgreSQL database with ZFS backing
        
        Args:
            name: Database name (3-63 chars, alphanumeric + underscore)
            pg_version: PostgreSQL version (defaults to 15)
            description: Optional description
            
        Returns:
            Dict with creation result and connection info
        """
        try:
            # 1. Validate and sanitize inputs
            validation_result = self._validate_creation_inputs(name, pg_version)
            if not validation_result['valid']:
                return {'success': False, 'message': validation_result['message']}
            
            pg_version = validation_result['pg_version']
            sanitized_name = validation_result['sanitized_name']
            
            logger.info(f"Creating database '{name}' on host {self.host_vm.name}")
            
            # 2. Allocate resources
            allocated_port = self._allocate_port()
            if not allocated_port:
                return {'success': False, 'message': 'No available ports in range 5432-5500'}
            
            password = self._generate_secure_password()
            container_name = f"stagdb_db_{sanitized_name}"
            
            # 3. Create ZFS dataset
            dataset_result = self.zfs_manager.create_database_dataset(
                self.host_vm.storage_config.get_pool_name(), 
                sanitized_name
            )
            if not dataset_result['success']:
                return {
                    'success': False, 
                    'message': f"Failed to create storage dataset: {dataset_result['message']}"
                }
            
            dataset_path = dataset_result['dataset_path']
            mount_path = dataset_result['mount_path']
            
            # 4. Deploy PostgreSQL container
            container_config = {
                'name': container_name,
                'image': f'postgres:{pg_version}-alpine',
                'port': allocated_port,
                'volume_mount': mount_path,
                'environment': {
                    'POSTGRES_DB': sanitized_name,
                    'POSTGRES_USER': 'postgres',
                    'POSTGRES_PASSWORD': password,
                    'POSTGRES_INITDB_ARGS': '--data-checksums'
                }
            }
            
            container_result = self.container_utils.create_postgres_container(container_config)
            if not container_result['success']:
                # Cleanup ZFS dataset on container failure
                self.zfs_manager.destroy_database_dataset(dataset_path)
                return {
                    'success': False,
                    'message': f"Failed to create container: {container_result['message']}"
                }
            
            container_id = container_result['container_id']
            
            # 5. Wait for database to be ready and initialize
            init_result = self._initialize_database(container_name, timeout=60)
            if not init_result['success']:
                # Cleanup on initialization failure
                self.container_utils.remove_container(container_name)
                self.zfs_manager.destroy_database_dataset(dataset_path)
                return {
                    'success': False,
                    'message': f"Database initialization failed: {init_result['message']}"
                }
            
            # 6. Create Database record
            database = Database.objects.create(
                name=name,
                host_vm=self.host_vm,
                db_type='postgresql',
                db_version=pg_version,
                container_name=container_name,
                container_id=container_id,
                zfs_dataset=dataset_path,
                port=allocated_port,
                username='postgres',
                password=password,
                database_name=sanitized_name,
                description=description,
                container_status='running',
                health_status='healthy'
            )
            
            # 7. Create initial snapshot (root branch)
            snapshot_result = self._create_root_snapshot(database)
            if snapshot_result['success']:
                # Create main branch record
                DatabaseBranch.objects.create(
                    database=database,
                    name='main',
                    snapshot_name='root',
                    is_active=True
                )
            
            # 8. Return success with connection info
            connection_info = database.get_connection_info()
            
            logger.info(f"Database '{name}' created successfully with ID {database.id}")
            
            return {
                'success': True,
                'message': f'Database "{name}" created successfully',
                'database': {
                    'id': database.id,
                    'name': database.name,
                    'version': database.db_version,
                    'status': database.container_status,
                    'health': database.health_status,
                    'port': database.port,
                    'connection_info': connection_info,
                    'created_at': database.created_at.isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Database creation failed for '{name}': {str(e)}")
            return {
                'success': False,
                'message': f'Database creation failed: {str(e)}'
            }
    
    def delete_database(self, database: Database) -> Dict:
        """
        Remove database and clean up all resources
        
        Args:
            database: Database instance to delete
            
        Returns:
            Dict with deletion result
        """
        try:
            logger.info(f"Deleting database '{database.name}' (ID: {database.id})")
            
            cleanup_errors = []
            
            # 1. Stop and remove container
            if database.container_name:
                container_result = self.container_utils.remove_container(database.container_name)
                if not container_result:
                    cleanup_errors.append(f"Failed to remove container {database.container_name}")
            
            # 2. Destroy ZFS dataset and all snapshots
            if database.zfs_dataset:
                dataset_result = self.zfs_manager.destroy_database_dataset(database.zfs_dataset)
                if not dataset_result['success']:
                    cleanup_errors.append(f"Failed to destroy dataset: {dataset_result['message']}")
            
            # 3. Delete database branches
            DatabaseBranch.objects.filter(database=database).delete()
            
            # 4. Delete database record
            database_name = database.name
            database.delete()
            
            if cleanup_errors:
                logger.warning(f"Database '{database_name}' deleted with cleanup warnings: {cleanup_errors}")
                return {
                    'success': True,
                    'message': f'Database "{database_name}" deleted with warnings',
                    'warnings': cleanup_errors
                }
            
            logger.info(f"Database '{database_name}' deleted successfully")
            return {
                'success': True,
                'message': f'Database "{database_name}" deleted successfully'
            }
            
        except Exception as e:
            logger.error(f"Database deletion failed: {str(e)}")
            return {
                'success': False,
                'message': f'Database deletion failed: {str(e)}'
            }
    
    def start_database(self, database: Database) -> Dict:
        """Start stopped database container"""
        if database.container_status == 'running':
            return {'success': True, 'message': 'Database is already running'}
        
        result = self.container_utils.start_container(database.container_name)
        if result:
            database.container_status = 'running'
            database.save()
            return {'success': True, 'message': f'Database "{database.name}" started successfully'}
        
        return {'success': False, 'message': f'Failed to start database "{database.name}"'}
    
    def stop_database(self, database: Database) -> Dict:
        """Stop running database container"""
        if database.container_status == 'stopped':
            return {'success': True, 'message': 'Database is already stopped'}
        
        result = self.container_utils.stop_container(database.container_name)
        if result:
            database.container_status = 'stopped'
            database.save()
            return {'success': True, 'message': f'Database "{database.name}" stopped successfully'}
        
        return {'success': False, 'message': f'Failed to stop database "{database.name}"'}
    
    def restart_database(self, database: Database) -> Dict:
        """Restart database container"""
        # Stop first
        stop_result = self.stop_database(database)
        if not stop_result['success']:
            return stop_result
        
        # Wait a moment for graceful shutdown
        import time
        time.sleep(2)
        
        # Start again
        return self.start_database(database)
    
    def get_database_status(self, database: Database) -> Dict:
        """Get comprehensive database status"""
        container_status = self.container_utils.get_container_status(database.container_name)
        
        status_data = {
            'database_id': database.id,
            'name': database.name,
            'container_status': container_status.get('status', 'unknown'),
            'health_status': database.health_status,
            'uptime': container_status.get('uptime'),
            'port': database.port,
            'version': database.db_version,
            'last_updated': timezone.now().isoformat()
        }
        
        # Update database record if status changed
        new_status = container_status.get('status', 'unknown')
        if database.container_status != new_status:
            database.container_status = new_status
            database.save()
        
        return status_data
    
    def get_connection_info(self, database: Database) -> Dict:
        """Get database connection parameters"""
        return database.get_connection_info()
    
    def validate_database_name(self, name: str) -> Tuple[bool, str]:
        """Validate database name meets requirements"""
        if not name:
            return False, "Database name is required"
        
        if len(name) < 3:
            return False, "Database name must be at least 3 characters"
        
        if len(name) > 63:
            return False, "Database name must be at most 63 characters"
        
        if not name.replace('_', '').isalnum():
            return False, "Database name can only contain letters, numbers, and underscores"
        
        if name.startswith('_') or name.endswith('_'):
            return False, "Database name cannot start or end with underscore"
        
        # Check if name already exists on this host
        if Database.objects.filter(host_vm=self.host_vm, name=name, is_active=True).exists():
            return False, f"Database '{name}' already exists on this host"
        
        return True, "Database name is valid"
    
    def _validate_creation_inputs(self, name: str, pg_version: str) -> Dict:
        """Validate and sanitize database creation inputs"""
        # Validate database name
        name_valid, name_message = self.validate_database_name(name)
        if not name_valid:
            return {'valid': False, 'message': name_message}
        
        # Validate PostgreSQL version
        if pg_version is None:
            pg_version = self.DEFAULT_VERSION
        elif pg_version not in self.SUPPORTED_VERSIONS:
            return {
                'valid': False, 
                'message': f"Unsupported PostgreSQL version '{pg_version}'. Supported: {', '.join(self.SUPPORTED_VERSIONS)}"
            }
        
        # Sanitize name for use as container/dataset name
        sanitized_name = name.lower()
        
        return {
            'valid': True,
            'pg_version': pg_version,
            'sanitized_name': sanitized_name
        }
    
    def _allocate_port(self) -> Optional[int]:
        """Find and allocate next available port in range"""
        try:
            logger.info(f"Allocating port in range {self.PORT_RANGE_START}-{self.PORT_RANGE_END}")
            
            # Get used ports from existing databases in our system
            db_used_ports = set(
                Database.objects.filter(host_vm=self.host_vm, is_active=True)
                .values_list('port', flat=True)
            )
            
            # Use the improved port finding method from container utils
            available_port = self.container_utils.find_available_port(
                self.PORT_RANGE_START, self.PORT_RANGE_END
            )
            
            if available_port:
                # Double-check it's not in our database records
                if available_port not in db_used_ports:
                    logger.info(f"Allocated port {available_port}")
                    return available_port
                else:
                    logger.warning(f"Port {available_port} is available on host but used in database records")
                    
            # Fallback: manually iterate through range
            logger.warning("Using fallback port allocation method")
            host_used_ports = self.container_utils.get_used_ports_in_range(
                self.PORT_RANGE_START, self.PORT_RANGE_END
            )
            all_used_ports = db_used_ports.union(set(host_used_ports))
            
            for port in range(self.PORT_RANGE_START, self.PORT_RANGE_END + 1):
                if port not in all_used_ports:
                    # Final verification by trying to bind
                    if self.container_utils.is_port_available(port):
                        logger.info(f"Fallback allocated port {port}")
                        return port
                        
            logger.error(f"No available ports in range {self.PORT_RANGE_START}-{self.PORT_RANGE_END}")
            return None
            
        except Exception as e:
            logger.error(f"Error in port allocation: {str(e)}")
            return None
    
    def _generate_secure_password(self, length: int = 32) -> str:
        """Generate cryptographically secure password"""
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    def _initialize_database(self, container_name: str, timeout: int = 60) -> Dict:
        """Wait for database to be ready and perform initialization"""
        import time
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            # Check if PostgreSQL is ready
            success, stdout, stderr = self.container_utils.execute_in_container(
                container_name, 
                "pg_isready -U postgres"
            )
            
            if success:
                logger.info(f"PostgreSQL ready in container {container_name}")
                return {'success': True, 'message': 'Database initialized successfully'}
            
            time.sleep(2)
        
        return {'success': False, 'message': f'Database initialization timed out after {timeout} seconds'}
    
    def _create_root_snapshot(self, database: Database) -> Dict:
        """Create initial snapshot (root branch)"""
        try:
            snapshot_name = f"{database.zfs_dataset}@root"
            result = self.zfs_manager.create_snapshot(database.zfs_dataset, 'root')
            
            if result['success']:
                logger.info(f"Created root snapshot for database '{database.name}': {snapshot_name}")
                return {'success': True, 'snapshot_name': snapshot_name}
            else:
                logger.warning(f"Failed to create root snapshot for database '{database.name}': {result['message']}")
                return result
                
        except Exception as e:
            logger.error(f"Error creating root snapshot for database '{database.name}': {str(e)}")
            return {'success': False, 'message': str(e)}
    
    @classmethod
    def get_supported_versions(cls) -> List[str]:
        """Get list of supported PostgreSQL versions"""
        return cls.SUPPORTED_VERSIONS.copy()
    
    @classmethod 
    def get_default_version(cls) -> str:
        """Get default PostgreSQL version"""
        return cls.DEFAULT_VERSION