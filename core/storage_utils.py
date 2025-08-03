import subprocess
import os
import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class StorageUtils:
    """Utility class for storage operations and ZFS management"""
    
    def __init__(self):
        self.host_command_prefix = ["nsenter", "-t", "1", "-m", "-p"]
    
    def execute_host_command(self, command: str) -> Tuple[bool, str, str]:
        """Execute command on host system from container"""
        try:
            full_command = self.host_command_prefix + command.split()
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def get_available_disks(self) -> List[Dict]:
        """Get list of available disks that can be used for ZFS"""
        disks = []
        
        # Get block devices
        success, stdout, stderr = self.execute_host_command("lsblk -J -o NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE")
        if not success:
            return disks
        
        try:
            lsblk_data = json.loads(stdout)
            for device in lsblk_data.get('blockdevices', []):
                if device.get('type') == 'disk':
                    # Skip disks that are already mounted or have filesystems
                    if not device.get('mountpoint') and not device.get('fstype'):
                        disk_info = {
                            'name': device['name'],
                            'path': f"/dev/{device['name']}",
                            'size': device['size'],
                            'type': 'disk',
                            'available': True
                        }
                        
                        # Check if disk has partitions
                        partitions = device.get('children', [])
                        if partitions:
                            mounted_partitions = [p for p in partitions if p.get('mountpoint')]
                            if mounted_partitions:
                                disk_info['available'] = False
                                disk_info['reason'] = 'Has mounted partitions'
                        
                        disks.append(disk_info)
                    else:
                        # Include but mark as unavailable
                        disks.append({
                            'name': device['name'],
                            'path': f"/dev/{device['name']}",
                            'size': device['size'],
                            'type': 'disk',
                            'available': False,
                            'reason': f"Mounted at {device.get('mountpoint', 'unknown')} or has filesystem {device.get('fstype', '')}"
                        })
        except json.JSONDecodeError:
            pass
        
        return disks
    
    def get_disk_info(self, disk_path: str) -> Dict:
        """Get detailed information about a specific disk"""
        # Get basic disk info
        success, stdout, stderr = self.execute_host_command(f"lsblk -J {disk_path}")
        if not success:
            return {'error': stderr}
        
        try:
            lsblk_data = json.loads(stdout)
            device = lsblk_data.get('blockdevices', [{}])[0]
            
            info = {
                'name': device.get('name'),
                'size': device.get('size'),
                'type': device.get('type'),
                'model': None,
                'serial': None,
                'available': True
            }
            
            # Get additional disk information
            success, stdout, stderr = self.execute_host_command(f"smartctl -i {disk_path} 2>/dev/null")
            if success:
                for line in stdout.split('\n'):
                    if 'Device Model:' in line:
                        info['model'] = line.split(':', 1)[1].strip()
                    elif 'Serial Number:' in line:
                        info['serial'] = line.split(':', 1)[1].strip()
            
            return info
            
        except json.JSONDecodeError:
            return {'error': 'Failed to parse disk information'}
    
    def get_available_space(self) -> Dict:
        """Get available disk space on the host"""
        success, stdout, stderr = self.execute_host_command("df -h /")
        if not success:
            return {'error': stderr}
        
        lines = stdout.strip().split('\n')
        if len(lines) < 2:
            return {'error': 'Invalid df output'}
        
        # Parse df output
        parts = lines[1].split()
        return {
            'total': parts[1],
            'used': parts[2],
            'available': parts[3],
            'usage_percent': parts[4],
            'filesystem': parts[0],
            'mount_point': parts[5] if len(parts) > 5 else '/'
        }
    
    def validate_existing_pool(self, pool_name: str) -> Dict:
        """Validate an existing ZFS pool"""
        # Check if pool exists
        success, stdout, stderr = self.execute_host_command(f"zpool status {pool_name}")
        if not success:
            return {
                'valid': False,
                'message': f"Pool '{pool_name}' not found or not accessible",
                'error': stderr
            }
        
        # Get pool health
        success, stdout, stderr = self.execute_host_command(f"zpool list -H -o name,health,size,free {pool_name}")
        if not success:
            return {
                'valid': False,
                'message': f"Failed to get pool information",
                'error': stderr
            }
        
        parts = stdout.split('\t')
        if len(parts) < 4:
            return {
                'valid': False,
                'message': "Invalid pool information format"
            }
        
        health = parts[1]
        size = parts[2]
        free = parts[3]
        
        if health != 'ONLINE':
            return {
                'valid': False,
                'message': f"Pool health is '{health}', expected 'ONLINE'"
            }
        
        return {
            'valid': True,
            'message': f"Pool '{pool_name}' is healthy and available",
            'health': health,
            'size': size,
            'free': free
        }
    
    def validate_dedicated_disks(self, disk_paths: List[str]) -> Dict:
        """Validate disks for dedicated ZFS pool creation"""
        if not disk_paths:
            return {'valid': False, 'message': 'No disks specified'}
        
        validated_disks = []
        errors = []
        
        for disk_path in disk_paths:
            if not disk_path.startswith('/dev/'):
                errors.append(f"Invalid disk path: {disk_path}")
                continue
            
            # Check if disk exists
            success, stdout, stderr = self.execute_host_command(f"test -b {disk_path}")
            if not success:
                errors.append(f"Disk not found: {disk_path}")
                continue
            
            # Check if disk is already in use
            success, stdout, stderr = self.execute_host_command(f"zpool status | grep {disk_path}")
            if success:
                errors.append(f"Disk already in ZFS pool: {disk_path}")
                continue
            
            # Check if disk has active filesystem (but allow GPT/ZFS labels)
            success, stdout, stderr = self.execute_host_command(f"blkid {disk_path}")
            if success and stdout.strip():
                # Allow ZFS labels and GPT partition tables, but reject other filesystems
                # If it only has PTTYPE="gpt" or zfs_member, that's acceptable
                if 'PTTYPE="gpt"' in stdout or 'zfs_member' in stdout:
                    # GPT partition table or ZFS labels are OK - ZFS can overwrite them
                    pass
                elif ' TYPE=' in stdout:  # Space before TYPE to avoid matching PTTYPE
                    # Has a real filesystem (ext4, xfs, etc.) - reject
                    fs_type = stdout.split(' TYPE="')[1].split('"')[0] if ' TYPE="' in stdout else 'unknown'
                    errors.append(f"Disk has active filesystem ({fs_type}): {disk_path}")
                    continue
            
            disk_info = self.get_disk_info(disk_path)
            validated_disks.append({
                'path': disk_path,
                'info': disk_info
            })
        
        if errors:
            return {
                'valid': False,
                'message': 'Disk validation failed',
                'errors': errors,
                'validated_disks': validated_disks
            }
        
        return {
            'valid': True,
            'message': f"All {len(validated_disks)} disks are valid for ZFS pool creation",
            'validated_disks': validated_disks
        }
    
    def validate_image_file_config(self, image_path: str, size_gb: int) -> Dict:
        """Validate image file configuration"""
        if not image_path:
            return {'valid': False, 'message': 'Image file path is required'}
        
        if size_gb < 1:
            return {'valid': False, 'message': 'Image file size must be at least 1GB'}
        
        # Check parent directory exists and is writable
        parent_dir = os.path.dirname(image_path)
        success, stdout, stderr = self.execute_host_command(f"test -d {parent_dir} -a -w {parent_dir}")
        if not success:
            return {
                'valid': False,
                'message': f"Parent directory '{parent_dir}' does not exist or is not writable"
            }
        
        # Check if file already exists
        success, stdout, stderr = self.execute_host_command(f"test -f {image_path}")
        if success:
            return {
                'valid': False,
                'message': f"Image file already exists: {image_path}"
            }
        
        # Check available space
        space_info = self.get_available_space()
        if 'available' in space_info:
            available_gb = self._parse_size_to_gb(space_info['available'])
            if available_gb < size_gb:
                return {
                    'valid': False,
                    'message': f"Insufficient disk space. Required: {size_gb}GB, Available: {available_gb}GB"
                }
        
        return {
            'valid': True,
            'message': f"Image file configuration is valid ({size_gb}GB at {image_path})"
        }
    
    def validate_directory_storage(self, directory: str) -> Dict:
        """Validate directory-based storage"""
        if not directory:
            return {'valid': False, 'message': 'Storage directory is required'}
        
        # Check if directory exists or can be created
        success, stdout, stderr = self.execute_host_command(f"mkdir -p {directory}")
        if not success:
            return {
                'valid': False,
                'message': f"Cannot create directory: {directory}",
                'error': stderr
            }
        
        # Check if directory is writable
        success, stdout, stderr = self.execute_host_command(f"test -w {directory}")
        if not success:
            return {
                'valid': False,
                'message': f"Directory is not writable: {directory}"
            }
        
        return {
            'valid': True,
            'message': f"Directory storage is valid: {directory}"
        }
    
    def validate_multi_disk_config(self, disk_paths: List[str], pool_type: str) -> Dict:
        """Validate multi-disk ZFS configuration"""
        min_disks = {
            'mirror': 2,
            'raidz1': 3,
            'raidz2': 4,
            'raidz3': 5
        }
        
        required_disks = min_disks.get(pool_type, 2)
        if len(disk_paths) < required_disks:
            return {
                'valid': False,
                'message': f"Pool type '{pool_type}' requires at least {required_disks} disks, got {len(disk_paths)}"
            }
        
        # Validate individual disks
        disk_validation = self.validate_dedicated_disks(disk_paths)
        if not disk_validation['valid']:
            return disk_validation
        
        return {
            'valid': True,
            'message': f"Multi-disk configuration valid: {len(disk_paths)} disks for {pool_type}",
            'validated_disks': disk_validation['validated_disks']
        }
    
    def validate_hybrid_config(self, cache_disks: List[str], data_disks: List[str], pool_type: str) -> Dict:
        """Validate hybrid storage configuration"""
        if not cache_disks or not data_disks:
            return {
                'valid': False,
                'message': 'Both cache and data disks are required for hybrid storage'
            }
        
        # Validate all disks
        all_disks = cache_disks + data_disks
        disk_validation = self.validate_dedicated_disks(all_disks)
        if not disk_validation['valid']:
            return disk_validation
        
        # Validate data disk configuration
        data_validation = self.validate_multi_disk_config(data_disks, pool_type)
        if not data_validation['valid']:
            return data_validation
        
        return {
            'valid': True,
            'message': f"Hybrid configuration valid: {len(cache_disks)} cache + {len(data_disks)} data disks",
            'cache_disks': cache_disks,
            'data_disks': data_disks
        }
    
    def create_image_file_pool(self, pool_name: str, image_path: str, size_gb: int, 
                              sparse: bool = True, compression: str = 'lz4', 
                              dedup: bool = False) -> Dict:
        """Create ZFS pool using an image file"""
        try:
            # Create image file
            if sparse:
                success, stdout, stderr = self.execute_host_command(
                    f"truncate -s {size_gb}G {image_path}"
                )
            else:
                success, stdout, stderr = self.execute_host_command(
                    f"dd if=/dev/zero of={image_path} bs=1G count={size_gb}"
                )
            
            if not success:
                return {
                    'success': False,
                    'message': f"Failed to create image file: {stderr}"
                }
            
            # Create ZFS pool
            zpool_cmd = f"zpool create {pool_name} {image_path}"
            success, stdout, stderr = self.execute_host_command(zpool_cmd)
            if not success:
                # Clean up image file
                self.execute_host_command(f"rm -f {image_path}")
                return {
                    'success': False,
                    'message': f"Failed to create ZFS pool: {stderr}"
                }
            
            # Set pool properties
            if compression != 'off':
                self.execute_host_command(f"zfs set compression={compression} {pool_name}")
            
            if dedup:
                self.execute_host_command(f"zfs set dedup=on {pool_name}")
            
            return {
                'success': True,
                'message': f"ZFS pool '{pool_name}' created successfully using image file",
                'pool_name': pool_name,
                'image_path': image_path,
                'size_gb': size_gb
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Unexpected error creating image file pool: {str(e)}"
            }
    
    def create_dedicated_disk_pool(self, pool_name: str, disk_paths: List[str], 
                                  pool_type: str = 'single', compression: str = 'lz4', 
                                  dedup: bool = False) -> Dict:
        """Create ZFS pool using dedicated disks"""
        try:
            if pool_type == 'single':
                vdev_spec = ' '.join(disk_paths)
            elif pool_type == 'mirror':
                vdev_spec = f"mirror {' '.join(disk_paths)}"
            elif pool_type in ['raidz1', 'raidz2', 'raidz3']:
                vdev_spec = f"{pool_type} {' '.join(disk_paths)}"
            else:
                return {
                    'success': False,
                    'message': f"Unsupported pool type: {pool_type}"
                }
            
            # Create ZFS pool
            zpool_cmd = f"zpool create {pool_name} {vdev_spec}"
            success, stdout, stderr = self.execute_host_command(zpool_cmd)
            if not success:
                return {
                    'success': False,
                    'message': f"Failed to create ZFS pool: {stderr}"
                }
            
            # Set pool properties
            if compression != 'off':
                self.execute_host_command(f"zfs set compression={compression} {pool_name}")
            
            if dedup:
                self.execute_host_command(f"zfs set dedup=on {pool_name}")
            
            return {
                'success': True,
                'message': f"ZFS pool '{pool_name}' created successfully using {len(disk_paths)} disk(s)",
                'pool_name': pool_name,
                'disks': disk_paths,
                'pool_type': pool_type
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Unexpected error creating dedicated disk pool: {str(e)}"
            }
    
    def _parse_size_to_gb(self, size_str: str) -> float:
        """Parse size string (like '100G', '1.5T') to GB"""
        if not size_str:
            return 0
        
        # Remove any trailing 'B'
        size_str = size_str.rstrip('B')
        
        # Extract number and unit
        match = re.match(r'([0-9.]+)([KMGT]?)', size_str.upper())
        if not match:
            return 0
        
        value = float(match.group(1))
        unit = match.group(2)
        
        multipliers = {
            '': 1 / (1024**3),  # bytes to GB
            'K': 1 / (1024**2), # KB to GB
            'M': 1 / 1024,      # MB to GB
            'G': 1,             # GB to GB
            'T': 1024           # TB to GB
        }
        
        return value * multipliers.get(unit, 1)
    
    def setup_existing_pool(self, pool_name: str) -> Dict:
        """Setup using an existing ZFS pool"""
        validation_result = self.validate_existing_pool(pool_name)
        if validation_result['valid']:
            return {
                'success': True,
                'message': f"Using existing ZFS pool '{pool_name}'",
                'pool_name': pool_name
            }
        else:
            return {
                'success': False,
                'message': validation_result['message']
            }
    
    def setup_directory_storage(self, directory: str) -> Dict:
        """Setup directory-based storage"""
        try:
            # Create directory if it doesn't exist
            success, stdout, stderr = self.execute_host_command(f"mkdir -p {directory}")
            if not success:
                return {
                    'success': False,
                    'message': f"Failed to create directory: {stderr}"
                }
            
            # Set permissions
            success, stdout, stderr = self.execute_host_command(f"chmod 755 {directory}")
            if not success:
                return {
                    'success': False,
                    'message': f"Failed to set directory permissions: {stderr}"
                }
            
            return {
                'success': True,
                'message': f"Directory storage configured at {directory}",
                'storage_directory': directory
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Unexpected error setting up directory storage: {str(e)}"
            }
    
    def create_multi_disk_pool(self, pool_name: str, disk_paths: List[str], 
                              pool_type: str, compression: str = 'lz4', 
                              dedup: bool = False) -> Dict:
        """Create multi-disk ZFS pool with redundancy"""
        # This is the same as create_dedicated_disk_pool but with explicit multi-disk handling
        return self.create_dedicated_disk_pool(pool_name, disk_paths, pool_type, compression, dedup)
    
    def create_hybrid_pool(self, pool_name: str, cache_disks: List[str], 
                          data_disks: List[str], pool_type: str = 'single',
                          compression: str = 'lz4', dedup: bool = False) -> Dict:
        """Create hybrid ZFS pool with cache and data disks"""
        try:
            # Create main pool with data disks
            if pool_type == 'single':
                vdev_spec = ' '.join(data_disks)
            elif pool_type == 'mirror':
                vdev_spec = f"mirror {' '.join(data_disks)}"
            elif pool_type in ['raidz1', 'raidz2', 'raidz3']:
                vdev_spec = f"{pool_type} {' '.join(data_disks)}"
            else:
                return {
                    'success': False,
                    'message': f"Unsupported pool type: {pool_type}"
                }
            
            # Create ZFS pool with data disks
            zpool_cmd = f"zpool create {pool_name} {vdev_spec}"
            success, stdout, stderr = self.execute_host_command(zpool_cmd)
            if not success:
                return {
                    'success': False,
                    'message': f"Failed to create ZFS pool: {stderr}"
                }
            
            # Add cache disks
            for cache_disk in cache_disks:
                cache_cmd = f"zpool add {pool_name} cache {cache_disk}"
                success, stdout, stderr = self.execute_host_command(cache_cmd)
                if not success:
                    # Log warning but don't fail the entire operation
                    print(f"Warning: Failed to add cache disk {cache_disk}: {stderr}")
            
            # Set pool properties
            if compression != 'off':
                self.execute_host_command(f"zfs set compression={compression} {pool_name}")
            
            if dedup:
                self.execute_host_command(f"zfs set dedup=on {pool_name}")
            
            return {
                'success': True,
                'message': f"Hybrid ZFS pool '{pool_name}' created with {len(data_disks)} data disks and {len(cache_disks)} cache disks",
                'pool_name': pool_name,
                'data_disks': data_disks,
                'cache_disks': cache_disks,
                'pool_type': pool_type
            }
            
        except Exception as e:
            return {
                'success': False,
                'message': f"Unexpected error creating hybrid pool: {str(e)}"
            }