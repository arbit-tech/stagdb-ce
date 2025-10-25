import subprocess
import json
import os
import platform
import logging
import base64
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class HostSystemManager:
    """Handles host system command execution and validation from within container"""
    
    def __init__(self):
        self.validation_results = {}
        self.is_in_container = self._detect_container_environment()
        
    def _detect_container_environment(self) -> bool:
        """Detect if running inside a container"""
        container_indicators = [
            os.path.exists('/.dockerenv'),
            os.environ.get('container') is not None,
            os.path.exists('/proc/1/cgroup') and self._check_cgroup_container()
        ]
        return any(container_indicators)
    
    def _check_cgroup_container(self) -> bool:
        """Check cgroup to detect container environment"""
        try:
            with open('/proc/1/cgroup', 'r') as f:
                content = f.read()
                return 'docker' in content or 'containerd' in content or 'kubepods' in content
        except (OSError, IOError):
            return False
    
    def execute_command(self, command: str, timeout: int = 30, check_return_code: bool = True) -> Tuple[bool, str, str]:
        """Execute command with error handling"""
        try:
            # If running in container with host access, use nsenter to execute on host
            if self.is_in_container and os.path.exists('/host/proc'):
                # Use nsenter to execute command in host namespace
                nsenter_cmd = f"nsenter --target 1 --mount --uts --ipc --net --pid -- {command}"
                logger.info(f"Executing command on host via nsenter: {command}")
                actual_command = nsenter_cmd
            else:
                logger.info(f"Executing command locally: {command}")
                actual_command = command
                
            result = subprocess.run(
                actual_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            success = result.returncode == 0 if check_return_code else True
            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            
            if not success:
                logger.warning(f"Command failed: {command}, stderr: {stderr}")
            
            return success, stdout, stderr
            
        except subprocess.TimeoutExpired:
            error_msg = f"Command timed out after {timeout}s: {command}"
            logger.error(error_msg)
            return False, "", error_msg
            
        except Exception as e:
            error_msg = f"Command execution failed: {command}, error: {str(e)}"
            logger.error(error_msg)
            return False, "", error_msg
    
    def execute_host_command(self, command: str, timeout: int = 30) -> Tuple[bool, str, str]:
        """Execute command on Docker host via nsenter"""
        if not self.is_in_container:
            # If not in container, execute directly
            return self.execute_command(command, timeout)
        
        # Use nsenter to access host namespace
        host_command = f"nsenter -t 1 -m -p {command}"
        return self.execute_command(host_command, timeout)
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get basic system information"""
        info = {
            'in_container': self.is_in_container,
            'platform': platform.platform(),
            'python_version': platform.python_version(),
        }
        
        # Get container system info
        success, stdout, _ = self.execute_command("uname -a")
        if success:
            info['container_uname'] = stdout
            
        # Get host system info if in container
        if self.is_in_container:
            success, stdout, _ = self.execute_host_command("uname -a")
            if success:
                info['host_uname'] = stdout
                
            success, stdout, _ = self.execute_host_command("cat /etc/os-release")
            if success:
                info['host_os_release'] = stdout
        
        return info
    
    def test_docker_socket_access(self) -> Tuple[bool, str]:
        """Test if Docker socket is accessible from container"""
        socket_path = "/var/run/docker.sock"
        
        if not os.path.exists(socket_path):
            return False, "Docker socket not mounted at /var/run/docker.sock"
        
        # Test basic docker command
        success, stdout, stderr = self.execute_command("docker version --format '{{.Server.Version}}'")
        if not success:
            return False, f"Cannot access Docker daemon: {stderr}"
        
        return True, f"Docker daemon accessible, version: {stdout}"
    
    def test_privileged_access(self) -> Tuple[bool, str]:
        """Test if container has privileged access to host"""
        # Test nsenter access
        success, stdout, stderr = self.execute_host_command("echo 'host_access_test'")
        if not success:
            return False, f"Cannot access host namespace: {stderr}"
        
        if stdout != "host_access_test":
            return False, "Host namespace access verification failed"
        
        return True, "Privileged host access confirmed"
    
    def get_docker_info(self) -> Dict[str, Any]:
        """Get Docker system information"""
        info = {}
        
        # Docker version
        success, stdout, stderr = self.execute_command("docker --version")
        if success:
            info['docker_version'] = stdout
        else:
            info['docker_version_error'] = stderr
        
        # Docker info
        success, stdout, stderr = self.execute_command("docker info --format json", timeout=10)
        if success:
            try:
                docker_info = json.loads(stdout)
                info['docker_info'] = {
                    'server_version': docker_info.get('ServerVersion'),
                    'containers_running': docker_info.get('ContainersRunning', 0),
                    'containers_total': docker_info.get('Containers', 0),
                    'images': docker_info.get('Images', 0),
                    'storage_driver': docker_info.get('Driver'),
                    'docker_root_dir': docker_info.get('DockerRootDir')
                }
            except json.JSONDecodeError:
                info['docker_info_parse_error'] = "Failed to parse docker info JSON"
        else:
            info['docker_info_error'] = stderr
        
        # Docker Compose version
        success, stdout, stderr = self.execute_command("docker compose version")
        if success:
            info['docker_compose_version'] = stdout
        else:
            # Try legacy docker-compose
            success, stdout, stderr = self.execute_command("docker-compose --version")
            if success:
                info['docker_compose_version'] = stdout
            else:
                info['docker_compose_error'] = stderr
        
        return info
    
    def get_zfs_info(self) -> Dict[str, Any]:
        """Get ZFS system information from host"""
        info = {}
        
        # ZFS version
        success, stdout, stderr = self.execute_host_command("zfs version")
        if success:
            info['zfs_version'] = stdout
        else:
            info['zfs_version_error'] = stderr
        
        # Check if ZFS utilities exist
        success, stdout, stderr = self.execute_host_command("which zfs")
        if success:
            info['zfs_path'] = stdout
        else:
            info['zfs_path_error'] = stderr
            
        success, stdout, stderr = self.execute_host_command("which zpool")
        if success:
            info['zpool_path'] = stdout
        else:
            info['zpool_path_error'] = stderr
        
        # Check ZFS kernel modules
        success, stdout, stderr = self.execute_host_command("lsmod | grep zfs")
        if success:
            info['zfs_modules'] = stdout
        else:
            info['zfs_modules_error'] = stderr
        
        # List ZFS pools
        success, stdout, stderr = self.execute_host_command("zpool list -H -o name,size,free,health")
        if success:
            pools = []
            for line in stdout.split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) >= 4:
                        pools.append({
                            'name': parts[0],
                            'size': parts[1],
                            'free': parts[2],
                            'health': parts[3]
                        })
            info['zfs_pools'] = pools
        else:
            info['zfs_pools_error'] = stderr
            
        # Get devices used by each pool
        pool_devices = {}
        if 'zfs_pools' in info:
            for pool in info['zfs_pools']:
                pool_name = pool['name']
                success, stdout, stderr = self.execute_host_command(f"zpool status {pool_name} | awk '/^\t/ {{print $1}}' | grep -v '^[[:space:]]*$' | grep -v '{pool_name}' | head -20")
                if success and stdout.strip():
                    devices = []
                    for line in stdout.split('\n'):
                        device = line.strip()
                        if device and not device.startswith('mirror') and not device.startswith('raidz'):
                            # Handle both /dev/sdb and sdb formats
                            if not device.startswith('/dev/'):
                                device = f'/dev/{device}'
                            devices.append(device)
                    pool_devices[pool_name] = devices
            info['pool_devices'] = pool_devices
        
        return info
    
    def get_host_system_resources(self) -> Dict[str, Any]:
        """Get host system resource information"""
        resources = {}
        
        # Memory information
        success, stdout, stderr = self.execute_host_command("cat /proc/meminfo | grep MemTotal")
        if success:
            # Extract memory in KB and convert to GB
            mem_kb = int(stdout.split()[1])
            resources['memory_total_gb'] = round(mem_kb / 1024 / 1024, 2)
        else:
            resources['memory_error'] = stderr
        
        # CPU information
        success, stdout, stderr = self.execute_host_command("nproc")
        if success:
            resources['cpu_cores'] = int(stdout)
        else:
            resources['cpu_cores_error'] = stderr
        
        # Disk space
        success, stdout, stderr = self.execute_host_command("df -h / | tail -1")
        if success:
            parts = stdout.split()
            if len(parts) >= 4:
                resources['disk_total'] = parts[1]
                resources['disk_used'] = parts[2]
                resources['disk_available'] = parts[3]
                resources['disk_usage_percent'] = parts[4]
        else:
            resources['disk_error'] = stderr
        
        # Load average
        success, stdout, stderr = self.execute_host_command("cat /proc/loadavg")
        if success:
            resources['load_average'] = stdout
        else:
            resources['load_average_error'] = stderr
        
        return resources
    
    def check_network_ports(self, port_range: str = "5432-5500") -> Dict[str, Any]:
        """Check network port availability on host"""
        port_info = {}
        
        # Check if ports in range are in use
        success, stdout, stderr = self.execute_host_command(f"ss -tulpn | grep -E ':(5432|3306|6379|27017)'")
        if success:
            used_ports = []
            for line in stdout.split('\n'):
                if line.strip():
                    used_ports.append(line.strip())
            port_info['used_database_ports'] = used_ports
        else:
            port_info['port_check_error'] = stderr
        
        # Check specific PostgreSQL port range
        success, stdout, stderr = self.execute_host_command("ss -tulpn | grep ':543[2-9]\\|:54[0-9][0-9]\\|:55[0-9][0-9]'")
        if success:
            used_pg_ports = []
            for line in stdout.split('\n'):
                if line.strip():
                    used_pg_ports.append(line.strip())
            port_info['used_postgresql_ports'] = used_pg_ports
        else:
            port_info['postgresql_ports'] = []
        
        return port_info

    def detect_os(self) -> Dict[str, Any]:
        """Detect operating system distribution and version"""
        os_info = {
            'detected': False,
            'distribution': 'unknown',
            'version': 'unknown',
            'codename': 'unknown',
            'package_manager': 'unknown',
            'zfs_installable': False
        }

        # Get OS release information
        success, stdout, stderr = self.execute_host_command("cat /etc/os-release")
        if not success:
            os_info['error'] = f"Failed to read /etc/os-release: {stderr}"
            return os_info

        # Parse os-release file
        os_release = {}
        for line in stdout.split('\n'):
            if '=' in line:
                key, value = line.split('=', 1)
                os_release[key] = value.strip('"')

        # Extract distribution info
        os_info['detected'] = True
        os_info['id'] = os_release.get('ID', 'unknown').lower()
        os_info['id_like'] = os_release.get('ID_LIKE', '').lower()
        os_info['version'] = os_release.get('VERSION_ID', 'unknown')
        os_info['codename'] = os_release.get('VERSION_CODENAME', 'unknown')
        os_info['pretty_name'] = os_release.get('PRETTY_NAME', 'Unknown OS')

        # Determine distribution family
        dist_id = os_info['id']
        dist_like = os_info['id_like']

        if dist_id in ['ubuntu', 'debian'] or 'debian' in dist_like:
            os_info['distribution'] = 'debian'
            os_info['package_manager'] = 'apt'
            os_info['zfs_installable'] = True
        elif dist_id in ['rhel', 'centos', 'rocky', 'almalinux', 'fedora'] or 'rhel' in dist_like or 'fedora' in dist_like:
            os_info['distribution'] = 'rhel'
            os_info['package_manager'] = 'dnf' if dist_id == 'fedora' else 'yum'
            os_info['zfs_installable'] = True
        elif dist_id in ['arch', 'manjaro']:
            os_info['distribution'] = 'arch'
            os_info['package_manager'] = 'pacman'
            os_info['zfs_installable'] = True
        else:
            os_info['distribution'] = 'unsupported'
            os_info['zfs_installable'] = False

        return os_info

    def generate_zfs_install_script(self, os_info: Dict[str, Any] = None) -> Tuple[bool, str, str]:
        """Generate ZFS installation commands based on OS"""
        if os_info is None:
            os_info = self.detect_os()

        if not os_info.get('zfs_installable'):
            return False, "", f"ZFS installation not supported on {os_info.get('pretty_name', 'unknown OS')}"

        distribution = os_info.get('distribution')
        dist_id = os_info.get('id')
        version = os_info.get('version')

        scripts = {
            'debian': {
                'ubuntu': f"""#!/bin/bash
set -e
echo "Installing ZFS on Ubuntu..."
apt-get update
apt-get install -y zfsutils-linux
modprobe zfs
echo "ZFS installation complete!"
zfs version
""",
                'debian': f"""#!/bin/bash
set -e
echo "Installing ZFS on Debian..."
apt-get update
apt-get install -y linux-headers-$(uname -r)
apt-get install -y zfsutils-linux
modprobe zfs
echo "ZFS installation complete!"
zfs version
"""
            },
            'rhel': f"""#!/bin/bash
set -e
echo "Installing ZFS on RHEL/CentOS/Rocky Linux..."
# Install EPEL repository
yum install -y epel-release

# Install kernel headers and development tools
yum install -y kernel-devel kernel-headers

# Install ZFS repository
yum install -y https://zfsonlinux.org/epel/zfs-release-2-2$(rpm --eval "%{{dist}}").noarch.rpm || true

# Import GPG key
rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-zfsonlinux || true

# Install ZFS
yum install -y zfs

# Load ZFS module
modprobe zfs

echo "ZFS installation complete!"
zfs version
""",
            'arch': f"""#!/bin/bash
set -e
echo "Installing ZFS on Arch Linux..."
pacman -Sy --noconfirm
pacman -S --noconfirm linux-headers zfs-dkms zfs-utils
modprobe zfs
echo "ZFS installation complete!"
zfs version
"""
        }

        if distribution == 'debian':
            script = scripts['debian'].get(dist_id, scripts['debian']['ubuntu'])
        elif distribution in scripts:
            script = scripts[distribution]
        else:
            return False, "", f"No installation script available for {distribution}"

        return True, script, "Installation script generated successfully"

    def install_zfs(self, os_info: Dict[str, Any] = None) -> Tuple[bool, str, str]:
        """Install ZFS utilities on the host system"""
        logger.info("Starting ZFS installation...")

        # Generate installation script
        success, script, error_msg = self.generate_zfs_install_script(os_info)
        if not success:
            return False, "", error_msg

        # Create temporary script file on host
        script_path = "/tmp/install_zfs.sh"

        # Encode script in base64 to avoid quoting/escaping issues
        script_bytes = script.encode('utf-8')
        script_b64 = base64.b64encode(script_bytes).decode('utf-8')

        # Write script to file using base64 decoding
        # This approach avoids all shell escaping issues
        write_cmd = f"echo '{script_b64}' | base64 -d > {script_path}"
        logger.info(f"Writing installation script to {script_path}")
        success, stdout, stderr = self.execute_host_command(write_cmd, timeout=10)
        if not success:
            logger.error(f"Failed to write script: {stderr}")
            return False, "", f"Failed to create installation script: {stderr}"

        # Verify the script was written
        success, stdout, stderr = self.execute_host_command(f"test -f {script_path} && echo 'exists'")
        if not success or 'exists' not in stdout:
            return False, "", f"Script file was not created at {script_path}"

        # Make script executable
        logger.info(f"Making script executable")
        success, stdout, stderr = self.execute_host_command(f"chmod +x {script_path}")
        if not success:
            logger.error(f"Failed to chmod script: {stderr}")
            return False, "", f"Failed to make script executable: {stderr}"

        # Execute installation script with extended timeout (5 minutes)
        logger.info(f"Executing ZFS installation script: {script_path}")
        success, stdout, stderr = self.execute_host_command(f"bash {script_path}", timeout=300)

        # Clean up script
        self.execute_host_command(f"rm -f {script_path}")

        if success:
            logger.info("ZFS installation completed successfully")
            return True, stdout, "ZFS installed successfully"
        else:
            logger.error(f"ZFS installation failed: {stderr}")
            return False, stdout, f"Installation failed: {stderr}"