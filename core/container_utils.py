import json
import logging
from typing import Dict, List, Optional, Tuple
from .host_system import HostSystemManager

logger = logging.getLogger(__name__)


class ContainerUtils:
    """Docker container management utilities"""
    
    def __init__(self, host_vm):
        self.host_vm = host_vm
        self.is_docker_host = host_vm.is_docker_host
        self.system_manager = HostSystemManager()
    
    def create_postgres_container(self, config: Dict) -> Dict:
        """
        Create and start PostgreSQL container
        
        Args:
            config: Container configuration dict with keys:
                - name: Container name
                - image: Docker image (e.g., postgres:15-alpine)
                - port: Host port to bind
                - volume_mount: Path to mount as /var/lib/postgresql/data
                - environment: Environment variables dict
                
        Returns:
            Dict with success status, container_id, and message
        """
        try:
            name = config['name']
            image = config['image']
            port = config['port']
            volume_mount = config['volume_mount']
            env_vars = config.get('environment', {})
            
            # Step 1: Pull image first to handle long downloads
            logger.info(f"Ensuring Docker image {image} is available...")
            pull_result = self.pull_image(image)
            if not pull_result['success']:
                return {
                    'success': False,
                    'message': f'Failed to pull image {image}: {pull_result["message"]}'
                }
            
            # Build environment variables string
            env_string = ' '.join([f'-e {k}="{v}"' for k, v in env_vars.items()])
            
            # Construct docker run command
            docker_cmd = (
                f'docker run -d '
                f'--name {name} '
                f'--restart unless-stopped '
                f'-p {port}:5432 '
                f'-v {volume_mount}:/var/lib/postgresql/data '
                f'{env_string} '
                f'{image}'
            )
            
            logger.info(f"Creating PostgreSQL container: {name}")
            success, stdout, stderr = self._execute_docker_command(docker_cmd)
            
            if success and stdout:
                container_id = stdout.strip()
                logger.info(f"Container {name} created successfully with ID: {container_id[:12]}")
                return {
                    'success': True,
                    'container_id': container_id,
                    'message': f'Container {name} created successfully'
                }
            else:
                logger.error(f"Failed to create container {name}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to create container: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error creating PostgreSQL container: {str(e)}")
            return {
                'success': False,
                'message': f'Container creation error: {str(e)}'
            }
    
    def get_container_status(self, container_name: str) -> Dict:
        """Get detailed container status"""
        try:
            # Get container info using docker inspect
            inspect_cmd = f'docker inspect {container_name}'
            success, stdout, stderr = self._execute_docker_command(inspect_cmd)
            
            if not success:
                if 'No such container' in stderr:
                    return {'status': 'missing', 'message': 'Container does not exist'}
                return {'status': 'error', 'message': f'Failed to inspect container: {stderr}'}
            
            try:
                container_info = json.loads(stdout)[0]
                state = container_info['State']
                
                status_data = {
                    'status': 'running' if state['Running'] else 'stopped',
                    'container_id': container_info['Id'][:12],
                    'image': container_info['Config']['Image'],
                    'created': container_info['Created'],
                    'started_at': state.get('StartedAt'),
                    'finished_at': state.get('FinishedAt'),
                }
                
                # Add uptime if running
                if state['Running'] and state.get('StartedAt'):
                    status_data['uptime'] = self._calculate_uptime(state['StartedAt'])
                
                # Add exit code if stopped
                if not state['Running']:
                    status_data['exit_code'] = state.get('ExitCode', 0)
                
                return status_data
                
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                return {'status': 'error', 'message': f'Failed to parse container info: {str(e)}'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Error getting container status: {str(e)}'}
    
    def get_container_logs(self, container_name: str, lines: int = 100) -> str:
        """Get container logs for debugging"""
        try:
            logs_cmd = f'docker logs --tail {lines} {container_name}'
            success, stdout, stderr = self._execute_docker_command(logs_cmd)
            
            if success:
                return stdout
            else:
                return f"Failed to get logs: {stderr}"
                
        except Exception as e:
            return f"Error getting container logs: {str(e)}"
    
    def stop_container(self, container_name: str) -> bool:
        """Stop container gracefully"""
        try:
            stop_cmd = f'docker stop {container_name}'
            success, stdout, stderr = self._execute_docker_command(stop_cmd, timeout=30)
            
            if success:
                logger.info(f"Container {container_name} stopped successfully")
                return True
            else:
                logger.error(f"Failed to stop container {container_name}: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error stopping container {container_name}: {str(e)}")
            return False
    
    def start_container(self, container_name: str) -> bool:
        """Start stopped container"""
        try:
            start_cmd = f'docker start {container_name}'
            success, stdout, stderr = self._execute_docker_command(start_cmd)
            
            if success:
                logger.info(f"Container {container_name} started successfully")
                return True
            else:
                logger.error(f"Failed to start container {container_name}: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error starting container {container_name}: {str(e)}")
            return False
    
    def remove_container(self, container_name: str) -> bool:
        """Remove container completely"""
        try:
            # Stop first if running
            self.stop_container(container_name)
            
            # Remove container
            remove_cmd = f'docker rm {container_name}'
            success, stdout, stderr = self._execute_docker_command(remove_cmd)
            
            if success:
                logger.info(f"Container {container_name} removed successfully")
                return True
            else:
                logger.error(f"Failed to remove container {container_name}: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error removing container {container_name}: {str(e)}")
            return False
    
    def execute_in_container(self, container_name: str, command: str) -> Tuple[bool, str, str]:
        """Execute command inside container"""
        try:
            exec_cmd = f'docker exec {container_name} {command}'
            return self._execute_docker_command(exec_cmd)
            
        except Exception as e:
            logger.error(f"Error executing command in container {container_name}: {str(e)}")
            return False, "", str(e)
    
    def check_container_health(self, container_name: str) -> Dict:
        """Comprehensive container health check"""
        status = self.get_container_status(container_name)
        
        health_data = {
            'container_name': container_name,
            'timestamp': self._get_current_timestamp(),
            'overall_health': 'unknown',
            'checks': {}
        }
        
        # Check 1: Container existence and state
        if status['status'] == 'missing':
            health_data['checks']['existence'] = {
                'status': 'fail',
                'message': 'Container does not exist'
            }
            health_data['overall_health'] = 'unhealthy'
            return health_data
        
        health_data['checks']['existence'] = {
            'status': 'pass',
            'message': 'Container exists'
        }
        
        # Check 2: Container running state
        if status['status'] == 'running':
            health_data['checks']['running'] = {
                'status': 'pass',
                'message': f"Container running since {status.get('started_at', 'unknown')}"
            }
            
            # Check 3: PostgreSQL connectivity (if running)
            pg_health = self._check_postgres_health(container_name)
            health_data['checks']['postgres'] = pg_health
            
            # Determine overall health
            if pg_health['status'] == 'pass':
                health_data['overall_health'] = 'healthy'
            else:
                health_data['overall_health'] = 'unhealthy'
                
        else:
            health_data['checks']['running'] = {
                'status': 'fail',
                'message': f"Container is {status['status']}"
            }
            health_data['overall_health'] = 'unhealthy'
        
        return health_data
    
    def get_container_resource_usage(self, container_name: str) -> Dict:
        """Get CPU, memory, disk usage stats"""
        try:
            stats_cmd = f'docker stats {container_name} --no-stream --format "table {{{{.CPUPerc}}}}\\t{{{{.MemUsage}}}}\\t{{{{.MemPerc}}}}"'
            success, stdout, stderr = self._execute_docker_command(stats_cmd)
            
            if success and stdout:
                lines = stdout.strip().split('\n')
                if len(lines) >= 2:  # Header + data line
                    data_line = lines[1]
                    parts = data_line.split('\t')
                    if len(parts) >= 3:
                        return {
                            'cpu_percent': parts[0],
                            'memory_usage': parts[1],
                            'memory_percent': parts[2],
                            'timestamp': self._get_current_timestamp()
                        }
            
            return {'error': 'Failed to parse stats output'}
            
        except Exception as e:
            return {'error': f'Error getting resource usage: {str(e)}'}
    
    def get_used_ports_in_range(self, start_port: int, end_port: int) -> List[int]:
        """Get list of ports currently in use in the specified range"""
        try:
            used_ports = set()
            
            # Method 1: Check system listening ports using /proc/net/tcp
            # For Docker host, we need to check the actual host, not the container
            if self.is_docker_host:
                # Use nsenter to read host's /proc/net/tcp directly
                tcp_cmd = 'nsenter -t 1 -n cat /proc/net/tcp'
            else:
                tcp_cmd = 'cat /proc/net/tcp'
            
            success, stdout, stderr = self._execute_docker_command(tcp_cmd, timeout=10)
            
            if success:
                for line in stdout.split('\n')[1:]:  # Skip header
                    if line.strip():
                        # Parse /proc/net/tcp format: sl local_address rem_address st ...
                        # local_address is in hex format like "3500007F:1539" (127.0.0.53:5433)
                        parts = line.split()
                        if len(parts) > 3 and parts[3] == '0A':  # 0A = LISTEN state
                            try:
                                local_addr = parts[1]  # Format: IP:PORT in hex
                                if ':' in local_addr:
                                    port_hex = local_addr.split(':')[1]
                                    port = int(port_hex, 16)  # Convert from hex
                                    if start_port <= port <= end_port:
                                        used_ports.add(port)
                                        # Convert IP from hex for logging
                                        ip_hex = local_addr.split(':')[0]
                                        ip_int = int(ip_hex, 16)
                                        ip_addr = f"{ip_int & 0xFF}.{(ip_int >> 8) & 0xFF}.{(ip_int >> 16) & 0xFF}.{(ip_int >> 24) & 0xFF}"
                                        logger.debug(f"Found used port {port} on {ip_addr} from /proc/net/tcp")
                            except (ValueError, IndexError) as e:
                                logger.debug(f"Failed to parse /proc/net/tcp line: {line} - {e}")
                                continue
            
            # Method 2: Check Docker container port mappings
            docker_cmd = 'docker ps --format "table {{.Names}}\\t{{.Ports}}"'
            success, stdout, stderr = self._execute_docker_command(docker_cmd, timeout=10)
            
            if success:
                for line in stdout.split('\n'):
                    if ':' in line and '->' in line:
                        # Parse port mappings like "0.0.0.0:5432->5432/tcp"
                        # Handle multiple port mappings per container
                        port_mappings = line.split(',')
                        for mapping in port_mappings:
                            if ':' in mapping and '->' in mapping:
                                try:
                                    # Extract host port from "0.0.0.0:5432->5432/tcp"
                                    host_part = mapping.split('->')[0].strip()
                                    if ':' in host_part:
                                        port = int(host_part.split(':')[-1])
                                        if start_port <= port <= end_port:
                                            used_ports.add(port)
                                            logger.debug(f"Found used port {port} from Docker container")
                                except (ValueError, IndexError):
                                    continue
            
            # Method 3: Try to bind to each port to verify availability (more reliable)
            import socket
            additional_used_ports = self._check_ports_by_binding(start_port, end_port)
            used_ports.update(additional_used_ports)
            
            result = sorted(list(used_ports))
            logger.info(f"Found {len(result)} used ports in range {start_port}-{end_port}: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error checking used ports: {str(e)}")
            # Return empty list to be safe - let Docker handle port conflicts
            return []
    
    def _check_ports_by_binding(self, start_port: int, end_port: int) -> List[int]:
        """Check port availability by attempting to bind to them"""
        used_ports = []
        
        try:
            import socket
            
            # Only check a reasonable number of ports to avoid performance issues
            ports_to_check = min(end_port - start_port + 1, 20)
            
            for port in range(start_port, start_port + ports_to_check):
                sock = None
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.settimeout(0.1)  # Very short timeout
                    result = sock.bind(('0.0.0.0', port))
                    # If bind succeeds, port is available
                except (socket.error, OSError):
                    # If bind fails, port is in use
                    used_ports.append(port)
                    logger.debug(f"Port {port} in use (binding failed)")
                finally:
                    if sock:
                        try:
                            sock.close()
                        except:
                            pass
                            
        except Exception as e:
            logger.warning(f"Error in port binding check: {str(e)}")
        
        return used_ports
    
    def is_port_available(self, port: int) -> bool:
        """Check if a specific port is available for binding like Docker would"""
        try:
            import socket
            
            # Test TCP binding to 0.0.0.0 (what Docker does)
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                # Don't use SO_REUSEADDR - we want to detect actual conflicts
                sock.settimeout(0.1)
                # This is exactly what Docker tries to do
                sock.bind(('0.0.0.0', port))
                logger.debug(f"Port {port} is available for Docker binding")
                return True
            except (socket.error, OSError) as e:
                # Log the specific error for debugging
                logger.debug(f"Port {port} not available for Docker binding: {e}")
                return False
            finally:
                if sock:
                    try:
                        sock.close()
                    except:
                        pass
            
        except Exception as e:
            logger.warning(f"Error checking port {port} availability: {e}")
            return False
    
    def find_available_port(self, start_port: int, end_port: int) -> Optional[int]:
        """Find the first available port in range using multiple methods"""
        try:
            # First get known used ports
            used_ports = self.get_used_ports_in_range(start_port, end_port)
            used_ports_set = set(used_ports)
            
            # Then test each port in range
            for port in range(start_port, end_port + 1):
                if port not in used_ports_set:
                    # Double-check by attempting to bind
                    if self.is_port_available(port):
                        logger.info(f"Found available port: {port}")
                        return port
                    else:
                        logger.debug(f"Port {port} appeared available but binding failed")
            
            logger.warning(f"No available ports found in range {start_port}-{end_port}")
            return None
            
        except Exception as e:
            logger.error(f"Error finding available port: {e}")
            return None
    
    def pull_image(self, image: str, timeout: int = 600) -> Dict:
        """
        Pull Docker image with extended timeout for large images
        
        Args:
            image: Docker image name (e.g., postgres:15-alpine)
            timeout: Timeout in seconds (default 10 minutes for image pulls)
            
        Returns:
            Dict with success status and message
        """
        try:
            logger.info(f"Checking if image {image} exists locally...")
            
            # First check if image exists locally
            inspect_cmd = f'docker image inspect {image}'
            success, stdout, stderr = self._execute_docker_command(inspect_cmd, timeout=10)
            
            if success:
                logger.info(f"Image {image} already exists locally")
                return {
                    'success': True,
                    'message': f'Image {image} already available locally',
                    'was_cached': True
                }
            
            # Image doesn't exist locally, need to pull it
            logger.info(f"Pulling Docker image {image}... (this may take several minutes)")
            pull_cmd = f'docker pull {image}'
            success, stdout, stderr = self._execute_docker_command(pull_cmd, timeout=timeout)
            
            if success:
                logger.info(f"Successfully pulled image {image}")
                return {
                    'success': True,
                    'message': f'Successfully pulled image {image}',
                    'was_cached': False
                }
            else:
                logger.error(f"Failed to pull image {image}: {stderr}")
                return {
                    'success': False,
                    'message': f'Failed to pull image: {stderr}'
                }
                
        except Exception as e:
            logger.error(f"Error pulling image {image}: {str(e)}")
            return {
                'success': False,
                'message': f'Image pull error: {str(e)}'
            }
    
    def check_image_availability(self, image: str) -> Dict:
        """
        Check if Docker image is available locally or remotely
        
        Args:
            image: Docker image name
            
        Returns:
            Dict with availability info
        """
        try:
            # Check local availability
            inspect_cmd = f'docker image inspect {image}'
            success, stdout, stderr = self._execute_docker_command(inspect_cmd, timeout=10)
            
            if success:
                return {
                    'available_locally': True,
                    'needs_pull': False,
                    'message': f'Image {image} available locally'
                }
            
            # Check remote availability (docker manifest inspect)
            manifest_cmd = f'docker manifest inspect {image}'
            success, stdout, stderr = self._execute_docker_command(manifest_cmd, timeout=30)
            
            return {
                'available_locally': False,
                'needs_pull': True,
                'available_remotely': success,
                'message': f'Image {image} {"available remotely" if success else "not found remotely"}'
            }
            
        except Exception as e:
            return {
                'available_locally': False,
                'needs_pull': True,
                'available_remotely': False,
                'error': str(e),
                'message': f'Error checking image availability: {str(e)}'
            }
    
    def get_image_info(self, image: str) -> Dict:
        """Get detailed information about a Docker image"""
        try:
            inspect_cmd = f'docker image inspect {image}'
            success, stdout, stderr = self._execute_docker_command(inspect_cmd, timeout=10)
            
            if success:
                import json
                image_info = json.loads(stdout)[0]
                return {
                    'success': True,
                    'size_bytes': image_info.get('Size', 0),
                    'created': image_info.get('Created'),
                    'architecture': image_info.get('Architecture'),
                    'os': image_info.get('Os'),
                    'repo_tags': image_info.get('RepoTags', []),
                    'layers': len(image_info.get('RootFS', {}).get('Layers', []))
                }
            else:
                return {
                    'success': False,
                    'message': f'Image {image} not found locally'
                }
                
        except Exception as e:
            return {
                'success': False,
                'message': f'Error getting image info: {str(e)}'
            }
    
    def _execute_docker_command(self, command: str, timeout: int = 30) -> Tuple[bool, str, str]:
        """Execute Docker command on host"""
        if self.is_docker_host:
            # For docker host, execute directly
            return self.system_manager.execute_command(command, timeout=timeout)
        else:
            # For remote host, use host command execution
            return self.system_manager.execute_host_command(command, timeout=timeout)
    
    def _check_postgres_health(self, container_name: str) -> Dict:
        """Check PostgreSQL health inside container"""
        try:
            # Use pg_isready to check PostgreSQL health
            success, stdout, stderr = self.execute_in_container(
                container_name, 
                'pg_isready -U postgres'
            )
            
            if success:
                return {
                    'status': 'pass',
                    'message': 'PostgreSQL is accepting connections'
                }
            else:
                return {
                    'status': 'fail',
                    'message': f'PostgreSQL not ready: {stderr}'
                }
                
        except Exception as e:
            return {
                'status': 'fail',
                'message': f'Error checking PostgreSQL health: {str(e)}'
            }
    
    def _calculate_uptime(self, started_at: str) -> str:
        """Calculate container uptime from started_at timestamp"""
        try:
            from datetime import datetime
            import re
            
            # Parse Docker's timestamp format
            # Remove the nanoseconds part if present
            timestamp = re.sub(r'\.\d+', '', started_at.replace('Z', '+00:00'))
            
            start_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            current_time = datetime.now(start_time.tzinfo)
            
            uptime_delta = current_time - start_time
            
            days = uptime_delta.days
            hours, remainder = divmod(uptime_delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            if days > 0:
                return f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                return f"{hours}h {minutes}m"
            else:
                return f"{minutes}m"
                
        except Exception:
            return "unknown"
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format"""
        from datetime import datetime
        return datetime.now().isoformat()