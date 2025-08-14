import os
import logging
from typing import Dict, Tuple
from .storage_utils import StorageUtils

logger = logging.getLogger(__name__)


class ZFSDatasetManager:
    """ZFS dataset operations for database storage"""
    
    def __init__(self, host_vm):
        self.host_vm = host_vm
        self.storage_utils = StorageUtils()
    
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