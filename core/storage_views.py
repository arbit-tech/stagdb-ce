from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from .models import StorageConfiguration
from .storage_utils import StorageUtils
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_options(request):
    """Get available storage configuration options"""
    try:
        storage_utils = StorageUtils()
        
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
        
        return Response({
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
        })
        
    except Exception as e:
        logger.error(f"Failed to get storage options: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get storage options'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_configurations(request):
    """Get all storage configurations"""
    try:
        configs = StorageConfiguration.objects.filter(is_active=True)
        
        config_data = []
        for config in configs:
            config_info = config.get_storage_info()
            config_info['id'] = config.id
            config_info['created_at'] = config.created_at.isoformat()
            config_data.append(config_info)
        
        return Response({
            'success': True,
            'configurations': config_data
        })
        
    except Exception as e:
        logger.error(f"Failed to get storage configurations: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get storage configurations'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_storage_configuration(request):
    """Create a new storage configuration"""
    try:
        data = request.data
        
        # Basic validation
        required_fields = ['name', 'storage_type']
        for field in required_fields:
            if field not in data:
                return Response({
                    'success': False,
                    'message': f'Required field missing: {field}'
                }, status=400)
        
        # Create storage configuration
        config = StorageConfiguration(
            name=data['name'],
            storage_type=data['storage_type']
        )
        
        # Set type-specific fields
        if data['storage_type'] == 'existing_pool':
            config.existing_pool_name = data.get('existing_pool_name', '')
        
        elif data['storage_type'] in ['dedicated_disk', 'multi_disk']:
            config.dedicated_disks = data.get('dedicated_disks', [])
            config.pool_type = data.get('pool_type', 'single')
        
        elif data['storage_type'] == 'image_file':
            config.image_file_path = data.get('image_file_path', '')
            config.image_file_size_gb = data.get('image_file_size_gb', 0)
            config.sparse_file = data.get('sparse_file', True)
        
        elif data['storage_type'] == 'directory':
            config.storage_directory = data.get('storage_directory', '')
        
        elif data['storage_type'] == 'hybrid':
            config.cache_disks = data.get('cache_disks', [])
            config.data_disks = data.get('data_disks', [])
            config.pool_type = data.get('pool_type', 'single')
        
        # Set optional fields
        config.pool_name = data.get('pool_name', '')
        config.compression = data.get('compression', 'lz4')
        config.dedup = data.get('dedup', False)
        
        # Validate configuration
        try:
            config.clean()
        except ValidationError as e:
            return Response({
                'success': False,
                'message': str(e),
                'validation_errors': e.message_dict if hasattr(e, 'message_dict') else [str(e)]
            }, status=400)
        
        # Test configuration
        validation_result = config.validate_configuration()
        if not validation_result.get('valid'):
            return Response({
                'success': False,
                'message': 'Configuration validation failed',
                'validation_result': validation_result
            }, status=400)
        
        # Save configuration
        config.save()
        
        # Apply configuration immediately
        apply_result = config.apply_configuration()
        
        if apply_result.get('success'):
            return Response({
                'success': True,
                'message': f'Storage configuration "{config.name}" created and applied successfully',
                'configuration': {
                    'id': config.id,
                    'name': config.name,
                    'storage_type': config.storage_type,
                    'validation_result': validation_result,
                    'apply_result': apply_result,
                    'is_configured': config.is_configured
                }
            })
        else:
            return Response({
                'success': False,
                'message': f'Configuration created but failed to apply: {apply_result.get("message")}',
                'configuration': {
                    'id': config.id,
                    'name': config.name,
                    'storage_type': config.storage_type,
                    'validation_result': validation_result,
                    'apply_result': apply_result,
                    'configuration_error': config.configuration_error
                }
            }, status=500)
        
    except Exception as e:
        logger.error(f"Failed to create storage configuration: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to create storage configuration'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def apply_storage_configuration(request, config_id):
    """Apply a storage configuration"""
    try:
        config = get_object_or_404(StorageConfiguration, id=config_id, is_active=True)
        
        # Check if already configured
        if config.is_configured:
            return Response({
                'success': False,
                'message': f'Configuration "{config.name}" is already applied'
            }, status=400)
        
        # Validate configuration before applying
        validation_result = config.validate_configuration()
        if not validation_result.get('valid'):
            return Response({
                'success': False,
                'message': 'Configuration validation failed',
                'validation_result': validation_result
            }, status=400)
        
        # Apply configuration
        apply_result = config.apply_configuration()
        
        if apply_result.get('success'):
            return Response({
                'success': True,
                'message': f'Storage configuration "{config.name}" applied successfully',
                'configuration': config.get_storage_info(),
                'apply_result': apply_result
            })
        else:
            return Response({
                'success': False,
                'message': f'Failed to apply configuration: {apply_result.get("message")}',
                'apply_result': apply_result
            }, status=500)
        
    except Exception as e:
        logger.error(f"Failed to apply storage configuration: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to apply storage configuration'
        }, status=500)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_storage_configuration(request, config_id):
    """Delete a storage configuration"""
    try:
        config = get_object_or_404(StorageConfiguration, id=config_id, is_active=True)
        
        # Check if configuration is in use
        # TODO: Add check for databases using this storage configuration
        
        config.is_active = False
        config.save()
        
        return Response({
            'success': True,
            'message': f'Storage configuration "{config.name}" deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Failed to delete storage configuration: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to delete storage configuration'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_storage_configuration(request):
    """Validate a storage configuration without saving it"""
    try:
        data = request.data
        storage_utils = StorageUtils()
        
        storage_type = data.get('storage_type')
        if not storage_type:
            return Response({
                'success': False,
                'message': 'Storage type is required'
            }, status=400)
        
        validation_result = {'valid': False}
        
        if storage_type == 'existing_pool':
            pool_name = data.get('existing_pool_name')
            if pool_name:
                validation_result = storage_utils.validate_existing_pool(pool_name)
        
        elif storage_type in ['dedicated_disk', 'multi_disk']:
            disk_paths = data.get('dedicated_disks', [])
            pool_type = data.get('pool_type', 'single')
            
            if storage_type == 'multi_disk':
                validation_result = storage_utils.validate_multi_disk_config(disk_paths, pool_type)
            else:
                validation_result = storage_utils.validate_dedicated_disks(disk_paths)
        
        elif storage_type == 'image_file':
            image_path = data.get('image_file_path')
            size_gb = data.get('image_file_size_gb', 0)
            validation_result = storage_utils.validate_image_file_config(image_path, size_gb)
        
        elif storage_type == 'directory':
            directory = data.get('storage_directory')
            validation_result = storage_utils.validate_directory_storage(directory)
        
        elif storage_type == 'hybrid':
            cache_disks = data.get('cache_disks', [])
            data_disks = data.get('data_disks', [])
            pool_type = data.get('pool_type', 'single')
            validation_result = storage_utils.validate_hybrid_config(cache_disks, data_disks, pool_type)
        
        return Response({
            'success': True,
            'validation_result': validation_result
        })
        
    except Exception as e:
        logger.error(f"Failed to validate storage configuration: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to validate storage configuration'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def disk_info(request, disk_name):
    """Get detailed information about a specific disk"""
    try:
        disk_path = f"/dev/{disk_name}"
        storage_utils = StorageUtils()
        
        disk_info = storage_utils.get_disk_info(disk_path)
        
        return Response({
            'success': True,
            'disk_info': disk_info
        })
        
    except Exception as e:
        logger.error(f"Failed to get disk info: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get disk information'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def storage_recommendations(request):
    """Get storage configuration recommendations based on system resources"""
    try:
        storage_utils = StorageUtils()
        
        # Get system information
        available_disks = storage_utils.get_available_disks()
        space_info = storage_utils.get_available_space()
        
        # Calculate available space in GB
        available_gb = 0
        if 'available' in space_info:
            available_gb = storage_utils._parse_size_to_gb(space_info['available'])
        
        recommendations = []
        
        # Count available disks
        usable_disks = [d for d in available_disks if d.get('available')]
        
        # Recommendation 1: Use existing pools if available
        success, stdout, stderr = storage_utils.execute_host_command("zpool list -H -o name,health")
        existing_pools = []
        if success:
            for line in stdout.strip().split('\n'):
                if line:
                    parts = line.split('\t')
                    if len(parts) >= 2 and parts[1] == 'ONLINE':
                        existing_pools.append(parts[0])
        
        if existing_pools:
            recommendations.append({
                'type': 'existing_pool',
                'title': 'Use Existing ZFS Pool (Recommended)',
                'description': f'Use existing healthy ZFS pool: {", ".join(existing_pools)}',
                'pros': ['Quick setup', 'Already tested', 'No data loss risk'],
                'cons': ['Shared with other data'],
                'difficulty': 'Easy',
                'config': {
                    'storage_type': 'existing_pool',
                    'existing_pool_name': existing_pools[0]
                }
            })
        
        # Recommendation 2: Dedicated disk if available
        if len(usable_disks) >= 1:
            recommendations.append({
                'type': 'dedicated_disk',
                'title': 'Dedicated Disk Storage',
                'description': f'Use {len(usable_disks)} available disk(s) for dedicated ZFS pool',
                'pros': ['High performance', 'Isolated storage', 'Full disk utilization'],
                'cons': ['Requires unused disk', 'Cannot be undone easily'],
                'difficulty': 'Medium',
                'config': {
                    'storage_type': 'dedicated_disk',
                    'dedicated_disks': [d['path'] for d in usable_disks[:1]],
                    'pool_type': 'single'
                }
            })
        
        # Recommendation 3: Multi-disk if 2+ disks
        if len(usable_disks) >= 2:
            recommendations.append({
                'type': 'multi_disk',
                'title': 'Multi-Disk ZFS Pool (High Availability)',
                'description': f'Use {len(usable_disks)} disks in mirror/RAID configuration',
                'pros': ['Data redundancy', 'High performance', 'Fault tolerance'],
                'cons': ['Requires multiple disks', 'Complex setup'],
                'difficulty': 'Advanced',
                'config': {
                    'storage_type': 'multi_disk',
                    'dedicated_disks': [d['path'] for d in usable_disks[:2]],
                    'pool_type': 'mirror' if len(usable_disks) == 2 else 'raidz1'
                }
            })
        
        # Recommendation 4: Image file storage
        if available_gb >= 20:
            recommended_size = min(int(available_gb * 0.3), 100)  # 30% of space or 100GB max
            recommendations.append({
                'type': 'image_file',
                'title': 'Image File Storage',
                'description': f'Create {recommended_size}GB ZFS pool using an image file',
                'pros': ['Flexible sizing', 'Can resize later', 'Safe to test'],
                'cons': ['Lower performance', 'Uses filesystem space'],
                'difficulty': 'Easy',
                'config': {
                    'storage_type': 'image_file',
                    'image_file_path': '/opt/stagdb/storage.img',
                    'image_file_size_gb': recommended_size,
                    'sparse_file': True
                }
            })
        
        # Recommendation 5: Directory storage (development)
        recommendations.append({
            'type': 'directory',
            'title': 'Directory Storage (Development Only)',
            'description': 'Simple directory-based storage without ZFS features',
            'pros': ['Simplest setup', 'No ZFS required', 'Good for testing'],
            'cons': ['No snapshots', 'No compression', 'Development only'],
            'difficulty': 'Easy',
            'config': {
                'storage_type': 'directory',
                'storage_directory': '/opt/stagdb/data'
            }
        })
        
        return Response({
            'success': True,
            'system_info': {
                'available_disks': len(usable_disks),
                'available_space_gb': available_gb,
                'existing_pools': len(existing_pools)
            },
            'recommendations': recommendations
        })
        
    except Exception as e:
        logger.error(f"Failed to get storage recommendations: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get storage recommendations'
        }, status=500)