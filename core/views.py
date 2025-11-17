from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import HostVM, Database
from .host_validator import HostValidator
from .host_system import HostSystemManager
import logging
import json

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
    
    # No longer tracking branches - using ZFS operations instead
    branches_count = 0
    
    context = {
        'host': host,
        'databases': databases,
        'databases_count': databases.count(),
        'active_databases_count': databases.filter(is_active=True).count(),
        'branches_count': branches_count,
    }
    return render(request, 'host_detail.html', context)


@login_required
def add_database_host(request):
    """Unified wizard for adding database hosts (Docker or Remote)"""
    return render(request, 'add_database_host.html')


@login_required
def database_detail_page(request, database_id):
    """Display comprehensive database information"""
    database = get_object_or_404(Database, id=database_id, is_active=True)
    
    # Get connection information
    connection_info = database.get_connection_info()
    
    # Get storage metrics
    storage_metrics = database.get_storage_metrics()
    
    # Get snapshot hierarchy
    snapshot_hierarchy = database.get_snapshot_hierarchy()
    
    # Get ZFS lineage and creation info
    zfs_lineage = database.get_zfs_lineage()
    creation_info = database.get_creation_info()
    child_databases = database.get_child_databases()
    
    context = {
        'database': database,
        'connection_info': connection_info,
        'storage_metrics': storage_metrics,
        'snapshot_hierarchy': snapshot_hierarchy,
        'zfs_lineage': zfs_lineage,
        'child_databases': child_databases,
        'host': database.host_vm,
    }
    
    # Add creation info to database object for template access
    database.creation_info = creation_info
    return render(request, 'database_detail.html', context)


@login_required
def database_connect(request, database_id):
    """Display database connection information"""
    database = get_object_or_404(Database, id=database_id, is_active=True)
    
    # Get connection information
    connection_info = database.get_connection_info()
    
    context = {
        'database': database,
        'connection_info': connection_info,
        'host': database.host_vm,
    }
    return render(request, 'database_connect.html', context)


@login_required
def add_host(request):
    return render(request, 'onboarding.html')


@login_required
def add_database(request, host_id):
    """Web interface for adding a database to a specific host"""
    host = get_object_or_404(HostVM, id=host_id, is_active=True)
    
    context = {
        'host': host,
        'can_create_databases': host.can_create_databases(),
        'validation_summary': host.get_validation_summary() if not host.can_create_databases() else None
    }
    
    return render(request, 'add_database.html', context)


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
        
        # Get validation summary for component details
        summary = validator.get_validation_summary()
        
        # Generate remediation steps
        remediation_steps = _generate_remediation_steps(validation_results)
        
        return Response({
            'success': True,
            'overall_status': validation_results.get('overall_status', 'unknown'),
            'message': validation_results.get('message', 'Validation completed'),
            'components': summary.get('components', {}),
            'remediation_steps': remediation_steps,
            'validation_results': validation_results,
            'summary': summary
        })
        
    except Exception as e:
        logger.error(f"Docker host validation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'System validation failed',
            'overall_status': 'error'
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
        
        # Redirect to the new database creation endpoint
        # This maintains backward compatibility while using the new implementation
        from .database_views import create_database as new_create_database
        return new_create_database(request)
        
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
            'is_docker_host': host.is_docker_host,
            'storage_config': host.storage_config.name if host.storage_config else None
        }
        
        # Clean up storage configuration if present
        storage_cleanup_result = None
        if host.storage_config and host.storage_config.is_configured:
            from .storage_utils import StorageUtils
            storage_utils = StorageUtils()
            storage_cleanup_result = storage_utils.cleanup_storage_configuration(host.storage_config)
            
            if not storage_cleanup_result['success']:
                logger.warning(f"Storage cleanup failed for host {host.name}: {storage_cleanup_result['message']}")
            else:
                logger.info(f"Storage cleanup completed for host {host.name}: {storage_cleanup_result['message']}")
        
        # Special handling for docker-host
        if host.is_docker_host:
            logger.warning(f"Removing docker-host: {host.name}")
        
        # Soft delete by setting is_active to False
        host.is_active = False
        host.save()
        
        # Also mark the storage configuration as inactive if it exists
        if host.storage_config:
            host.storage_config.is_active = False
            host.storage_config.save()
        
        logger.info(f"Host removed: {host.name} (ID: {host.id})")
        
        # Prepare response with cleanup details
        response_data = {
            'success': True,
            'message': f'Host "{host_info["name"]}" has been removed successfully',
            'removed_host': host_info
        }
        
        # Include storage cleanup results if applicable
        if storage_cleanup_result:
            response_data['storage_cleanup'] = storage_cleanup_result
            if not storage_cleanup_result['success']:
                response_data['message'] += ' (with storage cleanup warnings)'
        
        return Response(response_data)
        
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def validate_remote_host(request):
    """Validate a remote host configuration"""
    try:
        host_data = request.data
        
        # Validate required fields
        required_fields = ['name', 'ip_address', 'username', 'auth_method']
        for field in required_fields:
            if not host_data.get(field):
                return Response({
                    'success': False,
                    'message': f'{field} is required',
                    'overall_status': 'error'
                })
        
        # Validate authentication data
        auth_method = host_data.get('auth_method')
        if auth_method == 'password' and not host_data.get('password'):
            return Response({
                'success': False,
                'message': 'Password is required for password authentication',
                'overall_status': 'error'
            })
        elif auth_method == 'key' and not host_data.get('ssh_key'):
            return Response({
                'success': False,
                'message': 'SSH key is required for key authentication',
                'overall_status': 'error'
            })
        
        # Create a temporary HostVM instance for validation (don't save yet)
        temp_host = HostVM(
            name=host_data['name'],
            ip_address=host_data['ip_address'],
            username=host_data['username'],
            password=host_data.get('password', ''),
            ssh_key=host_data.get('ssh_key', ''),
            is_docker_host=False
        )
        
        # Run validation using the temporary host
        try:
            validation_results = temp_host.validate_host_system()
            
            # Generate remediation steps based on validation results
            remediation_steps = _generate_remediation_steps(validation_results)
            
            return Response({
                'success': True,
                'overall_status': validation_results.get('overall_status', 'unknown'),
                'message': validation_results.get('message', 'Validation completed'),
                'components': temp_host._get_component_summary(),
                'remediation_steps': remediation_steps
            })
            
        except Exception as validation_error:
            logger.error(f"Remote host validation failed: {str(validation_error)}")
            return Response({
                'success': False,
                'message': f'Validation failed: {str(validation_error)}',
                'overall_status': 'error',
                'remediation_steps': [
                    'Check network connectivity to the host',
                    'Verify SSH credentials are correct',
                    'Ensure the host is accessible from this network'
                ]
            })
        
    except Exception as e:
        logger.error(f"Remote host validation error: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Remote host validation failed',
            'overall_status': 'error'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_database_host(request):
    """Create a new database host (Docker or Remote)"""
    try:
        host_data = request.data
        host_type = host_data.get('host_type')
        
        if host_type == 'docker':
            # Create or get Docker host
            docker_host, created = HostVM.get_or_create_docker_host()

            # Update user-accessible configuration
            docker_host.user_accessible_host = host_data.get('user_accessible_host', 'localhost')
            docker_host.default_username = host_data.get('default_username', 'postgres')
            docker_host.default_port_range = host_data.get('default_port_range', 5432)

            # Create storage configuration from selected pool
            selected_pool = host_data.get('selected_pool')
            if selected_pool and not docker_host.storage_config:
                from .models import StorageConfiguration
                storage_config = StorageConfiguration.objects.create(
                    name=f"{docker_host.name}-storage",
                    storage_type='existing_pool',
                    existing_pool_name=selected_pool,
                    pool_type='single',  # Will be updated by storage sync
                    compression='lz4',
                    dedup=False,
                    is_configured=True,
                    is_active=True
                )
                docker_host.storage_config = storage_config
                logger.info(f"Created storage configuration for pool: {selected_pool}")

            docker_host.save()

            # Run validation
            validation_results = docker_host.validate_host_system()

            if validation_results.get('overall_status') in ['valid', 'warning']:
                return Response({
                    'success': True,
                    'message': 'Docker host configured successfully',
                    'host_id': docker_host.id,
                    'validation_status': validation_results.get('overall_status')
                })
            else:
                return Response({
                    'success': False,
                    'message': 'Docker host validation failed',
                    'validation_results': validation_results
                })
                
        elif host_type == 'remote':
            # Create remote host
            host = HostVM.objects.create(
                name=host_data['name'],
                ip_address=host_data['ip_address'],
                username=host_data['username'],
                password=host_data.get('password', ''),
                ssh_key=host_data.get('ssh_key', ''),
                is_docker_host=False,
                is_active=True,
                user_accessible_host=host_data.get('user_accessible_host', host_data['ip_address']),
                default_username=host_data.get('default_username', 'postgres'),
                default_port_range=host_data.get('default_port_range', 5432)
            )
            
            # Run validation
            validation_results = host.validate_host_system()
            
            if validation_results.get('overall_status') in ['valid', 'warning']:
                return Response({
                    'success': True,
                    'message': f'Remote host "{host.name}" added successfully',
                    'host_id': host.id,
                    'validation_status': validation_results.get('overall_status')
                })
            else:
                # Still create the host but mark it as needing attention
                return Response({
                    'success': True,
                    'message': f'Remote host "{host.name}" added but requires attention',
                    'host_id': host.id,
                    'validation_status': validation_results.get('overall_status'),
                    'validation_results': validation_results
                })
        else:
            return Response({
                'success': False,
                'message': 'Invalid host type. Must be "docker" or "remote"'
            }, status=400)
            
    except Exception as e:
        logger.error(f"Database host creation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to create database host'
        }, status=500)


def _generate_remediation_steps(validation_results):
    """Generate remediation steps based on validation results"""
    remediation_steps = []
    
    if not validation_results:
        return ['Run host validation to identify issues']
    
    overall_status = validation_results.get('overall_status', 'unknown')
    
    if overall_status == 'valid':
        return []
    
    # Check specific component failures
    components = validation_results
    
    # Docker Engine issues
    docker_engine = components.get('docker_engine', {})
    if docker_engine.get('status') == 'fail':
        remediation_steps.extend([
            'Install Docker Engine: curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh',
            'Start Docker service: sudo systemctl start docker',
            'Enable Docker on startup: sudo systemctl enable docker'
        ])
    
    # Docker Compose issues
    docker_compose = components.get('docker_compose', {})
    if docker_compose.get('status') == 'fail':
        remediation_steps.append('Install Docker Compose: sudo apt-get install docker-compose-plugin')
    
    # ZFS issues
    zfs_utilities = components.get('zfs_utilities', {})
    if zfs_utilities.get('status') == 'fail':
        # Check if this is a Secure Boot issue
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"ZFS utilities validation failed. Secure Boot issue flag: {zfs_utilities.get('secure_boot_issue')}")
        logger.info(f"ZFS utilities full data: {zfs_utilities}")

        if zfs_utilities.get('secure_boot_issue'):
            remediation_steps.extend([
                '⚠️  ZFS modules cannot load due to Secure Boot restrictions',
                'Option 1 (Recommended): Disable Secure Boot in BIOS/UEFI settings',
                'Option 2: Change Secure Boot from "Deployed Mode" to "Setup/Audit Mode" in BIOS',
                'Option 3 (Advanced): Sign ZFS modules with Machine Owner Key (MOK)',
                'After fixing Secure Boot, run: sudo modprobe zfs',
                'See installation wizard for detailed Secure Boot instructions'
            ])
        else:
            remediation_steps.extend([
                'Install ZFS utilities: sudo apt-get install zfsutils-linux',
                'Load ZFS kernel module: sudo modprobe zfs'
            ])
    
    zfs_pools = components.get('zfs_pools', {})
    if zfs_pools.get('status') == 'fail':
        remediation_steps.extend([
            'Note: ZFS pools will be configured in the storage setup step',
            'If you want to use existing pools: sudo zpool import <pool_name>'
        ])
    
    # Access issues
    docker_access = components.get('docker_access', {})
    if docker_access.get('status') == 'fail':
        remediation_steps.extend([
            'Add user to docker group: sudo usermod -aG docker $USER',
            'Restart session or run: newgrp docker'
        ])
    
    # Host resources
    host_resources = components.get('host_resources', {})
    if host_resources.get('status') == 'warning':
        remediation_steps.append('Consider adding more RAM or disk space for better performance')
    
    # Network ports
    network_ports = components.get('network_ports', {})
    if network_ports.get('status') == 'warning':
        remediation_steps.append('Some ports in the 5432-5500 range may be in use')
    
    if not remediation_steps:
        remediation_steps = [
            'Check system logs for specific error messages',
            'Ensure the host meets minimum system requirements',
            'Verify network connectivity and firewall settings'
        ]
    
    return remediation_steps


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def discover_storage_options(request):
    """Discover available storage options (existing pools and available disks)"""
    try:
        logger.info("Storage discovery request received")
        host_type = request.data.get('host_type')
        host_data = request.data.get('host_data', {})
        
        logger.info(f"Host type: {host_type}, Host data: {host_data}")
        
        # Now use real discovery logic
        if host_type == 'docker':
            # Use local system manager for Docker host
            from .host_system import HostSystemManager
            system_manager = HostSystemManager()
            
        elif host_type == 'remote':
            # Create temporary host system manager for remote host
            from .host_system import HostSystemManager
            temp_host = HostVM(
                name=host_data.get('name', 'temp'),
                ip_address=host_data.get('ip_address'),
                username=host_data.get('username'),
                password=host_data.get('password', ''),
                ssh_key=host_data.get('ssh_key', ''),
                is_docker_host=False
            )
            system_manager = HostSystemManager(temp_host)
            
        else:
            return Response({
                'success': False,
                'message': 'Invalid host type'
            }, status=400)
        
        # Discover existing ZFS pools
        existing_pools = []
        pool_devices = {}
        zfs_error = None
        try:
            zfs_info = system_manager.get_zfs_info()
            logger.info(f"ZFS info received: {zfs_info}")
            
            if 'zfs_pools' in zfs_info and zfs_info['zfs_pools']:
                existing_pools = zfs_info['zfs_pools']
                logger.info(f"Found {len(existing_pools)} existing ZFS pools")
                
                # Get pool device mapping
                if 'pool_devices' in zfs_info:
                    pool_devices = zfs_info['pool_devices']
                    logger.info(f"Pool devices: {pool_devices}")
            else:
                logger.info("No existing ZFS pools found")
                if 'zfs_pools_error' in zfs_info:
                    zfs_error = zfs_info['zfs_pools_error']
                    logger.warning(f"ZFS pools error: {zfs_error}")
        except Exception as e:
            zfs_error = str(e)
            logger.warning(f"Failed to get ZFS info: {str(e)}")
            
        # Create a set of devices that are already in use by ZFS pools
        used_devices = set()
        for pool_name, devices in pool_devices.items():
            for device in devices:
                used_devices.add(device)
        logger.info(f"Devices already in use by ZFS pools: {used_devices}")
        
        # Discover available disks
        available_disks = []
        lsblk_error = None
        all_devices = []
        
        try:
            # Get list of available block devices that could be used for ZFS
            success, stdout, stderr = system_manager.execute_command(
                "lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE", timeout=10
            )
            
            logger.info(f"lsblk command result: success={success}")
            if stderr:
                logger.warning(f"lsblk stderr: {stderr}")
            
            if success:
                try:
                    lsblk_data = json.loads(stdout)
                    logger.info(f"lsblk returned {len(lsblk_data.get('blockdevices', []))} devices")
                    
                    for device in lsblk_data.get('blockdevices', []):
                        try:
                            # Ensure device is not None and has basic properties
                            if not device or not isinstance(device, dict):
                                logger.warning(f"Skipping invalid device: {device}")
                                continue
                                
                            device_info = {
                                'name': device.get('name'),
                                'size': device.get('size'),
                                'type': device.get('type'), 
                                'mountpoint': device.get('mountpoint'),
                                'fstype': device.get('fstype'),
                                'has_children': bool(device.get('children'))
                            }
                            all_devices.append(device_info)
                            logger.info(f"Device: {device_info}")
                            
                            # Show all disks with appropriate warnings and usability status
                            if device.get('type') == 'disk':
                                status = 'available'
                                warnings = []
                                is_system_disk = False
                                
                                # Check if this is likely a system disk with null safety
                                try:
                                    if device.get('children'):
                                        for child in device['children']:
                                            if not child or not isinstance(child, dict):
                                                continue
                                                
                                            child_mount = child.get('mountpoint') or ''
                                            child_fstype = child.get('fstype') or ''
                                            child_name = child.get('name') or ''
                                            
                                            logger.debug(f"Checking child {child_name}: mount='{child_mount}', fstype='{child_fstype}'")
                                            
                                            # System disk indicators with null checks
                                            # Only consider actual system mount points and filesystem types
                                            # Note: When running in Docker, mount points may appear differently
                                            if (child_mount in ['/', '/boot', '/boot/efi', '[SWAP]'] or 
                                                (child_mount and child_mount.startswith('/boot')) or
                                                (child_mount and child_mount.startswith('/etc')) or  # Docker container mounts
                                                child_fstype == 'swap'):
                                                logger.info(f"Detected system disk: {device.get('name')} due to child {child_name} with mount='{child_mount}', fstype='{child_fstype}'")
                                                is_system_disk = True
                                                break
                                except (TypeError, AttributeError) as e:
                                    logger.warning(f"Error checking system disk status for {device.get('name', 'unknown')}: {e}")
                                    is_system_disk = False
                                
                                # Check if this disk is already used by a ZFS pool
                                device_path = f"/dev/{device.get('name', '')}"
                                is_zfs_in_use = device_path in used_devices
                                if is_zfs_in_use:
                                    logger.info(f"Device {device_path} is already in use by a ZFS pool")
                                
                                # Set status based on disk characteristics
                                try:
                                    if is_system_disk:
                                        status = 'system'
                                        warnings.append('⚠️ System disk - contains OS/boot partitions')
                                    elif is_zfs_in_use:
                                        status = 'zfs_in_use'
                                        warnings.append('🗄️ Already used by existing ZFS pool')
                                    elif device.get('mountpoint'):
                                        status = 'mounted'
                                        warnings.append('💿 Currently mounted')
                                    elif device.get('fstype'):
                                        status = 'filesystem'
                                        warnings.append(f'💾 Has {device.get("fstype")} filesystem')
                                    elif device.get('children'):
                                        # Check if partitions are mounted or have important data
                                        has_mounted_partitions = False
                                        try:
                                            for child in device.get('children', []):
                                                if not child or not isinstance(child, dict):
                                                    continue
                                                child_mount = child.get('mountpoint') if child else None
                                                child_fstype = child.get('fstype') if child else None
                                                if child_mount or child_fstype:
                                                    has_mounted_partitions = True
                                                    break
                                        except (TypeError, AttributeError) as e:
                                            logger.warning(f"Error checking partitions for {device.get('name', 'unknown')}: {e}")
                                        
                                        if has_mounted_partitions:
                                            status = 'partitioned'
                                            warnings.append('📀 Has partitions with data')
                                        else:
                                            warnings.append('🔧 Has empty partitions')
                                except (TypeError, AttributeError) as e:
                                    logger.warning(f"Error determining disk status for {device.get('name', 'unknown')}: {e}")
                                    status = 'unknown'
                                    warnings.append('❓ Status detection failed')
                                
                                # Determine usability - disks are usable if they're not system disks or already in ZFS use
                                # Even disks with partitions can be used for ZFS (partitions will be destroyed)
                                usable = not is_system_disk and not is_zfs_in_use and not device.get('fstype')
                                
                                # Add helpful descriptions
                                description = 'Safe for ZFS pool creation'
                                if is_system_disk:
                                    description = 'System disk - do not use for ZFS'
                                elif is_zfs_in_use:
                                    description = 'Already in use by ZFS pool'
                                elif status == 'mounted':
                                    description = 'In use - unmount first'
                                elif status == 'filesystem':
                                    description = 'Contains data - will be erased'
                                elif status == 'partitioned':
                                    description = 'Contains partitions - will be erased'
                                elif status == 'unknown':
                                    description = 'Status detection failed - use with caution'
                                
                                # Safe device name extraction
                                device_name = device.get('name', 'unknown')
                                if device_name and device_name != 'unknown':
                                    disk_path = f"/dev/{device_name}"
                                else:
                                    disk_path = "unknown"
                                
                                available_disks.append({
                                    'name': disk_path,
                                    'size': device.get('size', 'Unknown'),
                                    'type': 'Disk',
                                    'status': status,
                                    'warnings': warnings,
                                    'usable': usable,
                                    'description': description,
                                    'is_system_disk': is_system_disk
                                })
                            
                            # Also check children (partitions) for completeness
                            if device.get('children'):
                                for child in device['children']:
                                    if not child or not isinstance(child, dict):
                                        continue
                                    try:
                                        child_info = {
                                            'name': child.get('name', 'unknown'),
                                            'size': child.get('size', 'unknown'),
                                            'type': child.get('type', 'unknown'),
                                            'mountpoint': child.get('mountpoint'),
                                            'fstype': child.get('fstype'),
                                            'parent': device.get('name', 'unknown')
                                        }
                                        all_devices.append(child_info)
                                        logger.info(f"  Child device: {child_info}")
                                    except (TypeError, AttributeError) as e:
                                        logger.warning(f"Error processing child device: {e}")
                                        continue
                        except (TypeError, AttributeError, KeyError) as e:
                            logger.warning(f"Error processing device {device.get('name', 'unknown') if device else 'invalid'}: {e}")
                            continue
                    
                    logger.info(f"Added {len(available_disks)} disk devices")
                    
                    # If no disks were found with the enhanced logic, try simpler approach
                    if len(available_disks) == 0:
                        logger.warning("No disks found with enhanced logic, trying simpler approach")
                        for device in lsblk_data.get('blockdevices', []):
                            if not device or not isinstance(device, dict):
                                continue
                            if device.get('type') == 'disk':
                                device_name = device.get('name', 'unknown')
                                if device_name and device_name != 'unknown':
                                    disk_path = f"/dev/{device_name}"
                                    available_disks.append({
                                        'name': disk_path,
                                        'size': device.get('size', 'Unknown'),
                                        'type': 'Disk',
                                        'status': 'unknown',
                                        'warnings': ['Status detection failed'],
                                        'usable': True,  # Default to usable for debugging
                                        'description': 'Status detection failed - use with caution',
                                        'is_system_disk': False
                                    })
                                    logger.info(f"Added disk with simple logic: {disk_path}")
                                else:
                                    logger.warning("Skipping disk with no name")
                    
                except json.JSONDecodeError as e:
                    lsblk_error = f"Failed to parse lsblk JSON: {str(e)}"
                    logger.warning(lsblk_error)
            else:
                lsblk_error = f"lsblk command failed: {stderr}"
                logger.warning(lsblk_error)
                    
        except Exception as e:
            lsblk_error = f"Disk discovery exception: {str(e)}"
            logger.warning(lsblk_error)
        
        logger.info(f"Final result: {len(existing_pools)} pools, {len(available_disks)} disks")
        
        # Include debug information
        debug_info = {
            'zfs_error': zfs_error,
            'lsblk_error': lsblk_error,
            'total_devices_found': len(all_devices),
            'all_devices': all_devices[:10],  # Limit to first 10 for response size
        }
        
        return Response({
            'success': True,
            'existing_pools': existing_pools,
            'available_disks': available_disks,
            'debug': debug_info
        })
        
    except Exception as e:
        logger.error(f"Storage discovery failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Failed to discover storage options'
        }, status=500)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_zfs_pool(request):
    """Create a new ZFS pool from selected disks"""
    try:
        pool_name = request.data.get('pool_name', '').strip()
        pool_type = request.data.get('pool_type', 'single')
        selected_disks = request.data.get('selected_disks', [])
        host_type = request.data.get('host_type')
        host_data = request.data.get('host_data', {})
        
        # Validate inputs
        if not pool_name:
            return Response({
                'success': False,
                'message': 'Pool name is required'
            }, status=400)
            
        if not selected_disks:
            return Response({
                'success': False,
                'message': 'At least one disk must be selected'
            }, status=400)
        
        # Validate pool type requirements
        if pool_type == 'mirror' and len(selected_disks) < 2:
            return Response({
                'success': False,
                'message': 'Mirror pools require at least 2 disks'
            }, status=400)
            
        if pool_type == 'raidz1' and len(selected_disks) < 3:
            return Response({
                'success': False,
                'message': 'RAID-Z1 pools require at least 3 disks'
            }, status=400)
        
        # Get system manager
        if host_type == 'docker':
            from .host_system import HostSystemManager
            system_manager = HostSystemManager()
        elif host_type == 'remote':
            temp_host = HostVM(
                name=host_data.get('name', 'temp'),
                ip_address=host_data.get('ip_address'),
                username=host_data.get('username'),
                password=host_data.get('password', ''),
                ssh_key=host_data.get('ssh_key', ''),
                is_docker_host=False
            )
            from .host_system import HostSystemManager
            system_manager = HostSystemManager(temp_host)
        else:
            return Response({
                'success': False,
                'message': 'Invalid host type'
            }, status=400)
        
        # Build ZFS pool creation command
        if pool_type == 'single':
            disks_str = ' '.join(selected_disks)
            zpool_cmd = f"zpool create {pool_name} {disks_str}"
        elif pool_type == 'mirror':
            disks_str = ' '.join(selected_disks)
            zpool_cmd = f"zpool create {pool_name} mirror {disks_str}"
        elif pool_type == 'raidz1':
            disks_str = ' '.join(selected_disks)
            zpool_cmd = f"zpool create {pool_name} raidz1 {disks_str}"
        else:
            return Response({
                'success': False,
                'message': f'Unsupported pool type: {pool_type}'
            }, status=400)
        
        logger.info(f"Creating ZFS pool with command: {zpool_cmd}")
        
        # Execute the pool creation command
        success, stdout, stderr = system_manager.execute_command(zpool_cmd, timeout=60)
        
        if success:
            # Verify the pool was created successfully
            success, verify_stdout, verify_stderr = system_manager.execute_command(
                f"zpool status {pool_name}", timeout=10
            )
            
            if success:
                return Response({
                    'success': True,
                    'message': f'ZFS pool "{pool_name}" created successfully',
                    'pool_name': pool_name,
                    'pool_type': pool_type,
                    'disks': selected_disks
                })
            else:
                return Response({
                    'success': False,
                    'message': f'Pool creation appeared to succeed but verification failed: {verify_stderr}'
                })
        else:
            return Response({
                'success': False,
                'message': f'Failed to create ZFS pool: {stderr}'
            })
            
    except Exception as e:
        logger.error(f"ZFS pool creation failed: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'ZFS pool creation failed'
        }, status=500)