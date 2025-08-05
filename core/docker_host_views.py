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
        
        # Get storage configurations
        storage_configs = StorageConfiguration.objects.filter(is_active=True)
        available_storage = []
        for config in storage_configs:
            available_storage.append({
                'id': config.id,
                'name': config.name,
                'type': config.get_storage_type_display(),
                'is_configured': config.is_configured,
                'pool_name': config.get_pool_name() if config.is_configured else None
            })
        
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
            'available_storage': available_storage,
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
    """Set up Docker host with storage configuration"""
    try:
        data = request.data
        storage_config_id = data.get('storage_config_id')
        validation_results = data.get('validation_results', {})
        
        # Validate storage configuration
        storage_config = None
        if storage_config_id:
            try:
                storage_config = StorageConfiguration.objects.get(
                    id=storage_config_id, 
                    is_active=True,
                    is_configured=True
                )
            except StorageConfiguration.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Invalid or unconfigured storage configuration'
                }, status=400)
        
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