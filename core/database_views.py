import logging
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from .models import HostVM, Database, DatabaseBranch
from .database_manager import DatabaseManager

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_databases(request):
    """List all databases for the user"""
    try:
        # Get optional host filter
        host_id = request.GET.get('host_id')
        
        if host_id:
            host = get_object_or_404(HostVM, id=host_id, is_active=True)
            databases = Database.objects.filter(host_vm=host, is_active=True).order_by('-created_at')
        else:
            databases = Database.objects.filter(is_active=True).order_by('-created_at')
        
        database_list = []
        for db in databases:
            database_list.append({
                'id': db.id,
                'name': db.name,
                'host': {
                    'id': db.host_vm.id,
                    'name': db.host_vm.name,
                    'ip_address': db.host_vm.ip_address
                },
                'version': db.db_version,
                'port': db.port,
                'container_status': db.container_status,
                'health_status': db.health_status,
                'description': db.description,
                'created_at': db.created_at.isoformat(),
                'is_running': db.is_container_running()
            })
        
        return Response({
            'success': True,
            'databases': database_list,
            'count': len(database_list)
        })
        
    except Exception as e:
        logger.error(f"Error listing databases: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to list databases: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_database(request):
    """Create a new PostgreSQL database"""
    try:
        # Extract parameters
        name = request.data.get('name', '').strip()
        host_id = request.data.get('host_id')
        pg_version = request.data.get('db_version', '15')
        description = request.data.get('description', '').strip()
        
        # Validate required parameters
        if not name:
            return Response({
                'success': False,
                'message': 'Database name is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not host_id:
            return Response({
                'success': False,
                'message': 'Host ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get and validate host
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        
        # Check if host can create databases
        if not host.can_create_databases():
            return Response({
                'success': False,
                'message': f'Host validation failed. Status: {host.validation_status}. Run validation first.',
                'validation_summary': host.get_validation_summary()
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create database manager and create database
        db_manager = DatabaseManager(host)
        result = db_manager.create_database(
            name=name,
            pg_version=pg_version,
            description=description
        )
        
        if result['success']:
            logger.info(f"Database '{name}' created successfully by user")
            return Response(result, status=status.HTTP_201_CREATED)
        else:
            logger.warning(f"Database creation failed: {result['message']}")
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Database creation error: {str(e)}")
        return Response({
            'success': False,
            'message': f'Database creation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_detail(request, database_id):
    """Get detailed database information"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        # Get current status
        db_manager = DatabaseManager(database.host_vm)
        status_info = db_manager.get_database_status(database)
        connection_info = database.get_connection_info()
        
        # Get branches
        branches = DatabaseBranch.objects.filter(database=database).order_by('-created_at')
        branch_list = [
            {
                'id': branch.id,
                'name': branch.name,
                'snapshot_name': branch.snapshot_name,
                'is_active': branch.is_active,
                'created_at': branch.created_at.isoformat()
            }
            for branch in branches
        ]
        
        database_info = {
            'id': database.id,
            'name': database.name,
            'description': database.description,
            'host': {
                'id': database.host_vm.id,
                'name': database.host_vm.name,
                'ip_address': database.host_vm.ip_address
            },
            'version': database.db_version,
            'port': database.port,
            'container_name': database.container_name,
            'container_id': database.container_id,
            'zfs_dataset': database.zfs_dataset,
            'container_status': database.container_status,
            'health_status': database.health_status,
            'last_health_check': database.last_health_check.isoformat() if database.last_health_check else None,
            'storage_used_mb': database.storage_used_mb,
            'storage_quota_gb': database.storage_quota_gb,
            'tags': database.tags,
            'created_at': database.created_at.isoformat(),
            'updated_at': database.updated_at.isoformat(),
            'is_running': database.is_container_running(),
            'connection_info': connection_info,
            'status_info': status_info,
            'branches': branch_list
        }
        
        return Response({
            'success': True,
            'database': database_info
        })
        
    except Exception as e:
        logger.error(f"Error getting database details: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get database details: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_database(request, database_id):
    """Delete database and cleanup resources"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        db_name = database.name
        
        # Create database manager and delete database
        db_manager = DatabaseManager(database.host_vm)
        result = db_manager.delete_database(database)
        
        if result['success']:
            logger.info(f"Database '{db_name}' deleted successfully")
            return Response(result)
        else:
            logger.warning(f"Database deletion had issues: {result['message']}")
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        logger.error(f"Database deletion error: {str(e)}")
        return Response({
            'success': False,
            'message': f'Database deletion failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_database(request, database_id):
    """Start stopped database container"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        db_manager = DatabaseManager(database.host_vm)
        result = db_manager.start_database(database)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error starting database: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to start database: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def stop_database(request, database_id):
    """Stop running database container"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        db_manager = DatabaseManager(database.host_vm)
        result = db_manager.stop_database(database)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error stopping database: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to stop database: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def restart_database(request, database_id):
    """Restart database container"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        db_manager = DatabaseManager(database.host_vm)
        result = db_manager.restart_database(database)
        
        return Response(result)
        
    except Exception as e:
        logger.error(f"Error restarting database: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to restart database: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_status(request, database_id):
    """Get comprehensive database status"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        db_manager = DatabaseManager(database.host_vm)
        status_info = db_manager.get_database_status(database)
        
        return Response({
            'success': True,
            'status': status_info
        })
        
    except Exception as e:
        logger.error(f"Error getting database status: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get database status: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_connection_info(request, database_id):
    """Get database connection parameters"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        connection_info = database.get_connection_info()
        
        return Response({
            'success': True,
            'connection_info': connection_info
        })
        
    except Exception as e:
        logger.error(f"Error getting connection info: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get connection info: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_logs(request, database_id):
    """Get database container logs"""
    try:
        database = get_object_or_404(Database, id=database_id, is_active=True)
        
        # Get optional lines parameter
        lines = int(request.GET.get('lines', 100))
        lines = max(1, min(lines, 1000))  # Limit between 1 and 1000
        
        db_manager = DatabaseManager(database.host_vm)
        logs = db_manager.container_utils.get_container_logs(database.container_name, lines)
        
        return Response({
            'success': True,
            'logs': logs,
            'lines': lines,
            'container_name': database.container_name
        })
        
    except Exception as e:
        logger.error(f"Error getting database logs: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get database logs: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_postgres_versions(request):
    """List supported PostgreSQL versions"""
    try:
        versions = DatabaseManager.get_supported_versions()
        default_version = DatabaseManager.get_default_version()
        
        version_list = []
        for version in versions:
            version_info = {
                'version': version,
                'display_name': f'PostgreSQL {version}',
                'is_default': version == default_version,
                'image': f'postgres:{version}-alpine'
            }
            
            # Add version-specific info
            if version == '16':
                version_info['description'] = 'Latest stable release'
            elif version == '15':
                version_info['description'] = 'LTS - Recommended for production'
            elif version in ['14', '13', '12']:
                version_info['description'] = 'LTS - Long-term support'
            elif version == '11':
                version_info['description'] = 'Legacy - End of life soon'
            
            version_list.append(version_info)
        
        return Response({
            'success': True,
            'versions': version_list,
            'default_version': default_version
        })
        
    except Exception as e:
        logger.error(f"Error getting PostgreSQL versions: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get PostgreSQL versions: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_database_name(request):
    """Validate database name for creation"""
    try:
        name = request.data.get('name', '').strip()
        host_id = request.data.get('host_id')
        
        if not name:
            return Response({
                'valid': False,
                'message': 'Database name is required'
            })
        
        if not host_id:
            return Response({
                'valid': False,
                'message': 'Host ID is required'
            })
        
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        db_manager = DatabaseManager(host)
        
        is_valid, message = db_manager.validate_database_name(name)
        
        return Response({
            'valid': is_valid,
            'message': message,
            'sanitized_name': name.lower() if is_valid else None
        })
        
    except Exception as e:
        logger.error(f"Error validating database name: {str(e)}")
        return Response({
            'valid': False,
            'message': f'Validation error: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_image_availability(request):
    """Check if PostgreSQL Docker image is available"""
    try:
        host_id = request.data.get('host_id')
        image = request.data.get('image')
        
        if not host_id or not image:
            return Response({
                'success': False,
                'message': 'Host ID and image name are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        db_manager = DatabaseManager(host)
        
        availability = db_manager.container_utils.check_image_availability(image)
        
        return Response({
            'success': True,
            'image': image,
            'availability': availability
        })
        
    except Exception as e:
        logger.error(f"Error checking image availability: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to check image availability: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def pull_postgres_image(request):
    """Pull PostgreSQL Docker image"""
    try:
        host_id = request.data.get('host_id')
        image = request.data.get('image')
        
        if not host_id or not image:
            return Response({
                'success': False,
                'message': 'Host ID and image name are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        db_manager = DatabaseManager(host)
        
        pull_result = db_manager.container_utils.pull_image(image)
        
        if pull_result['success']:
            return Response({
                'success': True,
                'message': pull_result['message'],
                'was_cached': pull_result.get('was_cached', False)
            })
        else:
            return Response({
                'success': False,
                'message': pull_result['message']
            }, status=status.HTTP_400_BAD_REQUEST)
        
    except Exception as e:
        logger.error(f"Error pulling image: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to pull image: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_port_availability(request):
    """Check port availability in the database port range"""
    try:
        host_id = request.GET.get('host_id')
        
        if not host_id:
            return Response({
                'success': False,
                'message': 'Host ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        db_manager = DatabaseManager(host)
        
        # Get port range
        start_port = db_manager.PORT_RANGE_START
        end_port = db_manager.PORT_RANGE_END
        
        # Check used ports
        used_ports = db_manager.container_utils.get_used_ports_in_range(start_port, end_port)
        
        # Get database ports from our records
        db_ports = list(Database.objects.filter(host_vm=host, is_active=True).values_list('port', flat=True))
        
        # Find next available port
        next_available = db_manager._allocate_port()
        
        return Response({
            'success': True,
            'port_range': {
                'start': start_port,
                'end': end_port
            },
            'used_ports': {
                'system': sorted(used_ports),
                'database_records': sorted(db_ports),
                'all_used': sorted(list(set(used_ports + db_ports)))
            },
            'next_available_port': next_available,
            'total_available': (end_port - start_port + 1) - len(set(used_ports + db_ports))
        })
        
    except Exception as e:
        logger.error(f"Error checking port availability: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to check port availability: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)