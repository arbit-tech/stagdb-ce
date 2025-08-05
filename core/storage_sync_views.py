"""
API views for storage configuration synchronization and monitoring
"""

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .storage_monitor import StorageConfigurationSyncManager, StorageConfigurationMonitor
from .models import StorageConfiguration
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_sync_status(request):
    """Get overall storage synchronization status"""
    try:
        sync_manager = StorageConfigurationSyncManager()
        status_summary = sync_manager.get_sync_status_summary()
        
        return Response({
            'success': True,
            'status': status_summary
        })
        
    except Exception as e:
        logger.error(f"Failed to get storage sync status: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get storage sync status'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_storage_health_check(request):
    """Run storage health monitoring"""
    try:
        monitor = StorageConfigurationMonitor()
        results = monitor.monitor_storage_health()
        
        return Response({
            'success': True,
            'message': 'Storage health check completed',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Storage health check failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Storage health check failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_reality_reconciliation(request):
    """Run reality reconciliation to sync with actual infrastructure"""
    try:
        monitor = StorageConfigurationMonitor()
        results = monitor.reconcile_with_reality()
        
        return Response({
            'success': True,
            'message': 'Reality reconciliation completed',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Reality reconciliation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Reality reconciliation failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_drift_detection(request):
    """Detect configuration drift"""
    try:
        monitor = StorageConfigurationMonitor()
        results = monitor.detect_configuration_drift()
        
        return Response({
            'success': True,
            'message': 'Drift detection completed',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Drift detection failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Drift detection failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_auto_remediation(request):
    """Run automatic remediation for storage issues"""
    try:
        monitor = StorageConfigurationMonitor()
        results = monitor.auto_remediate_issues()
        
        return Response({
            'success': True,
            'message': 'Auto remediation completed',
            'results': results,
            'warning': 'Auto remediation can make changes to your storage infrastructure. Review results carefully.'
        })
        
    except Exception as e:
        logger.error(f"Auto remediation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Auto remediation failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def run_full_sync(request):
    """Run complete storage synchronization cycle"""
    try:
        sync_manager = StorageConfigurationSyncManager()
        results = sync_manager.run_full_sync_cycle()
        
        return Response({
            'success': True,
            'message': 'Full storage synchronization completed',
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Full storage sync failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Full storage sync failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_storage_before_operation(request):
    """Validate storage configuration before a critical operation"""
    try:
        config_id = request.data.get('config_id')
        operation = request.data.get('operation')
        
        if not config_id or not operation:
            return Response({
                'success': False,
                'message': 'Both config_id and operation are required'
            }, status=400)
        
        monitor = StorageConfigurationMonitor()
        validation_result = monitor.validate_before_operations(config_id, operation)
        
        return Response({
            'success': True,
            'message': 'Pre-operation validation completed',
            'validation_result': validation_result
        })
        
    except Exception as e:
        logger.error(f"Pre-operation validation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Pre-operation validation failed'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_storage_health_details(request, config_id):
    """Get detailed health information for a specific storage configuration"""
    try:
        config = StorageConfiguration.objects.get(id=config_id, is_active=True)
        
        monitor = StorageConfigurationMonitor()
        health_status = monitor._check_configuration_health(config)
        
        # Get additional details
        details = {
            'config_name': config.name,
            'config_type': config.get_storage_type_display(),
            'is_configured': config.is_configured,
            'pool_name': config.get_pool_name() if config.is_configured else None,
            'health_status': health_status,
            'last_health_check': getattr(config, 'last_health_check', None),
            'last_reconciliation': getattr(config, 'last_reconciliation', None),
            'sync_status': getattr(config, 'sync_status', 'unknown'),
            'configuration_error': config.configuration_error
        }
        
        return Response({
            'success': True,
            'storage_health': details
        })
        
    except StorageConfiguration.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Storage configuration not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Failed to get storage health details: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get storage health details'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_orphaned_pools(request):
    """List ZFS pools that exist but are not configured in the system"""
    try:
        monitor = StorageConfigurationMonitor()
        actual_pools = monitor._discover_actual_pools()
        
        # Get configured pools
        configured_pools = set()
        for config in StorageConfiguration.objects.filter(is_active=True):
            if config.storage_type in ['existing_pool', 'dedicated_disk', 'multi_disk', 'image_file']:
                pool_name = config.get_pool_name()
                configured_pools.add(pool_name)
        
        # Find orphaned pools
        orphaned_pools = []
        for pool_name, pool_info in actual_pools.items():
            if pool_name not in configured_pools:
                orphaned_pools.append({
                    'name': pool_name,
                    'size': pool_info.get('size'),
                    'free': pool_info.get('free'),
                    'health': pool_info.get('health'),
                    'suggested_actions': [
                        f"Create storage configuration for existing pool '{pool_name}'",
                        f"Import pool into StagDB management"
                    ]
                })
        
        return Response({
            'success': True,
            'orphaned_pools': orphaned_pools,
            'total_orphaned': len(orphaned_pools)
        })
        
    except Exception as e:
        logger.error(f"Failed to list orphaned pools: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to list orphaned pools'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def adopt_orphaned_pool(request):
    """Create a storage configuration for an orphaned pool"""
    try:
        pool_name = request.data.get('pool_name')
        config_name = request.data.get('config_name')
        
        if not pool_name or not config_name:
            return Response({
                'success': False,
                'message': 'Both pool_name and config_name are required'
            }, status=400)
        
        # Verify pool exists and is healthy
        monitor = StorageConfigurationMonitor()
        actual_pools = monitor._discover_actual_pools()
        
        if pool_name not in actual_pools:
            return Response({
                'success': False,
                'message': f'Pool {pool_name} not found on system'
            }, status=404)
        
        pool_info = actual_pools[pool_name]
        if pool_info.get('health') != 'ONLINE':
            return Response({
                'success': False,
                'message': f'Pool {pool_name} is not healthy (status: {pool_info.get("health")})'
            }, status=400)
        
        # Create storage configuration
        config = StorageConfiguration.objects.create(
            name=config_name,
            storage_type='existing_pool',
            existing_pool_name=pool_name,
            is_configured=True,
            is_active=True
        )
        
        logger.info(f"Adopted orphaned pool {pool_name} as configuration {config_name}")
        
        return Response({
            'success': True,
            'message': f'Successfully adopted pool {pool_name}',
            'configuration': {
                'id': config.id,
                'name': config.name,
                'pool_name': pool_name,
                'pool_info': pool_info
            }
        })
        
    except Exception as e:
        logger.error(f"Failed to adopt orphaned pool: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to adopt orphaned pool'
        }, status=500)