from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import HostVM, StorageConfiguration
from .host_validator import HostValidator
import logging
import uuid
from django.utils import timezone

logger = logging.getLogger(__name__)


def _create_or_update_storage_config(storage_data):
    """Create or update storage configuration for host setup"""
    try:
        storage_type = storage_data.get('storage_type')
        config_name = storage_data.get('name', f'docker-host-storage-{timezone.now().strftime("%Y%m%d-%H%M%S")}')
        
        # Create storage configuration
        storage_config = StorageConfiguration(
            name=config_name,
            storage_type=storage_type,
            pool_type=storage_data.get('pool_type', 'single'),
            compression=storage_data.get('compression', 'lz4'),
            dedup=storage_data.get('dedup', False)
        )
        
        # Set type-specific fields
        if storage_type == 'existing_pool':
            storage_config.existing_pool_name = storage_data.get('existing_pool_name')
            if not storage_config.existing_pool_name:
                return {'success': False, 'message': 'Existing pool name is required'}
        
        elif storage_type == 'dedicated_disk':
            storage_config.dedicated_disks = storage_data.get('dedicated_disks', [])
            storage_config.pool_name = storage_data.get('pool_name')
            if not storage_config.dedicated_disks:
                return {'success': False, 'message': 'At least one disk is required'}
        
        elif storage_type == 'image_file':
            storage_config.image_file_path = storage_data.get('image_file_path')
            storage_config.image_file_size_gb = storage_data.get('image_file_size_gb')
            storage_config.sparse_file = storage_data.get('sparse_file', True)
            storage_config.pool_name = storage_data.get('pool_name')
            if not storage_config.image_file_path or not storage_config.image_file_size_gb:
                return {'success': False, 'message': 'Image file path and size are required'}
        
        elif storage_type == 'directory':
            storage_config.storage_directory = storage_data.get('storage_directory')
            if not storage_config.storage_directory:
                return {'success': False, 'message': 'Storage directory is required'}
        
        # Validate the configuration
        try:
            storage_config.clean()
        except Exception as e:
            return {'success': False, 'message': f'Configuration validation failed: {str(e)}'}
        
        # Save the configuration
        storage_config.save()
        
        # Apply the storage configuration
        application_result = storage_config.apply_configuration()
        if not application_result['success']:
            storage_config.delete()  # Clean up if application failed
            return {
                'success': False, 
                'message': f'Storage configuration application failed: {application_result["message"]}',
                'details': application_result
            }
        
        return {
            'success': True,
            'storage_config': storage_config,
            'message': f'Storage configuration "{config_name}" created and applied successfully'
        }
        
    except Exception as e:
        logger.error(f"Error creating storage configuration: {str(e)}")
        return {
            'success': False,
            'message': f'Storage configuration creation failed: {str(e)}'
        }


def _ensure_host_datasets(host_vm):
    """Ensure required datasets exist for the host"""
    try:
        if not host_vm.storage_config or not host_vm.storage_config.is_configured:
            return {'success': False, 'message': 'Host has no configured storage'}
        
        # Create parent datasets
        host_vm._ensure_stagdb_parent_datasets()
        
        return {
            'success': True,
            'message': 'Host datasets created successfully'
        }
        
    except Exception as e:
        logger.error(f"Error ensuring host datasets: {str(e)}")
        return {
            'success': False,
            'message': f'Dataset creation failed: {str(e)}'
        }


@login_required
def docker_host_setup_wizard(request):
    """Docker host setup wizard main page"""
    return render(request, 'docker_host_setup.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def docker_host_status(request):
    """Get current Docker host status and requirements"""
    try:
        # Check if Docker host already exists
        existing_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
        
        # Get system validation status
        validator = HostValidator()
        validation_summary = validator.get_validation_summary()
        
        # Get storage options instead of existing configurations
        from .storage_utils import StorageUtils
        storage_utils = StorageUtils()
        
        # Get available storage options
        storage_options = _get_host_storage_options(storage_utils)
        available_storage = storage_options.get('options', {})
        
        return Response({
            'success': True,
            'docker_host_exists': existing_host is not None,
            'host_info': {
                'id': existing_host.id if existing_host else None,
                'name': existing_host.name if existing_host else None,
                'validation_status': existing_host.validation_status if existing_host else 'not_configured',
                'storage_config': existing_host.storage_config.name if existing_host and existing_host.storage_config else None
            } if existing_host else None,
            'system_status': validation_summary,
            'storage_options': available_storage,
            'requirements_met': validation_summary.get('overall_status') in ['valid', 'warning']
        })
        
    except Exception as e:
        logger.error(f"Failed to get Docker host status: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get Docker host status'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_docker_host(request):
    """Set up Docker host with integrated storage configuration"""
    try:
        data = request.data
        
        # Extract storage configuration data
        storage_config_data = data.get('storage_config', {})
        validation_results = data.get('validation_results', {})
        
        # Create or update storage configuration
        storage_config = None
        if storage_config_data:
            storage_result = _create_or_update_storage_config(storage_config_data)
            if not storage_result['success']:
                return Response({
                    'success': False,
                    'message': f'Storage configuration failed: {storage_result["message"]}',
                    'details': storage_result.get('details', {})
                }, status=400)
            storage_config = storage_result['storage_config']
        
        # Get or create Docker host entry
        docker_host, created = HostVM.get_or_create_docker_host()
        
        # Update Docker host configuration
        docker_host.storage_config = storage_config
        
        # Set the ZFS pool name from storage configuration if available
        if storage_config and storage_config.is_configured:
            docker_host.zfs_pool = storage_config.get_pool_name()
        
        # Run validation if not already done
        if not validation_results:
            validation_results = docker_host.validate_host_system()
        else:
            # Update validation status from provided results
            docker_host.validation_status = validation_results.get('overall_status', 'pending')
            docker_host.validation_report = validation_results
            docker_host.last_validated = timezone.now()
        
        # Extract and store system information
        if 'system_info' in validation_results:
            docker_host.os_info = validation_results['system_info']
        
        if 'docker_engine' in validation_results:
            docker_info = validation_results['docker_engine'].get('info', {})
            if 'docker_version' in docker_info:
                docker_host.docker_version = docker_info['docker_version']
        
        if 'zfs_utilities' in validation_results:
            zfs_info = validation_results['zfs_utilities'].get('info', {})
            if 'zfs_version' in zfs_info:
                docker_host.zfs_version = zfs_info['zfs_version']
        
        if 'zfs_pools' in validation_results:
            pools_info = validation_results['zfs_pools'].get('info', {})
            if 'pools' in pools_info:
                docker_host.zfs_pools = pools_info['pools']
        
        if 'host_resources' in validation_results:
            docker_host.system_resources = validation_results['host_resources'].get('info', {})
        
        # Save the updated host
        docker_host.save()
        
        # Ensure required datasets are created
        dataset_result = {'success': True, 'message': 'No storage configuration provided'}
        if storage_config and storage_config.is_configured:
            dataset_result = _ensure_host_datasets(docker_host)
            if not dataset_result['success']:
                logger.warning(f"Dataset creation failed for host {docker_host.id}: {dataset_result['message']}")
        
        logger.info(f"Docker host setup completed. Host ID: {docker_host.id}, Created: {created}")
        
        return Response({
            'success': True,
            'message': 'Docker host setup completed successfully',
            'host_configuration': {
                'id': docker_host.id,
                'name': docker_host.name,
                'created': created,
                'validation_status': docker_host.validation_status,
                'storage_config': {
                    'id': storage_config.id,
                    'name': storage_config.name,
                    'type': storage_config.get_storage_type_display(),
                    'pool_name': storage_config.get_pool_name()
                } if storage_config else None,
                'dataset_creation': dataset_result,
                'can_create_databases': docker_host.can_create_databases(),
                'system_info': {
                    'docker_version': docker_host.docker_version,
                    'zfs_version': docker_host.zfs_version,
                    'os_info': docker_host.os_info
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Docker host setup failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Docker host setup failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def remove_docker_host(request):
    """Remove Docker host and clean up all associated resources"""
    try:
        force = request.data.get('force', False)
        
        # Find the Docker host
        docker_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
        if not docker_host:
            return Response({
                'success': False,
                'message': 'No active Docker host found'
            }, status=404)
        
        # Check for active databases
        active_databases = docker_host.database_set.filter(is_active=True)
        if active_databases.exists() and not force:
            return Response({
                'success': False,
                'message': f'Cannot remove Docker host: {active_databases.count()} active databases exist',
                'active_databases': [
                    {
                        'id': db.id,
                        'name': db.name,
                        'creation_type': db.creation_type
                    }
                    for db in active_databases
                ],
                'force_option_available': True
            }, status=409)
        
        cleanup_summary = {
            'databases_removed': [],
            'storage_cleanup': {'success': False, 'message': 'Not attempted'},
            'datasets_removed': [],
            'storage_config_removed': False,
            'warnings': [],
            'errors': []
        }
        
        # Force remove all databases if requested
        if force and active_databases.exists():
            from .database_manager import DatabaseManager
            db_manager = DatabaseManager(docker_host)
            
            for database in active_databases:
                try:
                    delete_result = db_manager.delete_database(database, force=True)
                    if delete_result['success']:
                        cleanup_summary['databases_removed'].append({
                            'name': database.name,
                            'id': database.id,
                            'cleanup_details': delete_result.get('cleanup_summary', {})
                        })
                    else:
                        cleanup_summary['errors'].append(f"Failed to remove database {database.name}: {delete_result['message']}")
                except Exception as e:
                    cleanup_summary['errors'].append(f"Error removing database {database.name}: {str(e)}")
        
        # Clean up storage datasets
        if docker_host.storage_config and docker_host.storage_config.is_configured:
            storage_cleanup_result = _cleanup_host_storage(docker_host)
            cleanup_summary['storage_cleanup'] = storage_cleanup_result
            cleanup_summary['datasets_removed'] = storage_cleanup_result.get('datasets_removed', [])
            if storage_cleanup_result.get('warnings'):
                cleanup_summary['warnings'].extend(storage_cleanup_result['warnings'])
        
        # Remove storage configuration
        storage_config = docker_host.storage_config
        if storage_config:
            try:
                storage_config_name = storage_config.name
                storage_config.is_active = False
                storage_config.save()
                cleanup_summary['storage_config_removed'] = True
                cleanup_summary['warnings'].append(f"Storage configuration '{storage_config_name}' deactivated")
            except Exception as e:
                cleanup_summary['errors'].append(f"Failed to remove storage configuration: {str(e)}")
        
        # Remove the Docker host
        host_name = docker_host.name
        docker_host.is_active = False
        docker_host.save()
        
        success = len(cleanup_summary['errors']) == 0
        message = f"Docker host '{host_name}' removed successfully" if success else f"Docker host '{host_name}' removed with errors"
        
        logger.info(f"Docker host removal completed: {message}")
        
        return Response({
            'success': success,
            'message': message,
            'cleanup_summary': cleanup_summary
        })
        
    except Exception as e:
        logger.error(f"Docker host removal failed: {str(e)}")
        return Response({
            'success': False,
            'message': f'Docker host removal failed: {str(e)}'
        }, status=500)


def _cleanup_host_storage(host_vm):
    """Clean up storage datasets and configuration for host removal"""
    try:
        if not host_vm.storage_config or not host_vm.storage_config.is_configured:
            return {
                'success': True,
                'message': 'No storage configuration to clean up',
                'datasets_removed': [],
                'warnings': []
            }
        
        # Use the comprehensive storage cleanup method
        from .storage_utils import StorageUtils
        storage_utils = StorageUtils()
        cleanup_result = storage_utils.cleanup_storage_configuration(host_vm.storage_config)
        
        # Extract datasets information for backward compatibility
        datasets_removed = []
        warnings = cleanup_result.get('details', {}).get('warnings', [])
        
        # If pool cleanup was successful, we can assume datasets were removed
        pool_cleanup = cleanup_result.get('details', {}).get('pool_cleanup')
        if pool_cleanup and pool_cleanup.get('success'):
            pool_name = host_vm.storage_config.get_pool_name()
            datasets_removed = [f"{pool_name}/stagdb"]  # Main dataset that would have been removed
        
        # Add any errors as warnings for backward compatibility
        errors = cleanup_result.get('details', {}).get('errors', [])
        warnings.extend(errors)
        
        return {
            'success': cleanup_result['success'],
            'message': cleanup_result['message'],
            'datasets_removed': datasets_removed,
            'warnings': warnings,
            'storage_cleanup_details': cleanup_result.get('details', {})
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up host storage: {str(e)}")
        return {
            'success': False,
            'message': f'Storage cleanup failed: {str(e)}',
            'datasets_removed': [],
            'warnings': []
        }


def _get_host_storage_options(storage_utils):
    """Get available storage options for host setup"""
    try:
        # Get available disks
        available_disks = storage_utils.get_available_disks()
        
        # Get available space
        space_info = storage_utils.get_available_space()
        
        # Get existing ZFS pools
        success, stdout, stderr = storage_utils.execute_host_command("zpool list -H -o name,health,size,free")
        existing_pools = []
        if success:
            for line in stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        existing_pools.append({
                            'name': parts[0],
                            'health': parts[1],
                            'size': parts[2],
                            'free': parts[3]
                        })
        
        # Calculate max image file size (80% of available space)
        max_image_size_gb = 0
        if 'available' in space_info:
            available_gb = storage_utils._parse_size_to_gb(space_info['available'])
            max_image_size_gb = int(available_gb * 0.8)
        
        return {
            'success': True,
            'options': {
                'storage_types': StorageConfiguration.STORAGE_TYPES,
                'pool_types': StorageConfiguration.POOL_TYPES,
                'available_disks': available_disks,
                'existing_pools': existing_pools,
                'system_space': space_info,
                'max_image_size_gb': max_image_size_gb,
                'recommended_settings': {
                    'compression': 'lz4',
                    'dedup': False,
                    'min_image_size_gb': 10,
                    'min_directory_space_gb': 20
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get storage options: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'options': {}
        }


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def docker_host_validation_status(request):
    """Get detailed validation status for Docker host"""
    try:
        validator = HostValidator()
        validation_results = validator.validate_all()
        
        # Format validation results for the wizard
        formatted_results = {}
        
        component_mapping = {
            'container_environment': 'Container Environment',
            'docker_engine': 'Docker Engine',
            'zfs_utilities': 'ZFS Utilities',
            'zfs_pools': 'ZFS Pools',
            'host_resources': 'Host Resources',
            'network_ports': 'Network Ports'
        }
        
        for key, name in component_mapping.items():
            component_data = validation_results.get(key, {})
            formatted_results[key] = {
                'status': component_data.get('status', 'unknown'),
                'message': component_data.get('message', 'No information available'),
                'details': component_data.get('info', {})
            }
        
        overall_status = validation_results.get('overall_status', 'unknown')
        
        return Response({
            'success': True,
            'overall_status': overall_status,
            'validation_results': formatted_results,
            'can_proceed': overall_status in ['valid', 'warning'],
            'timestamp': validator.validation_timestamp.isoformat() if validator.validation_timestamp else None
        })
        
    except Exception as e:
        logger.error(f"Validation status check failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get validation status'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_docker_host_validation(request):
    """Run comprehensive Docker host validation"""
    try:
        force_revalidation = request.data.get('force_revalidation', True)
        
        logger.info(f"Starting Docker host validation (force: {force_revalidation})")
        
        validator = HostValidator()
        validation_results = validator.validate_all()
        
        logger.info(f"Validation completed with status: {validation_results.get('overall_status')}")
        
        # Store validation results in Docker host if it exists
        docker_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
        if docker_host:
            docker_host.validation_status = validation_results.get('overall_status', 'pending')
            docker_host.validation_report = validation_results
            docker_host.last_validated = validator.validation_timestamp
            docker_host.save()
        
        # Format results for the wizard
        formatted_results = {}
        component_mapping = {
            'container_environment': 'Container Environment',
            'docker_engine': 'Docker Engine', 
            'zfs_utilities': 'ZFS Utilities',
            'zfs_pools': 'ZFS Pools',
            'host_resources': 'Host Resources',
            'network_ports': 'Network Ports'
        }
        
        for key, name in component_mapping.items():
            component_data = validation_results.get(key, {})
            formatted_results[key] = {
                'status': component_data.get('status', 'unknown'),
                'message': component_data.get('message', 'No information available'),
                'details': component_data.get('info', {})
            }
        
        return Response({
            'success': True,
            'validation_results': formatted_results,
            'overall_status': validation_results.get('overall_status', 'unknown'),
            'summary': validator.get_validation_summary(),
            'can_proceed': validation_results.get('overall_status') in ['valid', 'warning']
        })
        
    except Exception as e:
        logger.error(f"Docker host validation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Docker host validation failed'
        }, status=500)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_docker_host(request):
    """Remove Docker host configuration"""
    try:
        docker_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
        
        if not docker_host:
            return Response({
                'success': False,
                'message': 'No Docker host configuration found'
            }, status=404)
        
        # Check if host can be removed (no databases)
        if not docker_host.can_be_removed():
            blockers = docker_host.get_removal_blockers()
            return Response({
                'success': False,
                'message': 'Docker host cannot be removed',
                'blockers': blockers
            }, status=400)
        
        # Soft delete
        docker_host.is_active = False
        docker_host.save()
        
        logger.info(f"Docker host removed: {docker_host.name} (ID: {docker_host.id})")
        
        return Response({
            'success': True,
            'message': 'Docker host configuration removed successfully'
        })
        
    except Exception as e:
        logger.error(f"Failed to remove Docker host: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to remove Docker host'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def docker_host_summary(request):
    """Get Docker host configuration summary"""
    try:
        docker_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
        
        if not docker_host:
            return Response({
                'success': False,
                'message': 'No Docker host configuration found'
            }, status=404)
        
        summary = {
            'id': docker_host.id,
            'name': docker_host.name,
            'status': docker_host.validation_status,
            'last_validated': docker_host.last_validated.isoformat() if docker_host.last_validated else None,
            'can_create_databases': docker_host.can_create_databases(),
            'database_count': docker_host.get_database_count(),
            'storage_config': {
                'id': docker_host.storage_config.id,
                'name': docker_host.storage_config.name,
                'type': docker_host.storage_config.get_storage_type_display(),
                'pool_name': docker_host.storage_config.get_pool_name()
            } if docker_host.storage_config else None,
            'system_info': {
                'docker_version': docker_host.docker_version,
                'zfs_version': docker_host.zfs_version,
                'os_info': docker_host.os_info,
                'system_resources': docker_host.system_resources
            },
            'validation_summary': docker_host.get_validation_summary()
        }
        
        return Response({
            'success': True,
            'docker_host': summary
        })
        
    except Exception as e:
        logger.error(f"Failed to get Docker host summary: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get Docker host summary'
        }, status=500)