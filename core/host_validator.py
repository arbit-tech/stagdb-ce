import logging
from datetime import datetime
from typing import Dict, Any, List, Tuple
from .host_system import HostSystemManager

logger = logging.getLogger(__name__)


class HostValidator:
    """Validates Docker host prerequisites for StagDB deployment from container"""
    
    def __init__(self):
        self.system_manager = HostSystemManager()
        self.validation_results = {}
        self.validation_timestamp = None
        
    def validate_all(self) -> Dict[str, Any]:
        """Run all validation checks and return comprehensive report"""
        logger.info("Starting comprehensive host system validation")
        self.validation_timestamp = datetime.now()
        
        self.validation_results = {
            'timestamp': self.validation_timestamp.isoformat(),
            'overall_status': 'unknown',
            'container_environment': self._validate_container_environment(),
            'docker_access': self._validate_docker_access(),
            'docker_engine': self._validate_docker_engine(),
            'docker_compose': self._validate_docker_compose(),
            'zfs_utilities': self._validate_zfs_utilities(),
            'zfs_pools': self._validate_zfs_pools(),
            'host_resources': self._validate_host_resources(),
            'network_ports': self._validate_network_ports(),
            'system_info': self.system_manager.get_system_info()
        }
        
        # Determine overall status
        overall_status = self._determine_overall_status()
        self.validation_results['overall_status'] = overall_status
        
        # Add appropriate message based on status
        if overall_status == 'valid':
            self.validation_results['message'] = 'Host validation successful. System is ready for database deployment.'
        elif overall_status == 'warning':
            self.validation_results['message'] = 'Host validation passed with warnings. Some features may be limited.'
        elif overall_status == 'invalid':
            self.validation_results['message'] = 'Host validation failed. Please address the issues before proceeding.'
        else:
            self.validation_results['message'] = 'Host validation status unknown. Please check system configuration.'
        
        logger.info(f"Validation completed with status: {self.validation_results['overall_status']}")
        return self.validation_results
    
    def _validate_container_environment(self) -> Dict[str, Any]:
        """Validate container environment and privileges"""
        result = {
            'status': 'unknown',
            'in_container': self.system_manager.is_in_container,
            'checks': {}
        }
        
        if not self.system_manager.is_in_container:
            result['status'] = 'warning'
            result['message'] = 'Not running in container - direct host access'
            result['checks']['container_detection'] = {'status': 'pass', 'message': 'Direct host access'}
        else:
            # Test privileged access
            privileged_ok, privileged_msg = self.system_manager.test_privileged_access()
            result['checks']['privileged_access'] = {
                'status': 'pass' if privileged_ok else 'fail',
                'message': privileged_msg
            }
            
            if privileged_ok:
                result['status'] = 'pass'
                result['message'] = 'Container has proper host access'
            else:
                result['status'] = 'fail'
                result['message'] = 'Container lacks privileged host access'
        
        return result
    
    def _validate_docker_access(self) -> Dict[str, Any]:
        """Validate Docker socket access from container"""
        result = {
            'status': 'unknown',
            'checks': {}
        }
        
        # Test Docker socket access
        socket_ok, socket_msg = self.system_manager.test_docker_socket_access()
        result['checks']['socket_access'] = {
            'status': 'pass' if socket_ok else 'fail',
            'message': socket_msg
        }
        
        if socket_ok:
            # Test creating a simple container
            success, stdout, stderr = self.system_manager.execute_command(
                "docker run --rm hello-world", timeout=60
            )
            result['checks']['container_creation'] = {
                'status': 'pass' if success else 'fail',
                'message': 'Can create containers' if success else f'Cannot create containers: {stderr}'
            }
            
            if success:
                result['status'] = 'pass'
                result['message'] = 'Docker access fully functional'
            else:
                result['status'] = 'warning'
                result['message'] = 'Docker socket accessible but container creation failed'
        else:
            result['status'] = 'fail'
            result['message'] = 'Docker socket not accessible'
        
        return result
    
    def _validate_docker_engine(self) -> Dict[str, Any]:
        """Validate Docker engine installation and version"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {}
        }
        
        docker_info = self.system_manager.get_docker_info()
        result['info'] = docker_info
        
        # Check Docker version
        if 'docker_version' in docker_info:
            version_str = docker_info['docker_version']
            result['checks']['version'] = {
                'status': 'pass',
                'message': f'Docker installed: {version_str}',
                'value': version_str
            }
            
            # Parse version for minimum requirement check
            try:
                # Extract version number (e.g., "Docker version 24.0.7" -> "24.0.7")
                version_parts = version_str.split()
                if len(version_parts) >= 3:
                    version_num = version_parts[2].split(',')[0]  # Remove any trailing comma
                    major, minor = map(int, version_num.split('.')[:2])
                    
                    if major > 20 or (major == 20 and minor >= 10):
                        result['checks']['version_requirement'] = {
                            'status': 'pass',
                            'message': f'Version {version_num} meets minimum requirement (20.10+)'
                        }
                    else:
                        result['checks']['version_requirement'] = {
                            'status': 'fail',
                            'message': f'Version {version_num} below minimum requirement (20.10+)'
                        }
            except (ValueError, IndexError):
                result['checks']['version_requirement'] = {
                    'status': 'warning',
                    'message': 'Could not parse Docker version for requirement check'
                }
        else:
            result['checks']['version'] = {
                'status': 'fail',
                'message': f"Docker not found: {docker_info.get('docker_version_error', 'Unknown error')}"
            }
        
        # Check Docker info
        if 'docker_info' in docker_info:
            info_data = docker_info['docker_info']
            result['checks']['daemon'] = {
                'status': 'pass',
                'message': f"Docker daemon running, {info_data.get('containers_total', 0)} containers, {info_data.get('images', 0)} images"
            }
        else:
            result['checks']['daemon'] = {
                'status': 'fail',
                'message': f"Docker daemon not accessible: {docker_info.get('docker_info_error', 'Unknown error')}"
            }
        
        # Determine overall status
        if all(check.get('status') == 'pass' for check in result['checks'].values()):
            result['status'] = 'pass'
            result['message'] = 'Docker engine fully functional'
        elif any(check.get('status') == 'fail' for check in result['checks'].values()):
            result['status'] = 'fail'
            result['message'] = 'Docker engine issues detected'
        else:
            result['status'] = 'warning'
            result['message'] = 'Docker engine partially functional'
        
        return result
    
    def _validate_docker_compose(self) -> Dict[str, Any]:
        """Validate Docker Compose installation"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {}
        }
        
        docker_info = self.system_manager.get_docker_info()
        
        if 'docker_compose_version' in docker_info:
            version_str = docker_info['docker_compose_version']
            result['checks']['installation'] = {
                'status': 'pass',
                'message': f'Docker Compose available: {version_str}',
                'value': version_str
            }
            
            # Check version requirement
            try:
                if 'v2.' in version_str or 'version 2.' in version_str:
                    result['checks']['version_requirement'] = {
                        'status': 'pass',
                        'message': 'Docker Compose v2.x detected (recommended)'
                    }
                elif 'v1.' in version_str or 'version 1.' in version_str:
                    # Extract version for more specific check
                    if '1.25' in version_str or any(f'1.{i}' in version_str for i in range(25, 30)):
                        result['checks']['version_requirement'] = {
                            'status': 'warning',
                            'message': 'Docker Compose v1.25+ detected (functional but v2.x recommended)'
                        }
                    else:
                        result['checks']['version_requirement'] = {
                            'status': 'fail',
                            'message': 'Docker Compose version too old (minimum 1.25 or 2.0 required)'
                        }
                else:
                    result['checks']['version_requirement'] = {
                        'status': 'warning',
                        'message': 'Could not determine Docker Compose version requirement'
                    }
            except Exception:
                result['checks']['version_requirement'] = {
                    'status': 'warning',
                    'message': 'Could not parse Docker Compose version'
                }
        else:
            result['checks']['installation'] = {
                'status': 'fail',
                'message': f"Docker Compose not found: {docker_info.get('docker_compose_error', 'Unknown error')}"
            }
        
        # Determine overall status
        if all(check.get('status') == 'pass' for check in result['checks'].values()):
            result['status'] = 'pass'
            result['message'] = 'Docker Compose fully functional'
        elif any(check.get('status') == 'fail' for check in result['checks'].values()):
            result['status'] = 'fail'
            result['message'] = 'Docker Compose issues detected'
        else:
            result['status'] = 'warning'
            result['message'] = 'Docker Compose functional with warnings'
        
        return result
    
    def _validate_zfs_utilities(self) -> Dict[str, Any]:
        """Validate ZFS utilities installation on host"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {},
            'can_install': False,
            'os_info': {}
        }

        zfs_info = self.system_manager.get_zfs_info()
        result['info'] = zfs_info

        # Check ZFS utilities
        if 'zfs_path' in zfs_info and 'zpool_path' in zfs_info:
            result['checks']['utilities'] = {
                'status': 'pass',
                'message': f"ZFS utilities found: zfs at {zfs_info['zfs_path']}, zpool at {zfs_info['zpool_path']}"
            }
        else:
            missing = []
            if 'zfs_path_error' in zfs_info:
                missing.append('zfs')
            if 'zpool_path_error' in zfs_info:
                missing.append('zpool')

            # Detect OS to check if we can install ZFS
            os_info = self.system_manager.detect_os()
            result['os_info'] = os_info
            result['can_install'] = os_info.get('zfs_installable', False)

            install_hint = ""
            if result['can_install']:
                install_hint = f" (can be installed on {os_info.get('pretty_name', 'this system')})"

            result['checks']['utilities'] = {
                'status': 'fail',
                'message': f"Missing ZFS utilities: {', '.join(missing)}{install_hint}"
            }
        
        # Check ZFS version
        if 'zfs_version' in zfs_info:
            version_str = zfs_info['zfs_version']
            result['checks']['version'] = {
                'status': 'pass',
                'message': f'ZFS version: {version_str}',
                'value': version_str
            }
            
            # Basic version requirement check
            try:
                if any(f'zfs-{v}' in version_str.lower() for v in ['2.1', '2.2', '0.8', '0.9']):
                    result['checks']['version_requirement'] = {
                        'status': 'pass',
                        'message': 'ZFS version meets requirements'
                    }
                else:
                    result['checks']['version_requirement'] = {
                        'status': 'warning',
                        'message': 'Could not verify ZFS version requirement'
                    }
            except Exception:
                result['checks']['version_requirement'] = {
                    'status': 'warning',
                    'message': 'Could not parse ZFS version'
                }
        else:
            result['checks']['version'] = {
                'status': 'fail',
                'message': f"ZFS version check failed: {zfs_info.get('zfs_version_error', 'Unknown error')}"
            }
        
        # Check ZFS kernel modules
        if 'zfs_modules' in zfs_info:
            result['checks']['kernel_modules'] = {
                'status': 'pass',
                'message': 'ZFS kernel modules loaded',
                'value': zfs_info['zfs_modules']
            }
        else:
            result['checks']['kernel_modules'] = {
                'status': 'fail',
                'message': f"ZFS kernel modules not loaded: {zfs_info.get('zfs_modules_error', 'Unknown error')}"
            }
        
        # Determine overall status
        if all(check.get('status') == 'pass' for check in result['checks'].values()):
            result['status'] = 'pass'
            result['message'] = 'ZFS utilities fully functional'
        elif any(check.get('status') == 'fail' for check in result['checks'].values()):
            result['status'] = 'fail'
            result['message'] = 'ZFS utilities issues detected'
        else:
            result['status'] = 'warning'
            result['message'] = 'ZFS utilities functional with warnings'
        
        return result
    
    def _validate_zfs_pools(self) -> Dict[str, Any]:
        """Validate ZFS pools availability on host"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {}
        }
        
        zfs_info = self.system_manager.get_zfs_info()
        
        if 'zfs_pools' in zfs_info:
            pools = zfs_info['zfs_pools']
            result['info']['pools'] = pools
            
            if pools:
                healthy_pools = [p for p in pools if p.get('health') == 'ONLINE']
                result['checks']['availability'] = {
                    'status': 'pass',
                    'message': f"Found {len(pools)} ZFS pools, {len(healthy_pools)} healthy",
                    'value': {'total': len(pools), 'healthy': len(healthy_pools)}
                }
                
                # Check for adequate free space
                adequate_pools = []
                for pool in healthy_pools:
                    try:
                        free_str = pool.get('free', '0')
                        # Simple check for GB/TB indicators
                        if 'T' in free_str or ('G' in free_str and float(free_str.replace('G', '')) >= 10):
                            adequate_pools.append(pool['name'])
                    except (ValueError, TypeError):
                        continue
                
                if adequate_pools:
                    result['checks']['space'] = {
                        'status': 'pass',
                        'message': f"Pools with adequate space (10GB+): {', '.join(adequate_pools)}"
                    }
                else:
                    result['checks']['space'] = {
                        'status': 'warning',
                        'message': 'No pools found with clearly adequate free space'
                    }
            else:
                # Don't fail host validation if no pools exist - they'll be created in storage step
                result['checks']['availability'] = {
                    'status': 'warning',
                    'message': 'No ZFS pools found (will be configured in storage setup)'
                }
        else:
            # Don't fail host validation if we can't list pools - ZFS might not be fully configured yet
            result['checks']['availability'] = {
                'status': 'warning',
                'message': f"Could not list ZFS pools: {zfs_info.get('zfs_pools_error', 'Unknown error')}. This will be addressed in storage setup."
            }
        
        # Determine overall status - never fail on ZFS pools during initial host validation
        if all(check.get('status') == 'pass' for check in result['checks'].values()):
            result['status'] = 'pass'
            result['message'] = 'ZFS pools available and ready'
        else:
            # Even if checks have warnings/failures, return warning to allow progression
            result['status'] = 'warning'
            result['message'] = 'ZFS pools will be configured in the storage setup step'
        
        return result
    
    def _validate_host_resources(self) -> Dict[str, Any]:
        """Validate host system resources"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {}
        }
        
        resources = self.system_manager.get_host_system_resources()
        result['info'] = resources
        
        # Check memory
        if 'memory_total_gb' in resources:
            memory_gb = resources['memory_total_gb']
            if memory_gb >= 4:
                result['checks']['memory'] = {
                    'status': 'pass',
                    'message': f'{memory_gb}GB RAM available (minimum 4GB)',
                    'value': memory_gb
                }
            elif memory_gb >= 2:
                result['checks']['memory'] = {
                    'status': 'warning',
                    'message': f'{memory_gb}GB RAM available (4GB recommended)',
                    'value': memory_gb
                }
            else:
                result['checks']['memory'] = {
                    'status': 'fail',
                    'message': f'{memory_gb}GB RAM available (minimum 4GB required)',
                    'value': memory_gb
                }
        else:
            result['checks']['memory'] = {
                'status': 'fail',
                'message': f"Could not check memory: {resources.get('memory_error', 'Unknown error')}"
            }
        
        # Check CPU
        if 'cpu_cores' in resources:
            cpu_cores = resources['cpu_cores']
            if cpu_cores >= 2:
                result['checks']['cpu'] = {
                    'status': 'pass',
                    'message': f'{cpu_cores} CPU cores available (minimum 2)',
                    'value': cpu_cores
                }
            else:
                result['checks']['cpu'] = {
                    'status': 'warning',
                    'message': f'{cpu_cores} CPU core available (2+ recommended)',
                    'value': cpu_cores
                }
        else:
            result['checks']['cpu'] = {
                'status': 'fail',
                'message': f"Could not check CPU: {resources.get('cpu_cores_error', 'Unknown error')}"
            }
        
        # Check disk space
        if 'disk_available' in resources:
            disk_available = resources['disk_available']
            result['checks']['disk'] = {
                'status': 'pass',
                'message': f'{disk_available} disk space available',
                'value': disk_available
            }
            
            # Try to parse for specific check
            try:
                if 'G' in disk_available:
                    gb_available = float(disk_available.replace('G', ''))
                    if gb_available < 20:
                        result['checks']['disk']['status'] = 'warning'
                        result['checks']['disk']['message'] += ' (20GB+ recommended)'
                elif 'T' in disk_available:
                    result['checks']['disk']['message'] += ' (excellent)'
            except (ValueError, TypeError):
                pass
        else:
            result['checks']['disk'] = {
                'status': 'fail',
                'message': f"Could not check disk space: {resources.get('disk_error', 'Unknown error')}"
            }
        
        # Determine overall status
        if all(check.get('status') == 'pass' for check in result['checks'].values()):
            result['status'] = 'pass'
            result['message'] = 'Host resources adequate'
        elif any(check.get('status') == 'fail' for check in result['checks'].values()):
            result['status'] = 'fail'
            result['message'] = 'Insufficient host resources'
        else:
            result['status'] = 'warning'
            result['message'] = 'Host resources adequate with warnings'
        
        return result
    
    def _validate_network_ports(self) -> Dict[str, Any]:
        """Validate network port availability"""
        result = {
            'status': 'unknown',
            'checks': {},
            'info': {}
        }
        
        port_info = self.system_manager.check_network_ports()
        result['info'] = port_info
        
        # Check database ports
        if 'used_database_ports' in port_info:
            used_ports = port_info['used_database_ports']
            if used_ports:
                result['checks']['database_ports'] = {
                    'status': 'warning',
                    'message': f'{len(used_ports)} standard database ports in use',
                    'value': used_ports
                }
            else:
                result['checks']['database_ports'] = {
                    'status': 'pass',
                    'message': 'No conflicts with standard database ports'
                }
        else:
            result['checks']['database_ports'] = {
                'status': 'warning',
                'message': f"Could not check database ports: {port_info.get('port_check_error', 'Unknown error')}"
            }
        
        # Check PostgreSQL port range
        if 'used_postgresql_ports' in port_info:
            used_pg_ports = port_info['used_postgresql_ports']
            if used_pg_ports:
                result['checks']['postgresql_range'] = {
                    'status': 'warning',
                    'message': f'{len(used_pg_ports)} ports in PostgreSQL range (5432-5500) in use',
                    'value': used_pg_ports
                }
            else:
                result['checks']['postgresql_range'] = {
                    'status': 'pass',
                    'message': 'PostgreSQL port range (5432-5500) available'
                }
        else:
            result['checks']['postgresql_range'] = {
                'status': 'pass',
                'message': 'PostgreSQL port range appears available'
            }
        
        # Determine overall status
        if all(check.get('status') in ['pass', 'warning'] for check in result['checks'].values()):
            if any(check.get('status') == 'warning' for check in result['checks'].values()):
                result['status'] = 'warning'
                result['message'] = 'Network ports available with some conflicts'
            else:
                result['status'] = 'pass'
                result['message'] = 'Network ports available'
        else:
            result['status'] = 'fail'
            result['message'] = 'Network port issues detected'
        
        return result
    
    def _determine_overall_status(self) -> str:
        """Determine overall validation status"""
        checks = [
            self.validation_results.get('container_environment', {}).get('status'),
            self.validation_results.get('docker_access', {}).get('status'),
            self.validation_results.get('docker_engine', {}).get('status'),
            self.validation_results.get('docker_compose', {}).get('status'),
            self.validation_results.get('zfs_utilities', {}).get('status'),
            self.validation_results.get('zfs_pools', {}).get('status'),
            self.validation_results.get('host_resources', {}).get('status'),
            self.validation_results.get('network_ports', {}).get('status')
        ]
        
        if any(status == 'fail' for status in checks):
            return 'invalid'  # Changed from 'fail' to match UI expectations
        elif any(status == 'warning' for status in checks):
            return 'warning'
        elif all(status == 'pass' for status in checks):
            return 'valid'   # Changed from 'pass' to match UI expectations
        else:
            return 'unknown'
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get a concise validation summary"""
        if not self.validation_results:
            return {'status': 'not_validated', 'message': 'System validation not yet performed'}
        
        overall_status = self.validation_results.get('overall_status', 'unknown')
        
        summary = {
            'status': overall_status,
            'timestamp': self.validation_results.get('timestamp'),
            'components': {}
        }
        
        # Summarize each component
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
            component_data = self.validation_results.get(key, {})
            component_summary = {
                'status': component_data.get('status', 'unknown'),
                'message': component_data.get('message', 'No information available')
            }

            # For ZFS utilities, include installation availability
            if key == 'zfs_utilities':
                component_summary['details'] = {
                    'can_install': component_data.get('can_install', False),
                    'os_info': component_data.get('os_info', {})
                }

            summary['components'][name] = component_summary
        
        # Overall message
        if overall_status == 'pass':
            summary['message'] = 'All system requirements satisfied'
        elif overall_status == 'warning':
            summary['message'] = 'System functional with warnings'
        elif overall_status == 'fail':
            summary['message'] = 'System requirements not met'
        else:
            summary['message'] = 'System validation incomplete'
        
        return summary