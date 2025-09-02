#!/usr/bin/env python
"""
Modern replacement for docker-compose Python library using Docker SDK directly.
Compatible with Python 3.10+ and maintains the same TestCluster interface.
"""

import os
import yaml
import docker
from typing import Dict, List, Optional, Any
import time


class ComposeConfig:
    """Handles docker-compose.yml parsing and configuration management."""
    
    def __init__(self, working_dir: str, config_file: str):
        self.working_dir = working_dir
        self.config_file_path = os.path.join(working_dir, config_file)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and parse docker-compose.yml file."""
        with open(self.config_file_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Normalize the config structure
        if 'version' not in config:
            config['version'] = '3'
        
        if 'services' not in config:
            raise ValueError("docker-compose.yml must contain 'services' section")
        
        return config
    
    def get_services(self) -> Dict[str, Dict[str, Any]]:
        """Get all service definitions."""
        return self.config.get('services', {})
    
    def get_service(self, service_name: str) -> Dict[str, Any]:
        """Get a specific service definition."""
        services = self.get_services()
        if service_name not in services:
            raise ValueError(f"Service '{service_name}' not found in compose file")
        return services[service_name]


class ComposeContainer:
    """Wrapper around Docker SDK container to provide compose-like interface."""
    
    def __init__(self, container: docker.models.containers.Container):
        self.container = container
        self._service_name = None
    
    @property
    def id(self) -> str:
        return self.container.id
    
    @property
    def name(self) -> str:
        return self.container.name
    
    @property
    def name_without_project(self) -> str:
        """Extract service name from container name."""
        if self._service_name:
            return self._service_name
        # Container names usually follow pattern: projectname_servicename_1
        parts = self.name.split('_')
        if len(parts) >= 2:
            return parts[1]  # service name
        return self.name
    
    @property
    def is_running(self) -> bool:
        """Check if container is running."""
        self.container.reload()
        return self.container.status == 'running'
    
    @property
    def exit_code(self) -> Optional[int]:
        """Get container exit code."""
        self.container.reload()
        if self.container.status == 'exited':
            return self.container.attrs['State']['ExitCode']
        return None
    
    def create_exec(self, command: str) -> str:
        """Create an exec instance."""
        exec_instance = self.container.exec_run(command, detach=True)
        return exec_instance.output
    
    def start_exec(self, exec_id: str) -> bytes:
        """Start an exec instance and return output."""
        # For our simplified implementation, we'll run the command directly
        # In a full implementation, you'd store the exec_id and run it here
        return exec_id  # This is actually the output from create_exec
    
    def logs(self) -> bytes:
        """Get container logs."""
        return self.container.logs()
    
    def stop(self):
        """Stop the container."""
        self.container.stop()
    
    def remove(self):
        """Remove the container."""
        self.container.remove()


class ComposeProject:
    """
    Replacement for docker-compose Project class using Docker SDK.
    Provides similar interface for managing multi-container applications.
    """
    
    def __init__(self, name: str, config: ComposeConfig, client: docker.DockerClient):
        self.name = name
        self.config = config
        self.client = client
        self._containers = {}
    
    def up(self, services: Optional[List[str]] = None):
        """Start all services (equivalent to docker-compose up)."""
        services_to_start = services or list(self.config.get_services().keys())
        
        for service_name in services_to_start:
            self._start_service(service_name)
    
    def down(self, remove_images=None, remove_volumes=False, remove_orphans=False):
        """Stop and remove all containers (equivalent to docker-compose down)."""
        containers = self.containers()
        
        # Stop all containers
        for container in containers:
            try:
                container.stop()
            except Exception as e:
                print(f"Error stopping container {container.name}: {e}")
        
        # Remove containers
        for container in containers:
            try:
                container.remove()
            except Exception as e:
                print(f"Error removing container {container.name}: {e}")
    
    def containers(self, service_names: Optional[List[str]] = None, stopped: bool = False) -> List[ComposeContainer]:
        """Get containers for the project."""
        filters = {
            'label': f'com.docker.compose.project={self.name}'
        }
        
        if not stopped:
            filters['status'] = 'running'
        
        docker_containers = self.client.containers.list(all=stopped, filters=filters)
        compose_containers = [ComposeContainer(c) for c in docker_containers]
        
        if service_names:
            # Filter by service names
            filtered = []
            for container in compose_containers:
                service_label = container.container.labels.get('com.docker.compose.service')
                if service_label in service_names:
                    filtered.append(container)
            return filtered
        
        return compose_containers
    
    def get_service(self, service_name: str):
        """Get a service object."""
        return ComposeService(service_name, self)
    
    def remove_stopped(self):
        """Remove stopped containers."""
        stopped_containers = self.containers(stopped=True)
        for container in stopped_containers:
            if not container.is_running:
                try:
                    container.remove()
                except Exception as e:
                    print(f"Error removing stopped container {container.name}: {e}")
    
    def _start_service(self, service_name: str):
        """Start a specific service."""
        service_config = self.config.get_service(service_name)
        
        # Build container configuration
        container_config = self._build_container_config(service_name, service_config)
        
        # Check if container already exists
        container_name = f"{self.name}_{service_name}_1"
        try:
            existing = self.client.containers.get(container_name)
            if existing.status != 'running':
                existing.start()
            return ComposeContainer(existing)
        except docker.errors.NotFound:
            pass
        
        # Create and start new container
        container = self.client.containers.run(
            name=container_name,
            detach=True,
            labels={
                'com.docker.compose.project': self.name,
                'com.docker.compose.service': service_name,
            },
            **container_config
        )
        
        return ComposeContainer(container)
    
    def _build_container_config(self, service_name: str, service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build Docker SDK container configuration from compose service config."""
        config = {}
        
        # Image
        if 'image' in service_config:
            config['image'] = service_config['image']
        elif 'build' in service_config:
            # For simplicity, we'll require pre-built images
            # In a full implementation, you'd handle building here
            raise NotImplementedError("Building images not implemented in this example")
        
        # Command
        if 'command' in service_config:
            config['command'] = service_config['command']
        
        # Environment variables
        if 'environment' in service_config:
            env = service_config['environment']
            if isinstance(env, list):
                # Convert list format to dict
                env_dict = {}
                for item in env:
                    if '=' in item:
                        key, value = item.split('=', 1)
                        env_dict[key] = value
                config['environment'] = env_dict
            else:
                config['environment'] = env
        
        # Ports
        if 'ports' in service_config:
            ports = {}
            for port_mapping in service_config['ports']:
                if ':' in str(port_mapping):
                    host_port, container_port = str(port_mapping).split(':', 1)
                    ports[container_port] = host_port
                else:
                    ports[str(port_mapping)] = None
            config['ports'] = ports
        
        # Volumes
        if 'volumes' in service_config:
            volumes = {}
            for volume in service_config['volumes']:
                if ':' in volume:
                    host_path, container_path = volume.split(':', 1)
                    if host_path.startswith('./'):
                        host_path = os.path.join(self.config.working_dir, host_path[2:])
                    volumes[host_path] = {'bind': container_path, 'mode': 'rw'}
            config['volumes'] = volumes
        
        # Working directory
        if 'working_dir' in service_config:
            config['working_dir'] = service_config['working_dir']
        
        return config


class ComposeService:
    """Represents a service in the compose project."""
    
    def __init__(self, name: str, project: ComposeProject):
        self.name = name
        self.project = project
    
    def get_container(self) -> ComposeContainer:
        """Get the container for this service."""
        containers = self.project.containers([self.name])
        if not containers:
            raise RuntimeError(f"No running container found for service '{self.name}'")
        return containers[0]


def create_docker_client() -> docker.DockerClient:
    """Create a Docker client similar to the old compose.cli.docker_client."""
    return docker.from_env()
