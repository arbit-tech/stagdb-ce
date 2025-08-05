from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import HostVM, Database, DatabaseBranch
from .host_validator import HostValidator
import logging

logger = logging.getLogger(__name__)


def health_check(request):
    return JsonResponse({'status': 'healthy'})


def home(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            error = "Invalid username or password"
    
    return render(request, 'index.html', {'error': error})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            error = "Invalid username or password"
    
    return render(request, 'index.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('home')


@login_required
def dashboard(request):
    hosts = HostVM.objects.filter(is_active=True)
    databases = Database.objects.filter(is_active=True)
    
    # Check for Docker host specifically
    docker_host = HostVM.objects.filter(is_docker_host=True, is_active=True).first()
    can_create_databases = docker_host and docker_host.can_create_databases() if docker_host else False
    
    context = {
        'hosts': hosts,
        'hosts_count': hosts.count(),
        'databases_count': databases.count(),
        'active_hosts_count': hosts.filter(is_active=True).count(),
        'docker_host': docker_host,
        'can_create_databases': can_create_databases,
    }
    return render(request, 'dashboard.html', context)


@login_required
def host_detail(request, host_id):
    host = get_object_or_404(HostVM, id=host_id, is_active=True)
    databases = Database.objects.filter(host_vm=host, is_active=True)
    
    branches_count = DatabaseBranch.objects.filter(database__host_vm=host).count()
    
    context = {
        'host': host,
        'databases': databases,
        'databases_count': databases.count(),
        'active_databases_count': databases.filter(is_active=True).count(),
        'branches_count': branches_count,
    }
    return render(request, 'host_detail.html', context)


@login_required
def add_host(request):
    return render(request, 'onboarding.html')


@login_required
def storage_config(request):
    """Storage configuration page"""
    return render(request, 'storage_config.html')


@login_required
def storage_sync_dashboard(request):
    """Storage synchronization dashboard"""
    return render(request, 'storage_sync_dashboard.html')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def vm_list(request):
    vms = HostVM.objects.filter(is_active=True)
    data = [{
        'id': vm.id,
        'name': vm.name,
        'ip_address': vm.ip_address,
        'username': vm.username,
        'zfs_pool': vm.zfs_pool,
        'created_at': vm.created_at
    } for vm in vms]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def database_list(request):
    databases = Database.objects.filter(is_active=True)
    data = [{
        'id': db.id,
        'name': db.name,
        'host_vm': db.host_vm.name,
        'db_type': db.db_type,
        'db_version': db.db_version,
        'port': db.port,
        'created_at': db.created_at
    } for db in databases]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_docker_host(request):
    """Validate Docker host system from container"""
    try:
        force_revalidation = request.data.get('force_revalidation', True)
        
        logger.info(f"Starting Docker host validation (force: {force_revalidation})")
        
        validator = HostValidator()
        validation_results = validator.validate_all()
        
        logger.info(f"Validation completed with status: {validation_results.get('overall_status')}")
        
        return Response({
            'success': True,
            'validation_results': validation_results,
            'summary': validator.get_validation_summary()
        })
        
    except Exception as e:
        logger.error(f"Docker host validation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'System validation failed'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def docker_host_status(request):
    """Get Docker host validation status"""
    try:
        validator = HostValidator()
        summary = validator.get_validation_summary()
        
        return Response({
            'success': True,
            'summary': summary
        })
        
    except Exception as e:
        logger.error(f"Failed to get Docker host status: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to get system status'
        }, status=500)


@api_view(['GET'])
def system_requirements(request):
    """Get system requirements information"""
    requirements = {
        'required_components': {
            'docker': {
                'name': 'Docker Engine',
                'min_version': '20.10',
                'description': 'Container runtime for database deployment',
                'installation_guide': {
                    'ubuntu': 'sudo apt-get update && sudo apt-get install docker.io',
                    'centos': 'sudo yum install docker',
                    'generic': 'See https://docs.docker.com/engine/install/'
                }
            },
            'docker_compose': {
                'name': 'Docker Compose',
                'min_version': '2.0 (or 1.25+)',
                'description': 'Container orchestration tool',
                'installation_guide': {
                    'ubuntu': 'Docker Compose v2 included with Docker Desktop',
                    'centos': 'Docker Compose v2 included with Docker Desktop',
                    'generic': 'See https://docs.docker.com/compose/install/'
                }
            },
            'zfs': {
                'name': 'ZFS Utilities',
                'min_version': '0.8+',
                'description': 'Filesystem for instant database branching',
                'installation_guide': {
                    'ubuntu': 'sudo apt-get install zfsutils-linux',
                    'centos': 'sudo yum install zfs',
                    'generic': 'See https://openzfs.github.io/openzfs-docs/Getting%20Started/'
                }
            }
        },
        'system_requirements': {
            'min_memory_gb': 4,
            'min_disk_gb': 20,
            'min_cpu_cores': 2,
            'required_ports': '5432-5500 range for PostgreSQL containers'
        },
        'container_requirements': {
            'docker_socket': '/var/run/docker.sock must be mounted',
            'privileged_mode': 'Container must run with privileged: true',
            'host_pid': 'Container must run with pid: host for host access',
            'host_mounts': 'Host /proc and /sys should be mounted read-only'
        }
    }
    
    return Response({
        'success': True,
        'requirements': requirements
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_docker_host(request):
    """Initialize Docker host entry and run validation"""
    try:
        # Get or create docker-host HostVM entry
        docker_host, created = HostVM.get_or_create_docker_host()
        
        logger.info(f"Docker host entry {'created' if created else 'found'}: {docker_host.id}")
        
        # Run validation using the model method
        validation_results = docker_host.validate_host_system()
        
        return Response({
            'success': True,
            'docker_host': {
                'id': docker_host.id,
                'name': docker_host.name,
                'status': docker_host.validation_status,
                'created': created,
                'can_create_databases': docker_host.can_create_databases()
            },
            'validation_results': validation_results,
            'summary': docker_host.get_validation_summary()
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
def validate_host(request, host_id):
    """Validate a specific host"""
    try:
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        
        if host.is_docker_host:
            # For docker host, use the validation system
            validation_results = host.validate_host_system()
            summary = host.get_validation_summary()
        else:
            # For other hosts, we'd need SSH-based validation (future feature)
            return Response({
                'success': False,
                'message': 'Validation not yet supported for remote hosts'
            }, status=400)
        
        return Response({
            'success': True,
            'host': {
                'id': host.id,
                'name': host.name,
                'status': host.validation_status,
                'can_create_databases': host.can_create_databases()
            },
            'validation_results': validation_results,
            'summary': summary
        })
        
    except Exception as e:
        logger.error(f"Host validation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Host validation failed'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_database(request):
    """Create a new database (only if host validation passes)"""
    try:
        host_id = request.data.get('host_id')
        if not host_id:
            return Response({
                'success': False,
                'message': 'Host ID is required'
            }, status=400)
        
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        
        # Check if host can create databases
        if not host.can_create_databases():
            return Response({
                'success': False,
                'message': f'Host validation failed. Status: {host.validation_status}. Run validation first.',
                'validation_summary': host.get_validation_summary()
            }, status=400)
        
        # TODO: Implement actual database creation logic
        return Response({
            'success': True,
            'message': 'Database creation logic to be implemented',
            'host_status': host.validation_status
        })
        
    except Exception as e:
        logger.error(f"Database creation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Database creation failed'
        }, status=500)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def remove_host(request, host_id):
    """Remove a host if it has no active databases"""
    try:
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        
        # Check if host can be removed
        if not host.can_be_removed():
            blockers = host.get_removal_blockers()
            return Response({
                'success': False,
                'message': 'Host cannot be removed',
                'blockers': blockers,
                'host': {
                    'id': host.id,
                    'name': host.name,
                    'database_count': host.get_database_count()
                }
            }, status=400)
        
        # Get host info before deletion
        host_info = {
            'id': host.id,
            'name': host.name,
            'ip_address': str(host.ip_address),
            'is_docker_host': host.is_docker_host
        }
        
        # Special handling for docker-host
        if host.is_docker_host:
            logger.warning(f"Removing docker-host: {host.name}")
        
        # Soft delete by setting is_active to False
        host.is_active = False
        host.save()
        
        logger.info(f"Host removed: {host.name} (ID: {host.id})")
        
        return Response({
            'success': True,
            'message': f'Host "{host_info["name"]}" has been removed successfully',
            'removed_host': host_info
        })
        
    except Exception as e:
        logger.error(f"Host removal failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to remove host'
        }, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def host_removal_check(request, host_id):
    """Check if a host can be removed and get removal information"""
    try:
        host = get_object_or_404(HostVM, id=host_id, is_active=True)
        
        can_remove = host.can_be_removed()
        blockers = host.get_removal_blockers()
        database_count = host.get_database_count()
        
        # Get list of databases for detailed info
        databases = []
        if database_count > 0:
            for db in host.database_set.filter(is_active=True):
                databases.append({
                    'id': db.id,
                    'name': db.name,
                    'db_type': db.db_type,
                    'port': db.port,
                    'created_at': db.created_at.isoformat()
                })
        
        return Response({
            'success': True,
            'host': {
                'id': host.id,
                'name': host.name,
                'ip_address': str(host.ip_address),
                'is_docker_host': host.is_docker_host,
                'validation_status': host.validation_status
            },
            'can_remove': can_remove,
            'blockers': blockers,
            'database_count': database_count,
            'databases': databases,
            'warnings': [
                'This action cannot be undone',
                'Host will be permanently removed from StagDB'
            ] + (['This is the Docker host - removing it will disable database creation'] if host.is_docker_host else [])
        })
        
    except Exception as e:
        logger.error(f"Host removal check failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to check host removal status'
        }, status=500)