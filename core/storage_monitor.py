"""
Storage Configuration Monitoring and Sync Management

Strategies for keeping storage configurations synchronized with actual infrastructure.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from django.utils import timezone
from django.db import transaction
from .models import StorageConfiguration, HostVM
from .storage_utils import StorageUtils

logger = logging.getLogger(__name__)


class StorageConfigurationMonitor:
    """Monitor and sync storage configurations with actual infrastructure"""
    
    def __init__(self):
        self.storage_utils = StorageUtils()
        self.monitoring_interval = 300  # 5 minutes
        self.health_check_interval = 60   # 1 minute
    
    # Strategy 1: Continuous Health Monitoring
    def monitor_storage_health(self) -> Dict:
        """
        Continuously monitor storage configuration health
        - Check pool status every minute
        - Update configuration health status
        - Alert on issues
        """
        results = {
            'healthy': [],
            'degraded': [],
            'failed': [],
            'missing': []
        }
        
        for config in StorageConfiguration.objects.filter(is_active=True, is_configured=True):
            try:
                health_status = self._check_configuration_health(config)
                
                # Update configuration health in database
                config.last_health_check = timezone.now()
                config.health_status = health_status['status']
                config.health_details = health_status['details']
                
                if health_status['status'] == 'healthy':
                    results['healthy'].append(config.name)
                elif health_status['status'] == 'degraded':
                    results['degraded'].append({
                        'name': config.name,
                        'issues': health_status['issues']
                    })
                elif health_status['status'] == 'failed':
                    results['failed'].append({
                        'name': config.name,
                        'error': health_status['error']
                    })
                elif health_status['status'] == 'missing':
                    results['missing'].append(config.name)
                    # Mark as not configured if infrastructure is missing
                    config.is_configured = False
                    config.configuration_error = f"Infrastructure missing: {health_status['error']}"
                
                config.save()
                
            except Exception as e:
                logger.error(f"Health check failed for {config.name}: {str(e)}")
                results['failed'].append({
                    'name': config.name,
                    'error': str(e)
                })
        
        return results
    
    def _check_configuration_health(self, config: StorageConfiguration) -> Dict:
        """Check health of a specific storage configuration"""
        if config.storage_type == 'existing_pool':
            return self._check_pool_health(config.existing_pool_name)
        
        elif config.storage_type in ['dedicated_disk', 'multi_disk']:
            pool_name = config.get_pool_name()
            pool_health = self._check_pool_health(pool_name)
            
            if pool_health['status'] == 'healthy':
                # Also check underlying disks
                disk_health = self._check_disk_health(config.dedicated_disks)
                if disk_health['status'] != 'healthy':
                    return {
                        'status': 'degraded',
                        'details': pool_health['details'],
                        'issues': disk_health['issues']
                    }
            
            return pool_health
        
        elif config.storage_type == 'image_file':
            # Check both image file and pool
            file_health = self._check_image_file_health(config.image_file_path)
            if file_health['status'] != 'healthy':
                return file_health
            
            pool_name = config.get_pool_name()
            return self._check_pool_health(pool_name)
        
        elif config.storage_type == 'directory':
            return self._check_directory_health(config.storage_directory)
        
        return {'status': 'unknown', 'details': {}, 'error': 'Unknown storage type'}
    
    def _check_pool_health(self, pool_name: str) -> Dict:
        """Check ZFS pool health"""
        try:
            validation_result = self.storage_utils.validate_existing_pool(pool_name)
            
            if validation_result['valid']:
                return {
                    'status': 'healthy',
                    'details': {
                        'health': validation_result.get('health'),
                        'size': validation_result.get('size'),
                        'free': validation_result.get('free')
                    }
                }
            else:
                return {
                    'status': 'missing',
                    'details': {},
                    'error': validation_result['message']
                }
        except Exception as e:
            return {
                'status': 'failed',
                'details': {},
                'error': str(e)
            }
    
    def _check_disk_health(self, disk_paths: List[str]) -> Dict:
        """Check physical disk health"""
        issues = []
        
        for disk_path in disk_paths:
            success, stdout, stderr = self.storage_utils.execute_host_command(
                f"smartctl -H {disk_path}"
            )
            
            if not success:
                issues.append(f"Cannot check health of {disk_path}: {stderr}")
                continue
            
            if "PASSED" not in stdout:
                issues.append(f"Disk {disk_path} health check failed")
        
        return {
            'status': 'healthy' if not issues else 'degraded',
            'issues': issues
        }
    
    def _check_image_file_health(self, image_path: str) -> Dict:
        """Check image file health"""
        success, stdout, stderr = self.storage_utils.execute_host_command(
            f"test -f {image_path} && stat {image_path}"
        )
        
        if not success:
            return {
                'status': 'missing',
                'details': {},
                'error': f"Image file not found: {image_path}"
            }
        
        return {
            'status': 'healthy',
            'details': {'path': image_path}
        }
    
    def _check_directory_health(self, directory: str) -> Dict:
        """Check directory storage health"""
        success, stdout, stderr = self.storage_utils.execute_host_command(
            f"test -d {directory} && df -h {directory}"
        )
        
        if not success:
            return {
                'status': 'missing',
                'details': {},
                'error': f"Directory not found: {directory}"
            }
        
        return {
            'status': 'healthy',
            'details': {'path': directory, 'df_output': stdout}
        }

    # Strategy 2: Reality Reconciliation
    def reconcile_with_reality(self) -> Dict:
        """
        Reconcile database state with actual infrastructure
        - Scan actual ZFS pools
        - Compare with stored configurations
        - Identify orphaned pools and missing configurations
        """
        results = {
            'reconciled': [],
            'orphaned_pools': [],
            'missing_pools': [],
            'conflicts': []
        }
        
        # Get actual pools from system
        actual_pools = self._discover_actual_pools()
        
        # Get configured pools from database
        configured_pools = {}
        for config in StorageConfiguration.objects.filter(is_active=True):
            if config.storage_type in ['existing_pool', 'dedicated_disk', 'multi_disk', 'image_file']:
                pool_name = config.get_pool_name()
                configured_pools[pool_name] = config
        
        # Find orphaned pools (exist but not configured)
        for pool_name, pool_info in actual_pools.items():
            if pool_name not in configured_pools:
                results['orphaned_pools'].append({
                    'name': pool_name,
                    'size': pool_info.get('size'),
                    'health': pool_info.get('health'),
                    'suggestion': 'Create configuration for existing pool'
                })
        
        # Find missing pools (configured but don't exist)
        for pool_name, config in configured_pools.items():
            if config.is_configured and pool_name not in actual_pools:
                results['missing_pools'].append({
                    'name': pool_name,
                    'config_name': config.name,
                    'config_id': config.id,
                    'suggestion': 'Mark configuration as not configured or recreate pool'
                })
                
                # Automatically mark as not configured
                config.is_configured = False
                config.configuration_error = f"Pool {pool_name} no longer exists"
                config.save()
        
        # Reconcile existing matches
        for pool_name in set(actual_pools.keys()) & set(configured_pools.keys()):
            config = configured_pools[pool_name]
            actual_info = actual_pools[pool_name]
            
            # Update configuration with actual information
            if not config.is_configured:
                config.is_configured = True
                config.configuration_error = ""
            
            # Store actual pool information
            config.actual_pool_info = actual_info
            config.last_reconciliation = timezone.now()
            config.save()
            
            results['reconciled'].append({
                'name': pool_name,
                'config_name': config.name,
                'health': actual_info.get('health')
            })
        
        return results
    
    def _discover_actual_pools(self) -> Dict:
        """Discover all ZFS pools on the system"""
        success, stdout, stderr = self.storage_utils.execute_host_command("zpool list -H")
        
        if not success:
            logger.error(f"Failed to list ZFS pools: {stderr}")
            return {}
        
        pools = {}
        for line in stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 3:
                    name = parts[0]
                    size = parts[1]
                    free = parts[2]
                    
                    # Get detailed health info
                    health_success, health_out, _ = self.storage_utils.execute_host_command(
                        f"zpool status {name} | grep 'state:' | awk '{{print $2}}'"
                    )
                    health = health_out.strip() if health_success else 'UNKNOWN'
                    
                    pools[name] = {
                        'size': size,
                        'free': free,
                        'health': health
                    }
        
        return pools

    # Strategy 3: Automatic Remediation
    def auto_remediate_issues(self) -> Dict:
        """
        Automatically fix common storage configuration issues
        - Recreate missing pools where possible
        - Fix pool import issues
        - Update configuration states
        """
        results = {
            'remediated': [],
            'failed_remediation': [],
            'manual_intervention_required': []
        }
        
        for config in StorageConfiguration.objects.filter(is_active=True):
            if hasattr(config, 'health_status') and config.health_status in ['failed', 'missing']:
                try:
                    remediation_result = self._attempt_remediation(config)
                    
                    if remediation_result['success']:
                        results['remediated'].append({
                            'config': config.name,
                            'action': remediation_result['action'],
                            'details': remediation_result['details']
                        })
                    else:
                        if remediation_result.get('requires_manual'):
                            results['manual_intervention_required'].append({
                                'config': config.name,
                                'issue': remediation_result['error'],
                                'suggested_action': remediation_result.get('suggested_action')
                            })
                        else:
                            results['failed_remediation'].append({
                                'config': config.name,
                                'error': remediation_result['error']
                            })
                
                except Exception as e:
                    logger.error(f"Remediation failed for {config.name}: {str(e)}")
                    results['failed_remediation'].append({
                        'config': config.name,
                        'error': str(e)
                    })
        
        return results
    
    def _attempt_remediation(self, config: StorageConfiguration) -> Dict:
        """Attempt to remediate a storage configuration issue"""
        
        if config.storage_type == 'existing_pool':
            # Try to import the pool if it exists but is not imported
            pool_name = config.existing_pool_name
            
            # Check if pool exists but is not imported
            success, stdout, stderr = self.storage_utils.execute_host_command(
                f"zpool import | grep -A1 'pool: {pool_name}'"
            )
            
            if success and pool_name in stdout:
                # Pool exists but not imported, try to import it
                import_success, import_out, import_err = self.storage_utils.execute_host_command(
                    f"zpool import {pool_name}"
                )
                
                if import_success:
                    config.is_configured = True
                    config.configuration_error = ""
                    config.save()
                    return {
                        'success': True,
                        'action': 'imported_pool',
                        'details': f"Successfully imported pool {pool_name}"
                    }
                else:
                    return {
                        'success': False,
                        'error': f"Failed to import pool {pool_name}: {import_err}",
                        'requires_manual': True,
                        'suggested_action': f"Manually import pool: zpool import {pool_name}"
                    }
            
            return {
                'success': False,
                'error': f"Pool {pool_name} not found in system",
                'requires_manual': True,
                'suggested_action': f"Recreate pool {pool_name} or update configuration"
            }
        
        elif config.storage_type in ['dedicated_disk', 'multi_disk']:
            # For dedicated disks, we can potentially recreate the pool
            # But this is dangerous as it would destroy data
            return {
                'success': False,
                'error': "Pool missing for dedicated disk configuration",
                'requires_manual': True,
                'suggested_action': f"Manually recreate pool or restore from backup"
            }
        
        elif config.storage_type == 'image_file':
            # Check if image file exists but pool is not imported
            if config.image_file_path:
                success, stdout, stderr = self.storage_utils.execute_host_command(
                    f"test -f {config.image_file_path}"
                )
                
                if success:
                    # Image file exists, try to import pool
                    pool_name = config.get_pool_name()
                    import_success, import_out, import_err = self.storage_utils.execute_host_command(
                        f"zpool import -d {config.image_file_path} {pool_name}"
                    )
                    
                    if import_success:
                        config.is_configured = True
                        config.configuration_error = ""
                        config.save()
                        return {
                            'success': True,
                            'action': 'imported_image_pool',
                            'details': f"Successfully imported pool {pool_name} from {config.image_file_path}"
                        }
        
        return {
            'success': False,
            'error': "No remediation strategy available for this configuration type"
        }

    # Strategy 4: Configuration Drift Detection
    def detect_configuration_drift(self) -> Dict:
        """
        Detect when actual infrastructure differs from stored configuration
        - Compare expected vs actual pool properties
        - Detect unauthorized changes
        - Alert on significant deviations
        """
        drift_results = {
            'no_drift': [],
            'minor_drift': [],
            'major_drift': [],
            'configuration_errors': []
        }
        
        for config in StorageConfiguration.objects.filter(is_active=True, is_configured=True):
            try:
                drift_analysis = self._analyze_configuration_drift(config)
                
                if drift_analysis['drift_level'] == 'none':
                    drift_results['no_drift'].append(config.name)
                elif drift_analysis['drift_level'] == 'minor':
                    drift_results['minor_drift'].append({
                        'config': config.name,
                        'differences': drift_analysis['differences']
                    })
                elif drift_analysis['drift_level'] == 'major':
                    drift_results['major_drift'].append({
                        'config': config.name,
                        'differences': drift_analysis['differences'],
                        'recommended_action': drift_analysis['recommended_action']
                    })
                
            except Exception as e:
                logger.error(f"Drift detection failed for {config.name}: {str(e)}")
                drift_results['configuration_errors'].append({
                    'config': config.name,
                    'error': str(e)
                })
        
        return drift_results
    
    def _analyze_configuration_drift(self, config: StorageConfiguration) -> Dict:
        """Analyze configuration drift for a specific storage configuration"""
        differences = []
        
        if config.storage_type in ['existing_pool', 'dedicated_disk', 'multi_disk', 'image_file']:
            pool_name = config.get_pool_name()
            
            # Get actual pool properties
            success, stdout, stderr = self.storage_utils.execute_host_command(
                f"zfs get all {pool_name} -H -p"
            )
            
            if not success:
                return {
                    'drift_level': 'major',
                    'differences': [f"Cannot read pool properties: {stderr}"],
                    'recommended_action': 'Check pool accessibility'
                }
            
            actual_props = {}
            for line in stdout.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 3:
                    actual_props[parts[1]] = parts[2]
            
            # Compare expected vs actual properties
            expected_compression = config.compression
            actual_compression = actual_props.get('compression', 'off')
            
            if expected_compression != actual_compression:
                differences.append(f"Compression: expected {expected_compression}, actual {actual_compression}")
            
            expected_dedup = 'on' if config.dedup else 'off'
            actual_dedup = actual_props.get('dedup', 'off')
            
            if expected_dedup != actual_dedup:
                differences.append(f"Deduplication: expected {expected_dedup}, actual {actual_dedup}")
        
        # Determine drift level
        if not differences:
            drift_level = 'none'
        elif len(differences) <= 2:
            drift_level = 'minor'
        else:
            drift_level = 'major'
        
        return {
            'drift_level': drift_level,
            'differences': differences,
            'recommended_action': 'Update configuration to match actual state' if differences else None
        }

    # Strategy 5: Preventive Validation
    def validate_before_operations(self, config_id: int, operation: str) -> Dict:
        """
        Validate storage configuration before critical operations
        - Pre-database creation validation
        - Pre-snapshot validation  
        - Pre-backup validation
        """
        try:
            config = StorageConfiguration.objects.get(id=config_id, is_active=True)
        except StorageConfiguration.DoesNotExist:
            return {
                'valid': False,
                'error': 'Storage configuration not found'
            }
        
        # Run comprehensive validation
        validation_result = config.validate_configuration()
        
        if not validation_result['valid']:
            return {
                'valid': False,
                'error': f"Storage validation failed: {validation_result['message']}",
                'remediation_suggestions': self._get_remediation_suggestions(config, validation_result)
            }
        
        # Operation-specific validation
        if operation == 'create_database':
            return self._validate_for_database_creation(config)
        elif operation == 'create_snapshot':
            return self._validate_for_snapshot_creation(config)
        elif operation == 'backup':
            return self._validate_for_backup(config)
        
        return {'valid': True, 'message': 'Validation passed'}
    
    def _validate_for_database_creation(self, config: StorageConfiguration) -> Dict:
        """Validate storage is ready for database creation"""
        pool_name = config.get_pool_name()
        
        # Check available space
        success, stdout, stderr = self.storage_utils.execute_host_command(
            f"zpool list -H {pool_name} | awk '{{print $4}}'"
        )
        
        if success:
            free_space = stdout.strip()
            # Parse free space (e.g., "45.2G" -> 45.2)
            if 'G' in free_space:
                free_gb = float(free_space.replace('G', ''))
                if free_gb < 5.0:  # Minimum 5GB required
                    return {
                        'valid': False,
                        'error': f"Insufficient space: {free_space} available, minimum 5GB required"
                    }
        
        return {'valid': True, 'message': 'Ready for database creation'}
    
    def _validate_for_snapshot_creation(self, config: StorageConfiguration) -> Dict:
        """Validate storage is ready for snapshot creation"""
        # Check if snapshots are enabled
        pool_name = config.get_pool_name()
        success, stdout, stderr = self.storage_utils.execute_host_command(
            f"zfs get snapdir {pool_name} -H | awk '{{print $3}}'"
        )
        
        if success and stdout.strip() == 'hidden':
            return {
                'valid': False,
                'error': 'Snapshots are disabled on this pool',
                'remediation': f'Enable snapshots: zfs set snapdir=visible {pool_name}'
            }
        
        return {'valid': True, 'message': 'Ready for snapshot creation'}
    
    def _validate_for_backup(self, config: StorageConfiguration) -> Dict:
        """Validate storage is ready for backup operations"""
        # Check pool health for backup reliability
        validation_result = self.storage_utils.validate_existing_pool(config.get_pool_name())
        
        if validation_result['valid'] and validation_result.get('health') != 'ONLINE':
            return {
                'valid': False,
                'error': f"Pool health is {validation_result.get('health')}, not suitable for backup"
            }
        
        return {'valid': True, 'message': 'Ready for backup operations'}
    
    def _get_remediation_suggestions(self, config: StorageConfiguration, validation_result: Dict) -> List[str]:
        """Get remediation suggestions for validation failures"""
        suggestions = []
        
        if 'not found' in validation_result.get('message', '').lower():
            if config.storage_type == 'existing_pool':
                suggestions.append(f"Import pool: zpool import {config.existing_pool_name}")
            else:
                suggestions.append("Recreate the missing pool or update configuration")
        
        if 'unhealthy' in validation_result.get('message', '').lower():
            suggestions.append("Check pool status: zpool status")
            suggestions.append("Repair pool issues before proceeding")
        
        return suggestions


# Strategy 6: Integration Points
class StorageConfigurationSyncManager:
    """High-level manager for storage configuration synchronization"""
    
    def __init__(self):
        self.monitor = StorageConfigurationMonitor()
    
    def run_full_sync_cycle(self) -> Dict:
        """Run a complete synchronization cycle"""
        results = {
            'timestamp': timezone.now().isoformat(),
            'health_monitoring': {},
            'reality_reconciliation': {},
            'drift_detection': {},
            'auto_remediation': {}
        }
        
        try:
            # 1. Health monitoring
            results['health_monitoring'] = self.monitor.monitor_storage_health()
            
            # 2. Reality reconciliation
            results['reality_reconciliation'] = self.monitor.reconcile_with_reality()
            
            # 3. Drift detection
            results['drift_detection'] = self.monitor.detect_configuration_drift()
            
            # 4. Auto remediation (if enabled)
            results['auto_remediation'] = self.monitor.auto_remediate_issues()
            
        except Exception as e:
            logger.error(f"Full sync cycle failed: {str(e)}")
            results['error'] = str(e)
        
        return results
    
    def get_sync_status_summary(self) -> Dict:
        """Get a summary of storage configuration sync status"""
        total_configs = StorageConfiguration.objects.filter(is_active=True).count()
        configured_configs = StorageConfiguration.objects.filter(is_active=True, is_configured=True).count()
        
        # Get health status distribution if available
        health_stats = {}
        if hasattr(StorageConfiguration, 'health_status'):
            from django.db.models import Count
            health_distribution = StorageConfiguration.objects.filter(is_active=True).values('health_status').annotate(count=Count('health_status'))
            health_stats = {item['health_status']: item['count'] for item in health_distribution}
        
        return {
            'total_configurations': total_configs,
            'configured_configurations': configured_configs,
            'configuration_rate': (configured_configs / total_configs * 100) if total_configs > 0 else 0,
            'health_distribution': health_stats,
            'last_sync': timezone.now().isoformat()
        }