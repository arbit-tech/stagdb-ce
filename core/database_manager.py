import secrets
import string
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from django.utils import timezone
from .models import HostVM, Database
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
                       description: str = '', creation_type: str = 'empty',
                       source_database_id: int = None, source_snapshot: str = None, **kwargs) -> Dict:
        """
        Create new PostgreSQL database with ZFS backing
        
        Args:
            name: Database name (3-63 chars, alphanumeric + underscore)
            pg_version: PostgreSQL version (defaults to 15)
            description: Optional description
            creation_type: How to create ('empty', 'clone', 'snapshot')
            source_database_id: Database ID to clone from (for 'clone' type)
            source_snapshot: Snapshot path to restore from (for 'snapshot' type)
            
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

            container_name = f"stagdb_db_{sanitized_name}"

            # Check if storage configuration exists
            if not self.host_vm.storage_config:
                return {
                    'success': False,
                    'message': 'Host does not have a storage configuration. Please configure storage for this host first.'
                }

            pool_name = self.host_vm.storage_config.get_pool_name()

            # 3. Create ZFS dataset based on creation type
            source_db = None
            password = None  # Will be set based on creation type

            if creation_type == 'clone' and source_database_id:
                try:
                    # Allow cloning from databases on any host (cross-host cloning)
                    source_db = Database.objects.get(id=source_database_id, is_active=True)
                except Database.DoesNotExist:
                    return {'success': False, 'message': f'Source database with ID {source_database_id} not found or inactive'}
                # Check if source database is on the same host
                if source_db.host_vm.id != self.host_vm.id:
                    return {'success': False, 'message': 'Cross-host cloning is not yet supported. Source database must be on the same host.'}

                # IMPORTANT: Use source database's password for clones
                # When cloning via ZFS, we copy the entire data directory including password hashes
                # PostgreSQL ignores POSTGRES_PASSWORD env var when data dir already exists
                password = source_db.password
                logger.info(f"Cloning database '{source_db.name}' - reusing source password")

                dataset_result = self.zfs_manager.create_dataset_from_clone(
                    source_db.zfs_dataset, sanitized_name, pool_name, database=None,
                    context={'creation_type': 'clone', 'source_database': source_db.name}
                )
            elif creation_type == 'snapshot' and source_snapshot:
                # TODO: For snapshot restoration, we should try to find the source database
                # and reuse its password, since we're copying the data directory
                # For now, generate a new password (may require manual password reset)
                password = self._generate_secure_password()
                logger.warning(f"Restoring from snapshot '{source_snapshot}' - new password generated. May need manual reset.")

                dataset_result = self.zfs_manager.create_dataset_from_snapshot(
                    source_snapshot, sanitized_name, pool_name, database=None,
                    context={'creation_type': 'snapshot', 'source_snapshot': source_snapshot}
                )
            else:
                # Default to empty dataset - generate new password
                creation_type = 'empty'
                password = self._generate_secure_password()

                dataset_result = self.zfs_manager.create_dataset_from_empty(
                    pool_name, sanitized_name, database=None,
                    context={'creation_type': 'empty'}
                )
            
            if not dataset_result['success']:
                return {
                    'success': False, 
                    'message': f"Failed to create storage dataset: {dataset_result['message']}"
                }
            
            dataset_path = dataset_result['dataset_path']
            mount_path = dataset_result['mount_path']

            # Ensure password was set
            if not password:
                logger.error("Password was not set for database creation")
                self.zfs_manager.destroy_database_dataset(dataset_path)
                return {
                    'success': False,
                    'message': 'Internal error: Password was not set during database creation'
                }

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

            # 5b. For clones, rename the database inside PostgreSQL to match the new name
            if creation_type == 'clone' and source_db:
                source_db_name = source_db.database_name
                if source_db_name != sanitized_name:
                    logger.info(f"Renaming cloned database from '{source_db_name}' to '{sanitized_name}'")
                    rename_result = self._rename_database_internal(
                        container_name, source_db_name, sanitized_name, password
                    )
                    if not rename_result['success']:
                        logger.error(f"Failed to rename database: {rename_result['message']}")
                        # Don't fail the entire operation, but log it
                        # The user can still connect using the source database name
                        logger.warning(f"Clone created but database name is '{source_db_name}' instead of '{sanitized_name}'")
                        # Update the database_name to reflect reality
                        sanitized_name = source_db_name
            
            # 6. Create Database record with lineage tracking
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
                health_status='healthy',
                # ZFS lineage tracking
                created_from_operation=dataset_result.get('operation') or dataset_result.get('clone_operation'),
                creation_type=creation_type,
                source_database=source_db,
                source_snapshot=source_snapshot or dataset_result.get('source_snapshot', '').split('@')[-1] if '@' in str(dataset_result.get('source_snapshot', '')) else ''
            )
            
            # 7. Update operation with database reference
            if hasattr(dataset_result.get('operation'), 'initiated_by_database'):
                operation = dataset_result.get('operation') or dataset_result.get('clone_operation')
                if operation:
                    operation.initiated_by_database = database
                    operation.save()
            
            # 8. Create initial snapshot for future branching
            self._create_root_snapshot(database)
            
            # 9. Return success with connection info
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
    
    def get_available_databases_for_cloning(self) -> Dict:
        """Get list of databases available for cloning on this host"""
        try:
            databases = Database.objects.filter(
                host_vm=self.host_vm, 
                is_active=True,
                container_status='running'
            ).values('id', 'name', 'db_type', 'db_version', 'created_at', 'description')
            
            return {
                'success': True,
                'databases': list(databases),
                'count': len(databases)
            }
        except Exception as e:
            logger.error(f"Error getting databases for cloning: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def get_available_snapshots_for_restore(self) -> Dict:
        """Get list of available snapshots for restore operations"""
        try:
            pool_name = self.host_vm.storage_config.get_pool_name()
            return self.zfs_manager.list_available_snapshots(pool_name)
        except Exception as e:
            logger.error(f"Error getting snapshots for restore: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def create_manual_snapshot(self, database: Database, snapshot_name: str) -> Dict:
        """Create a manual snapshot of a database for branching"""
        try:
            return self.zfs_manager.create_snapshot_with_tracking(
                database.zfs_dataset, 
                snapshot_name,
                database=database,
                context={'manual_snapshot': True, 'user_requested': True}
            )
        except Exception as e:
            logger.error(f"Error creating manual snapshot: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def delete_database(self, database: Database, force: bool = False) -> Dict:
        """
        Remove database and clean up all resources comprehensively
        
        Args:
            database: Database instance to delete
            force: If True, ignore dependency checks and force deletion
            
        Returns:
            Dict with deletion result and cleanup summary
        """
        try:
            logger.info(f"Deleting database '{database.name}' (ID: {database.id})")
            
            # 1. Check for dependent databases (clones)
            if not force:
                dependency_check = self._check_database_dependencies(database)
                if not dependency_check['can_delete']:
                    return {
                        'success': False,
                        'message': dependency_check['message'],
                        'dependencies': dependency_check.get('dependencies', [])
                    }
            
            cleanup_summary = {
                'container_cleanup': False,
                'dataset_cleanup': False,
                'snapshots_cleaned': [],
                'child_databases_handled': [],
                'errors': [],
                'warnings': []
            }
            
            # 2. Handle dependent databases if force deletion
            if force:
                dependent_cleanup = self._handle_dependent_databases(database)
                cleanup_summary['child_databases_handled'] = dependent_cleanup['handled']
                cleanup_summary['warnings'].extend(dependent_cleanup['warnings'])
            
            # 3. Stop and remove container with enhanced cleanup
            if database.container_name:
                container_result = self._comprehensive_container_cleanup(database.container_name)
                cleanup_summary['container_cleanup'] = container_result['success']
                if not container_result['success']:
                    cleanup_summary['errors'].append(f"Container cleanup: {container_result['message']}")
                cleanup_summary['warnings'].extend(container_result.get('warnings', []))
            
            # 4. Comprehensive ZFS cleanup
            if database.zfs_dataset:
                zfs_cleanup_result = self._comprehensive_zfs_cleanup(database)
                cleanup_summary['dataset_cleanup'] = zfs_cleanup_result['success']
                cleanup_summary['snapshots_cleaned'] = zfs_cleanup_result.get('snapshots_cleaned', [])
                if not zfs_cleanup_result['success']:
                    cleanup_summary['errors'].append(f"ZFS cleanup: {zfs_cleanup_result['message']}")
                cleanup_summary['warnings'].extend(zfs_cleanup_result.get('warnings', []))
            
            # 5. Clean up ZFS operations records
            operations_cleanup = self._cleanup_zfs_operations(database)
            if operations_cleanup['cleaned_count'] > 0:
                cleanup_summary['warnings'].append(f"Cleaned {operations_cleanup['cleaned_count']} ZFS operation records")
            
            # 6. Delete database record
            database_name = database.name
            database.delete()
            
            # 7. Generate comprehensive result
            has_errors = len(cleanup_summary['errors']) > 0
            has_warnings = len(cleanup_summary['warnings']) > 0
            
            if has_errors:
                return {
                    'success': False,
                    'message': f'Database "{database_name}" deletion failed with errors',
                    'cleanup_summary': cleanup_summary
                }
            elif has_warnings:
                return {
                    'success': True,
                    'message': f'Database "{database_name}" deleted with warnings',
                    'cleanup_summary': cleanup_summary
                }
            else:
                return {
                    'success': True,
                    'message': f'Database "{database_name}" deleted successfully',
                    'cleanup_summary': cleanup_summary
                }
            
        except Exception as e:
            logger.error(f"Database deletion failed: {str(e)}")
            return {
                'success': False,
                'message': f'Database deletion failed: {str(e)}',
                'cleanup_summary': {'errors': [str(e)]}
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
        """Generate cryptographically secure password using only alphanumeric characters"""
        # Use only alphanumeric characters to avoid shell escaping and connection string issues
        alphabet = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
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

    def _rename_database_internal(self, container_name: str, old_name: str, new_name: str, password: str) -> Dict:
        """Rename a database inside PostgreSQL after cloning"""
        try:
            logger.info(f"Renaming database from '{old_name}' to '{new_name}' in container {container_name}")

            # Step 1: Terminate all connections to the old database
            terminate_sql = f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{old_name}' AND pid <> pg_backend_pid();"
            success, stdout, stderr = self.container_utils.execute_in_container(
                container_name,
                f"psql -U postgres -d postgres -c \"{terminate_sql}\""
            )
            if not success:
                logger.warning(f"Could not terminate connections: {stderr}")

            # Step 2: Rename the database
            rename_sql = f"ALTER DATABASE {old_name} RENAME TO {new_name};"
            success, stdout, stderr = self.container_utils.execute_in_container(
                container_name,
                f"psql -U postgres -d postgres -c \"{rename_sql}\""
            )

            if success or 'ALTER DATABASE' in stdout:
                logger.info(f"Successfully renamed database from '{old_name}' to '{new_name}'")
                return {'success': True, 'message': f'Database renamed to {new_name}'}
            else:
                logger.error(f"Failed to rename database: {stderr}")
                return {'success': False, 'message': f'Rename failed: {stderr}'}

        except Exception as e:
            logger.error(f"Error renaming database: {str(e)}")
            return {'success': False, 'message': f'Error: {str(e)}'}

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
    
    def _check_database_dependencies(self, database: Database) -> Dict:
        """Check if database has dependent databases (clones)"""
        try:
            # Check for databases that were cloned from this one
            dependent_databases = Database.objects.filter(
                source_database=database,
                is_active=True
            )
            
            if dependent_databases.exists():
                dependency_list = [
                    {
                        'id': db.id,
                        'name': db.name,
                        'creation_type': db.creation_type,
                        'created_at': db.created_at.isoformat()
                    }
                    for db in dependent_databases
                ]
                
                return {
                    'can_delete': False,
                    'message': f'Cannot delete database "{database.name}". {len(dependent_databases)} databases were cloned from it.',
                    'dependencies': dependency_list
                }
            
            return {
                'can_delete': True,
                'message': 'No dependencies found'
            }
            
        except Exception as e:
            logger.error(f"Error checking database dependencies: {str(e)}")
            return {
                'can_delete': False,
                'message': f'Error checking dependencies: {str(e)}'
            }
    
    def _handle_dependent_databases(self, database: Database) -> Dict:
        """Handle dependent databases when force deleting"""
        try:
            dependent_databases = Database.objects.filter(
                source_database=database,
                is_active=True
            )
            
            handled = []
            warnings = []
            
            for dependent_db in dependent_databases:
                # Update source reference to None to orphan the dependent database
                dependent_db.source_database = None
                dependent_db.save()
                
                handled.append({
                    'id': dependent_db.id,
                    'name': dependent_db.name,
                    'action': 'orphaned'
                })
                
                warnings.append(f"Orphaned dependent database '{dependent_db.name}' (ID: {dependent_db.id})")
            
            return {
                'handled': handled,
                'warnings': warnings
            }
            
        except Exception as e:
            logger.error(f"Error handling dependent databases: {str(e)}")
            return {
                'handled': [],
                'warnings': [f"Error handling dependencies: {str(e)}"]
            }
    
    def _comprehensive_container_cleanup(self, container_name: str) -> Dict:
        """Comprehensive container cleanup with detailed reporting"""
        try:
            warnings = []
            
            # Get container status first
            status = self.container_utils.get_container_status(container_name)
            
            if status['status'] == 'missing':
                return {
                    'success': True,
                    'message': 'Container already removed',
                    'warnings': ['Container was already missing']
                }
            
            # Stop container gracefully first
            if status['status'] == 'running':
                logger.info(f"Stopping container {container_name}")
                stop_success = self.container_utils.stop_container(container_name)
                if not stop_success:
                    warnings.append('Failed to gracefully stop container')
                    
                    # Force kill if graceful stop failed
                    logger.warning(f"Force killing container {container_name}")
                    kill_cmd = f"docker kill {container_name}"
                    kill_success, _, kill_stderr = self.container_utils.host_system.execute_command(kill_cmd)
                    if not kill_success:
                        warnings.append(f'Force kill also failed: {kill_stderr}')
            
            # Remove container
            logger.info(f"Removing container {container_name}")
            remove_success = self.container_utils.remove_container(container_name)
            
            if remove_success:
                return {
                    'success': True,
                    'message': 'Container removed successfully',
                    'warnings': warnings
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to remove container',
                    'warnings': warnings
                }
                
        except Exception as e:
            logger.error(f"Error in container cleanup: {str(e)}")
            return {
                'success': False,
                'message': f'Container cleanup error: {str(e)}'
            }
    
    def _comprehensive_zfs_cleanup(self, database: Database) -> Dict:
        """Comprehensive ZFS cleanup including orphaned snapshots"""
        try:
            warnings = []
            snapshots_cleaned = []
            
            # 1. Get all snapshots related to this dataset before destruction
            snapshot_info = self.zfs_manager.get_snapshot_hierarchy(database.zfs_dataset)
            if snapshot_info.get('success'):
                related_snapshots = snapshot_info.get('snapshots', [])
                for snapshot in related_snapshots:
                    if snapshot.get('type') == 'current_dataset':
                        snapshots_cleaned.append(snapshot['full_name'])
            
            # 2. Check for snapshots that might be used by other databases
            protected_snapshots = self._find_protected_snapshots(database)
            if protected_snapshots:
                warnings.append(f"Found {len(protected_snapshots)} snapshots in use by other databases")
            
            # 3. Destroy the dataset (this will destroy all its snapshots)
            logger.info(f"Destroying ZFS dataset: {database.zfs_dataset}")
            dataset_result = self.zfs_manager.destroy_database_dataset(database.zfs_dataset)
            
            if not dataset_result['success']:
                return {
                    'success': False,
                    'message': dataset_result['message'],
                    'snapshots_cleaned': snapshots_cleaned,
                    'warnings': warnings
                }
            
            # 4. Clean up any orphaned snapshots that might reference this dataset
            orphan_cleanup = self._cleanup_orphaned_snapshots(database)
            if orphan_cleanup['cleaned_count'] > 0:
                warnings.append(f"Cleaned {orphan_cleanup['cleaned_count']} orphaned snapshots")
                snapshots_cleaned.extend(orphan_cleanup['snapshots'])
            
            return {
                'success': True,
                'message': 'ZFS dataset destroyed successfully',
                'snapshots_cleaned': snapshots_cleaned,
                'warnings': warnings
            }
            
        except Exception as e:
            logger.error(f"Error in ZFS cleanup: {str(e)}")
            return {
                'success': False,
                'message': f'ZFS cleanup error: {str(e)}'
            }
    
    def _find_protected_snapshots(self, database: Database) -> List[str]:
        """Find snapshots that are still in use by other databases"""
        try:
            from .models import Database as DatabaseModel
            
            # Find databases that might be using snapshots from this dataset
            databases_using_snapshots = DatabaseModel.objects.filter(
                creation_type='snapshot',
                source_snapshot__contains=database.zfs_dataset.split('/')[-1],  # database name
                is_active=True
            ).exclude(id=database.id)
            
            protected = []
            for db in databases_using_snapshots:
                if db.source_snapshot:
                    protected.append(db.source_snapshot)
            
            return protected
            
        except Exception as e:
            logger.error(f"Error finding protected snapshots: {str(e)}")
            return []
    
    def _cleanup_orphaned_snapshots(self, database: Database) -> Dict:
        """Clean up snapshots that are no longer needed"""
        try:
            # For now, we rely on ZFS dataset destruction to handle snapshot cleanup
            # This is a placeholder for more sophisticated orphan detection
            return {
                'cleaned_count': 0,
                'snapshots': []
            }
            
        except Exception as e:
            logger.error(f"Error cleaning orphaned snapshots: {str(e)}")
            return {
                'cleaned_count': 0,
                'snapshots': []
            }
    
    def _cleanup_zfs_operations(self, database: Database) -> Dict:
        """Clean up ZFS operation records for deleted database"""
        try:
            from .models import ZFSOperation
            
            # Find operations related to this database
            related_operations = ZFSOperation.objects.filter(
                initiated_by_database=database
            )
            
            cleaned_count = related_operations.count()
            
            # Delete the operation records
            related_operations.delete()
            
            logger.info(f"Cleaned {cleaned_count} ZFS operation records for database {database.name}")
            
            return {
                'cleaned_count': cleaned_count
            }
            
        except Exception as e:
            logger.error(f"Error cleaning ZFS operations: {str(e)}")
            return {
                'cleaned_count': 0
            }