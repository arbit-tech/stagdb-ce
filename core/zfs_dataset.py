import os
import logging
import time
from typing import Dict, Tuple, Optional
from django.utils import timezone
from .storage_utils import StorageUtils

logger = logging.getLogger(__name__)


class ZFSDatasetManager:
    """ZFS dataset operations for database storage"""
    
    def __init__(self, host_vm):
        self.host_vm = host_vm
        self.storage_utils = StorageUtils()
    
    def _track_zfs_operation(self, operation_type: str, command: str, source_dataset: str = '', 
                           target_dataset: str = '', snapshot_name: str = '', 
                           database=None, context: dict = None) -> 'ZFSOperation':
        """Create and track a ZFS operation"""
        from .models import ZFSOperation
        
        operation = ZFSOperation.objects.create(
            operation_type=operation_type,
            source_dataset=source_dataset,
            target_dataset=target_dataset,
            snapshot_name=snapshot_name,
            command_executed=command,
            success=False,  # Will be updated after execution
            host_vm=self.host_vm,
            initiated_by_database=database,
            operation_context=context or {}
        )
        return operation
    
    def _complete_zfs_operation(self, operation: 'ZFSOperation', success: bool, 
                              stdout: str = '', stderr: str = '', start_time: float = None):
        """Complete a ZFS operation with results"""
        operation.success = success
        operation.stdout = stdout
        operation.stderr = stderr
        operation.completed_at = timezone.now()
        
        if start_time:
            operation.duration_seconds = time.time() - start_time
        
        operation.save()
        return operation
    
    def _execute_with_tracking(self, operation_type: str, command: str, source_dataset: str = '',
                             target_dataset: str = '', snapshot_name: str = '', 
                             database=None, context: dict = None) -> Tuple['ZFSOperation', bool, str, str]:
        """Execute ZFS command with full operation tracking"""
        
        # Track the operation
        operation = self._track_zfs_operation(
            operation_type, command, source_dataset, target_dataset, 
            snapshot_name, database, context
        )
        
        # Execute the command
        start_time = time.time()
        success, stdout, stderr = self.storage_utils.execute_host_command(command)
        
        # Complete the operation
        self._complete_zfs_operation(operation, success, stdout, stderr, start_time)
        
        return operation, success, stdout, stderr
    
    def create_database_dataset(self, pool_name: str, database_name: str) -> Dict:
        """
        Create ZFS dataset for database storage
        
        Args:
            pool_name: ZFS pool name
            database_name: Database name (sanitized)
            
        Returns:
            Dict with success status, dataset_path, mount_path, and message
        """
        try:
            # Validate inputs
            if not pool_name or not database_name:
                return {'success': False, 'message': 'Pool name and database name are required'}
            
            # Validate dataset name
            valid, message = self.validate_dataset_name(database_name)
            if not valid:
                return {'success': False, 'message': message}
            
            # Construct dataset path: {pool_name}/stagdb/databases/{database_name}
            dataset_path = f"{pool_name}/stagdb/databases/{database_name}"
            mount_path = f"/stagdb/data/{database_name}"
            
            logger.info(f"Creating ZFS dataset: {dataset_path}")
            
            # Create parent datasets if they don't exist
            parent_creation = self._ensure_parent_datasets(pool_name)
            if not parent_creation['success']:
                return parent_creation
            
            # Create the database dataset with PostgreSQL-optimized settings
            create_cmd = (
                f"zfs create "
                f"-o compression=lz4 "
                f"-o recordsize=8K "
                f"-o mountpoint={mount_path} "
                f"{dataset_path}"
            )
            
            success, stdout, stderr = self.storage_utils.execute_host_command(create_cmd)
            
            if not success:
                logger.error(f"Failed to create ZFS dataset {dataset_path}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to create ZFS dataset: {stderr}'
                }
            
            # Set proper permissions for PostgreSQL container (UID 999, GID 999)
            permission_result = self._set_dataset_permissions(mount_path)
            if not permission_result['success']:
                # Try to cleanup the dataset if permission setting failed
                self._cleanup_failed_dataset(dataset_path)
                return permission_result
            
            logger.info(f"ZFS dataset created successfully: {dataset_path} -> {mount_path}")
            
            return {
                'success': True,
                'dataset_path': dataset_path,
                'mount_path': mount_path,
                'message': f'Dataset {dataset_path} created successfully'
            }
            
        except Exception as e:
            logger.error(f"Error creating ZFS dataset for {database_name}: {str(e)}")
            return {
                'success': False,
                'message': f'Dataset creation error: {str(e)}'
            }
    
    def destroy_database_dataset(self, dataset_path: str) -> Dict:
        """
        Destroy dataset and all snapshots/clones
        
        Args:
            dataset_path: Full ZFS dataset path
            
        Returns:
            Dict with success status and message
        """
        try:
            if not dataset_path:
                return {'success': False, 'message': 'Dataset path is required'}
            
            logger.info(f"Destroying ZFS dataset: {dataset_path}")
            
            # Destroy dataset with recursive flag to remove all snapshots and clones
            destroy_cmd = f"zfs destroy -r {dataset_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(destroy_cmd)
            
            if success:
                logger.info(f"ZFS dataset destroyed successfully: {dataset_path}")
                return {
                    'success': True,
                    'message': f'Dataset {dataset_path} destroyed successfully'
                }
            else:
                # Check if dataset doesn't exist (not an error in this context)
                if 'dataset does not exist' in stderr.lower():
                    logger.info(f"Dataset {dataset_path} already does not exist")
                    return {
                        'success': True,
                        'message': f'Dataset {dataset_path} was already removed'
                    }
                
                logger.error(f"Failed to destroy ZFS dataset {dataset_path}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to destroy dataset: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error destroying ZFS dataset {dataset_path}: {str(e)}")
            return {
                'success': False,
                'message': f'Dataset destruction error: {str(e)}'
            }
    
    def get_dataset_info(self, dataset_path: str) -> Dict:
        """Get dataset properties and usage"""
        try:
            info_cmd = f"zfs list -H -o name,used,avail,refer,mountpoint {dataset_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(info_cmd)
            
            if not success:
                return {'error': f'Failed to get dataset info: {stderr}'}
            
            parts = stdout.strip().split('\t')
            if len(parts) >= 5:
                return {
                    'name': parts[0],
                    'used': parts[1],
                    'available': parts[2],
                    'referenced': parts[3],
                    'mountpoint': parts[4],
                    'exists': True
                }
            
            return {'error': 'Invalid dataset info format'}
            
        except Exception as e:
            return {'error': f'Error getting dataset info: {str(e)}'}
    
    def create_snapshot(self, dataset_path: str, snapshot_name: str) -> Dict:
        """Create a ZFS snapshot"""
        try:
            if not dataset_path or not snapshot_name:
                return {'success': False, 'message': 'Dataset path and snapshot name are required'}
            
            # Validate snapshot name
            if not self._is_valid_snapshot_name(snapshot_name):
                return {'success': False, 'message': 'Invalid snapshot name'}
            
            snapshot_path = f"{dataset_path}@{snapshot_name}"
            
            logger.info(f"Creating ZFS snapshot: {snapshot_path}")
            
            snapshot_cmd = f"zfs snapshot {snapshot_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(snapshot_cmd)
            
            if success:
                logger.info(f"ZFS snapshot created successfully: {snapshot_path}")
                return {
                    'success': True,
                    'snapshot_path': snapshot_path,
                    'message': f'Snapshot {snapshot_name} created successfully'
                }
            else:
                logger.error(f"Failed to create ZFS snapshot {snapshot_path}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to create snapshot: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error creating ZFS snapshot {dataset_path}@{snapshot_name}: {str(e)}")
            return {
                'success': False,
                'message': f'Snapshot creation error: {str(e)}'
            }
    
    def set_dataset_quota(self, dataset_path: str, quota_gb: int) -> bool:
        """Set storage quota for dataset"""
        try:
            quota_cmd = f"zfs set quota={quota_gb}G {dataset_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(quota_cmd)
            
            if success:
                logger.info(f"Set quota {quota_gb}GB for dataset {dataset_path}")
                return True
            else:
                logger.error(f"Failed to set quota for dataset {dataset_path}: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting quota for dataset {dataset_path}: {str(e)}")
            return False
    
    def validate_dataset_name(self, name: str) -> Tuple[bool, str]:
        """Validate dataset name meets ZFS requirements"""
        if not name:
            return False, "Dataset name cannot be empty"
        
        if len(name) > 255:
            return False, "Dataset name too long (max 255 characters)"
        
        # ZFS naming rules: alphanumeric, underscore, hyphen, period
        # Cannot start with hyphen or period
        if name.startswith('-') or name.startswith('.'):
            return False, "Dataset name cannot start with hyphen or period"
        
        # Check for invalid characters
        valid_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.')
        if not set(name).issubset(valid_chars):
            return False, "Dataset name contains invalid characters"
        
        return True, "Dataset name is valid"
    
    def _ensure_parent_datasets(self, pool_name: str) -> Dict:
        """Ensure parent datasets exist (stagdb and stagdb/databases)"""
        try:
            # Check if stagdb dataset exists
            stagdb_dataset = f"{pool_name}/stagdb"
            check_cmd = f"zfs list {stagdb_dataset}"
            success, stdout, stderr = self.storage_utils.execute_host_command(check_cmd)
            
            if not success:
                # Create stagdb parent dataset
                logger.info(f"Creating parent dataset: {stagdb_dataset}")
                create_cmd = f"zfs create {stagdb_dataset}"
                success, stdout, stderr = self.storage_utils.execute_host_command(create_cmd)
                
                if not success:
                    return {
                        'success': False,
                        'message': f'Failed to create parent dataset {stagdb_dataset}: {stderr}'
                    }
            
            # Check if stagdb/databases dataset exists
            databases_dataset = f"{pool_name}/stagdb/databases"
            check_cmd = f"zfs list {databases_dataset}"
            success, stdout, stderr = self.storage_utils.execute_host_command(check_cmd)
            
            if not success:
                # Create databases parent dataset
                logger.info(f"Creating databases dataset: {databases_dataset}")
                create_cmd = f"zfs create {databases_dataset}"
                success, stdout, stderr = self.storage_utils.execute_host_command(create_cmd)
                
                if not success:
                    return {
                        'success': False,
                        'message': f'Failed to create databases dataset {databases_dataset}: {stderr}'
                    }
            
            return {'success': True, 'message': 'Parent datasets ready'}
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Error ensuring parent datasets: {str(e)}'
            }
    
    def _set_dataset_permissions(self, mount_path: str) -> Dict:
        """Set proper permissions for PostgreSQL container"""
        try:
            # PostgreSQL runs as user 999:999 in the container
            # Set ownership and permissions
            chown_cmd = f"chown -R 999:999 {mount_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(chown_cmd)
            
            if not success:
                logger.error(f"Failed to set ownership for {mount_path}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to set dataset permissions: {stderr}'
                }
            
            # Set directory permissions
            chmod_cmd = f"chmod 700 {mount_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(chmod_cmd)
            
            if not success:
                logger.error(f"Failed to set permissions for {mount_path}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to set directory permissions: {stderr}'
                }
            
            logger.info(f"Set proper permissions for dataset mount: {mount_path}")
            return {'success': True, 'message': 'Permissions set successfully'}
            
        except Exception as e:
            logger.error(f"Error setting dataset permissions for {mount_path}: {str(e)}")
            return {
                'success': False,
                'message': f'Permission setting error: {str(e)}'
            }
    
    def _cleanup_failed_dataset(self, dataset_path: str) -> None:
        """Clean up dataset if creation partially failed"""
        try:
            logger.info(f"Cleaning up failed dataset: {dataset_path}")
            destroy_cmd = f"zfs destroy {dataset_path}"
            self.storage_utils.execute_host_command(destroy_cmd)
        except Exception as e:
            logger.warning(f"Failed to cleanup dataset {dataset_path}: {str(e)}")
    
    def _is_valid_snapshot_name(self, name: str) -> bool:
        """Validate snapshot name"""
        if not name or len(name) > 255:
            return False
        
        # Snapshot names have similar rules to dataset names
        # but cannot contain certain characters like @
        invalid_chars = set('@/')
        return not any(char in name for char in invalid_chars)
    
    def get_dataset_metrics(self, dataset_path: str) -> Dict:
        """Get detailed storage metrics for a ZFS dataset"""
        try:
            # Get basic dataset info
            basic_info = self.get_dataset_info(dataset_path)
            if 'error' in basic_info:
                return basic_info
            
            # Get additional properties
            properties = ['used', 'available', 'referenced', 'usedbychildren', 'usedbydataset', 
                         'usedbyrefreservation', 'usedbysnapshots', 'compressratio', 'quota']
            
            metrics = {}
            for prop in properties:
                cmd = f"zfs get -H -o value {prop} {dataset_path}"
                success, stdout, stderr = self.storage_utils.execute_host_command(cmd)
                
                if success and stdout.strip():
                    metrics[prop] = stdout.strip()
                else:
                    metrics[prop] = 'Unknown'
            
            # Parse sizes for better display
            for size_prop in ['used', 'available', 'referenced', 'usedbychildren', 'usedbydataset', 
                             'usedbyrefreservation', 'usedbysnapshots']:
                if size_prop in metrics and metrics[size_prop] != 'Unknown':
                    metrics[f"{size_prop}_human"] = self._format_size(metrics[size_prop])
            
            return {
                'success': True,
                'metrics': metrics,
                'dataset_path': dataset_path
            }
            
        except Exception as e:
            logger.error(f"Error getting dataset metrics for {dataset_path}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_snapshot_hierarchy(self, dataset_path: str) -> Dict:
        """Get ZFS snapshot hierarchy from root to current dataset"""
        try:
            # Get all snapshots for this dataset and its parents
            snapshots = []
            
            # Get snapshots for current dataset
            cmd = f"zfs list -t snapshot -H -o name,creation,used -s creation {dataset_path}"
            success, stdout, stderr = self.storage_utils.execute_host_command(cmd)
            
            current_snapshots = []
            if success and stdout.strip():
                for line in stdout.strip().split('\n'):
                    parts = line.split('\t')
                    if len(parts) >= 3:
                        snapshot_name = parts[0]
                        creation_time = parts[1]
                        used_space = parts[2]
                        
                        # Parse snapshot name to get just the snapshot part
                        if '@' in snapshot_name:
                            dataset_part, snap_part = snapshot_name.split('@', 1)
                            current_snapshots.append({
                                'full_name': snapshot_name,
                                'snapshot_name': snap_part,
                                'dataset': dataset_part,
                                'creation_time': creation_time,
                                'used_space': used_space,
                                'used_space_human': self._format_size(used_space),
                                'type': 'current_dataset'
                            })
            
            # Get parent datasets and their snapshots
            parent_snapshots = self._get_parent_snapshots(dataset_path)
            
            # Combine and sort by creation time
            all_snapshots = current_snapshots + parent_snapshots
            all_snapshots.sort(key=lambda x: x.get('creation_time', ''))
            
            return {
                'success': True,
                'snapshots': all_snapshots,
                'dataset_path': dataset_path,
                'hierarchy': self._build_snapshot_hierarchy(dataset_path, all_snapshots)
            }
            
        except Exception as e:
            logger.error(f"Error getting snapshot hierarchy for {dataset_path}: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'snapshots': []
            }
    
    def _get_parent_snapshots(self, dataset_path: str):
        """Get snapshots from parent datasets"""
        try:
            parent_snapshots = []
            
            # Parse dataset path to get parents
            # e.g., pool/stagdb/databases/mydb -> check pool/stagdb/databases, pool/stagdb, pool
            path_parts = dataset_path.split('/')
            
            for i in range(len(path_parts) - 1, 0, -1):
                parent_path = '/'.join(path_parts[:i])
                
                cmd = f"zfs list -t snapshot -H -o name,creation,used -s creation {parent_path} 2>/dev/null || true"
                success, stdout, stderr = self.storage_utils.execute_host_command(cmd)
                
                if success and stdout.strip():
                    for line in stdout.strip().split('\n'):
                        parts = line.split('\t')
                        if len(parts) >= 3:
                            snapshot_name = parts[0]
                            creation_time = parts[1]
                            used_space = parts[2]
                            
                            if '@' in snapshot_name:
                                dataset_part, snap_part = snapshot_name.split('@', 1)
                                parent_snapshots.append({
                                    'full_name': snapshot_name,
                                    'snapshot_name': snap_part,
                                    'dataset': dataset_part,
                                    'creation_time': creation_time,
                                    'used_space': used_space,
                                    'used_space_human': self._format_size(used_space),
                                    'type': 'parent_dataset',
                                    'parent_level': len(path_parts) - i
                                })
            
            return parent_snapshots
            
        except Exception as e:
            logger.error(f"Error getting parent snapshots: {str(e)}")
            return []
    
    def _build_snapshot_hierarchy(self, dataset_path: str, snapshots: list) -> Dict:
        """Build a hierarchical structure of snapshots"""
        try:
            hierarchy = {
                'root': dataset_path,
                'levels': {}
            }
            
            for snapshot in snapshots:
                dataset = snapshot['dataset']
                level = len(dataset.split('/'))
                
                if level not in hierarchy['levels']:
                    hierarchy['levels'][level] = {
                        'dataset': dataset,
                        'snapshots': []
                    }
                
                hierarchy['levels'][level]['snapshots'].append(snapshot)
            
            return hierarchy
            
        except Exception as e:
            logger.error(f"Error building snapshot hierarchy: {str(e)}")
            return {'error': str(e)}
    
    def _format_size(self, size_str: str) -> str:
        """Format size string to human readable format"""
        try:
            if not size_str or size_str == '-':
                return '0 B'
            
            # If already human readable (contains letters), return as is
            if any(c.isalpha() for c in size_str):
                return size_str
            
            # Convert bytes to human readable
            size_bytes = int(size_str)
            
            for unit in ['B', 'K', 'M', 'G', 'T', 'P']:
                if size_bytes < 1024.0:
                    if unit == 'B':
                        return f"{size_bytes:.0f} {unit}"
                    else:
                        return f"{size_bytes:.1f} {unit}"
                size_bytes /= 1024.0
                
            return f"{size_bytes:.1f} E"
            
        except (ValueError, TypeError):
            return size_str
    
    def create_dataset_from_empty(self, pool_name: str, database_name: str, database=None, context: dict = None) -> Dict:
        """Create a new empty ZFS dataset for a database"""
        try:
            # Ensure parent datasets exist
            parent_creation = self._ensure_parent_datasets(pool_name)
            if not parent_creation['success']:
                return parent_creation
                
            dataset_path = f"{pool_name}/stagdb/databases/{database_name}"
            mount_path = f"/stagdb/data/{database_name}"
            
            create_cmd = (
                f"zfs create "
                f"-o recordsize=8K "
                f"-o primarycache=metadata "
                f"-o logbias=throughput "
                f"-o mountpoint={mount_path} "
                f"{dataset_path}"
            )
            
            operation, success, stdout, stderr = self._execute_with_tracking(
                'create', create_cmd, target_dataset=dataset_path, 
                database=database, context=context
            )
            
            if success:
                # Set permissions
                perm_result = self._set_dataset_permissions(mount_path)
                if not perm_result['success']:
                    logger.warning(f"Dataset created but permissions failed: {perm_result['message']}")
                
                return {
                    'success': True,
                    'dataset_path': dataset_path,
                    'mount_path': mount_path,
                    'operation': operation,
                    'message': f'Empty dataset created successfully at {dataset_path}'
                }
            else:
                return {
                    'success': False,
                    'operation': operation,
                    'message': f'Failed to create dataset: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error creating empty dataset: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def create_dataset_from_clone(self, source_database_dataset: str, target_database_name: str, 
                                pool_name: str, database=None, context: dict = None) -> Dict:
        """Create a new dataset by cloning from an existing database"""
        try:
            # Ensure parent datasets exist
            parent_creation = self._ensure_parent_datasets(pool_name)
            if not parent_creation['success']:
                return parent_creation
            # First create a snapshot of the source
            snapshot_name = f"clone-{target_database_name}-{int(time.time())}"
            snapshot_result = self.create_snapshot_with_tracking(
                source_database_dataset, snapshot_name, database, context
            )
            
            if not snapshot_result['success']:
                return snapshot_result
            
            # Then clone from the snapshot
            source_snapshot = f"{source_database_dataset}@{snapshot_name}"
            target_dataset = f"{pool_name}/stagdb/databases/{target_database_name}"
            mount_path = f"/stagdb/data/{target_database_name}"
            
            clone_cmd = f"zfs clone -o mountpoint={mount_path} {source_snapshot} {target_dataset}"
            
            operation, success, stdout, stderr = self._execute_with_tracking(
                'clone', clone_cmd, source_dataset=source_snapshot, 
                target_dataset=target_dataset, database=database, context=context
            )
            
            if success:
                # Set permissions
                perm_result = self._set_dataset_permissions(mount_path)
                if not perm_result['success']:
                    logger.warning(f"Dataset cloned but permissions failed: {perm_result['message']}")
                
                return {
                    'success': True,
                    'dataset_path': target_dataset,
                    'mount_path': mount_path,
                    'source_snapshot': source_snapshot,
                    'clone_operation': operation,
                    'snapshot_operation': snapshot_result['operation'],
                    'message': f'Dataset cloned successfully from {source_database_dataset}'
                }
            else:
                return {
                    'success': False,
                    'operation': operation,
                    'message': f'Failed to clone dataset: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error cloning dataset: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def create_dataset_from_snapshot(self, source_snapshot: str, target_database_name: str,
                                   pool_name: str, database=None, context: dict = None) -> Dict:
        """Create a new dataset by cloning from an existing snapshot"""
        try:
            # Ensure parent datasets exist
            parent_creation = self._ensure_parent_datasets(pool_name)
            if not parent_creation['success']:
                return parent_creation
            target_dataset = f"{pool_name}/stagdb/databases/{target_database_name}"
            mount_path = f"/stagdb/data/{target_database_name}"
            
            clone_cmd = f"zfs clone -o mountpoint={mount_path} {source_snapshot} {target_dataset}"
            
            operation, success, stdout, stderr = self._execute_with_tracking(
                'clone', clone_cmd, source_dataset=source_snapshot,
                target_dataset=target_dataset, database=database, context=context
            )
            
            if success:
                # Set permissions
                perm_result = self._set_dataset_permissions(mount_path)
                if not perm_result['success']:
                    logger.warning(f"Dataset restored but permissions failed: {perm_result['message']}")
                
                return {
                    'success': True,
                    'dataset_path': target_dataset,
                    'mount_path': mount_path,
                    'source_snapshot': source_snapshot,
                    'operation': operation,
                    'message': f'Dataset restored successfully from snapshot {source_snapshot}'
                }
            else:
                return {
                    'success': False,
                    'operation': operation,
                    'message': f'Failed to restore from snapshot: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error restoring from snapshot: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def create_snapshot_with_tracking(self, dataset_path: str, snapshot_name: str, 
                                    database=None, context: dict = None) -> Dict:
        """Create a ZFS snapshot with operation tracking"""
        try:
            if not dataset_path or not snapshot_name:
                return {'success': False, 'message': 'Dataset path and snapshot name are required'}
            
            # Validate snapshot name
            if not self._is_valid_snapshot_name(snapshot_name):
                return {'success': False, 'message': 'Invalid snapshot name'}
            
            snapshot_path = f"{dataset_path}@{snapshot_name}"
            snapshot_cmd = f"zfs snapshot {snapshot_path}"
            
            operation, success, stdout, stderr = self._execute_with_tracking(
                'snapshot', snapshot_cmd, source_dataset=dataset_path,
                snapshot_name=snapshot_name, database=database, context=context
            )
            
            if success:
                return {
                    'success': True,
                    'snapshot_path': snapshot_path,
                    'operation': operation,
                    'message': f'Snapshot {snapshot_name} created successfully'
                }
            else:
                return {
                    'success': False,
                    'operation': operation,
                    'message': f'Failed to create snapshot: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error creating snapshot {dataset_path}@{snapshot_name}: {str(e)}")
            return {'success': False, 'message': str(e)}
    
    def list_available_snapshots(self, pool_name: str = None) -> Dict:
        """List all available snapshots for cloning"""
        try:
            if pool_name:
                # List snapshots for specific pool
                cmd = f"zfs list -t snapshot -H -o name,creation,used,referenced -s creation {pool_name}/stagdb"
            else:
                # List all snapshots in stagdb datasets
                cmd = "zfs list -t snapshot -H -o name,creation,used,referenced -s creation"
            
            success, stdout, stderr = self.storage_utils.execute_host_command(cmd)
            
            if not success:
                return {'success': False, 'message': f'Failed to list snapshots: {stderr}'}
            
            snapshots = []
            if stdout.strip():
                for line in stdout.strip().split('\n'):
                    parts = line.split('\t')
                    if len(parts) >= 4 and 'stagdb' in parts[0]:
                        snapshot_name = parts[0]
                        creation_time = parts[1]
                        used_space = parts[2]
                        referenced = parts[3]
                        
                        if '@' in snapshot_name:
                            dataset_part, snap_part = snapshot_name.split('@', 1)
                            snapshots.append({
                                'full_name': snapshot_name,
                                'dataset': dataset_part,
                                'snapshot_name': snap_part,
                                'creation_time': creation_time,
                                'used_space': used_space,
                                'referenced': referenced,
                                'used_space_human': self._format_size(used_space),
                                'referenced_human': self._format_size(referenced)
                            })
            
            return {
                'success': True,
                'snapshots': snapshots,
                'count': len(snapshots)
            }
            
        except Exception as e:
            logger.error(f"Error listing snapshots: {str(e)}")
            return {'success': False, 'message': str(e)}