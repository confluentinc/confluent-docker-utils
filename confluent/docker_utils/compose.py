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
from enum import Enum, StrEnum


class ContainerStatus(Enum):
    """Container status constants."""
    RUNNING = "running"
    EXITED = "exited"


class DockerComposeLabels(StrEnum):
    """Docker Compose label constants."""
    PROJECT = "com.docker.compose.project"
    SERVICE = "com.docker.compose.service"


class ComposeConfigKeys(StrEnum):
    """Docker Compose configuration keys."""
    VERSION = "version"
    SERVICES = "services"
    IMAGE = "image"
    BUILD = "build"
    COMMAND = "command"
    ENVIRONMENT = "environment"
    PORTS = "ports"
    VOLUMES = "volumes"
    WORKING_DIR = "working_dir"


class DockerStateKeys(StrEnum):
    """Docker container state keys."""
    STATE = "State"
    EXIT_CODE = "ExitCode"
    ID = "Id"
    STATUS = "Status"


FILE_READ_MODE = "r"
VOLUME_READ_WRITE_MODE = "rw"
VOLUME_BIND_MODE = "bind"

CURRENT_DIR_PREFIX = "./"


class Separators(StrEnum):
    """Common string separators."""
    UNDERSCORE = "_"
    COLON = ":"
    EQUALS = "="


class Defaults(StrEnum):
    """Default configuration values."""
    COMPOSE_VERSION = "3"
    CONTAINER_SUFFIX = "_1"


class ComposeConfig:
    """Handles docker-compose.yml parsing and configuration management."""
    
    def __init__(self, working_dir: str, config_file: str):
        self.working_dir = working_dir
        self.config_file_path = os.path.join(working_dir, config_file)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load and parse docker-compose.yml file."""
        with open(self.config_file_path, FILE_READ_MODE) as f:
            config = yaml.safe_load(f)
        
        if ComposeConfigKeys.VERSION not in config:
            config[ComposeConfigKeys.VERSION] = Defaults.COMPOSE_VERSION
        
        if ComposeConfigKeys.SERVICES not in config:
            raise ValueError("docker-compose.yml must contain 'services' section")
        
        return config
    
    def get_services(self) -> Dict[str, Dict[str, Any]]:
        """Get all service definitions."""
        return self.config.get(ComposeConfigKeys.SERVICES, {})
    
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
        parts = self.name.split(Separators.UNDERSCORE)
        if len(parts) >= 2:
            return parts[1]
        return self.name
    
    @property
    def is_running(self) -> bool:
        """Check if container is running."""
        self.container.reload()
        return self.container.status == ContainerStatus.RUNNING.value
    
    @property
    def exit_code(self) -> Optional[int]:
        """Get container exit code."""
        self.container.reload()
        if self.container.status == ContainerStatus.EXITED.value:
            return self.container.attrs[DockerStateKeys.STATE][DockerStateKeys.EXIT_CODE]
        return None
    
    def create_exec(self, command: str) -> str:
        """Create an exec instance and return its ID."""
        exec_create_result = self.container.client.api.exec_create(self.container.id, command)
        return exec_create_result[DockerStateKeys.ID]
    
    def start_exec(self, exec_id: str) -> bytes:
        """Start an exec instance by ID and return output."""
        output = self.container.client.api.exec_start(exec_id)
        return output
    
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
        
        for container in containers:
            try:
                container.stop()
            except Exception as e:
                print(f"Error stopping container {container.name}: {e}")
        
        for container in containers:
            try:
                container.remove()
            except Exception as e:
                print(f"Error removing container {container.name}: {e}")
    
    def containers(self, service_names: Optional[List[str]] = None, stopped: bool = False) -> List[ComposeContainer]:
        """Get containers for the project."""
        filters = {
            'label': f'{DockerComposeLabels.PROJECT}={self.name}'
        }
        
        if not stopped:
            filters['status'] = ContainerStatus.RUNNING.value
        
        docker_containers = self.client.containers.list(all=stopped, filters=filters)
        compose_containers = [ComposeContainer(c) for c in docker_containers]
        
        if service_names:
            filtered = []
            for container in compose_containers:
                service_label = container.container.labels.get(DockerComposeLabels.SERVICE)
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
        
        container_config = self._build_container_config(service_name, service_config)
        
        container_name = f"{self.name}{Separators.UNDERSCORE}{service_name}{Defaults.CONTAINER_SUFFIX}"
        try:
            existing = self.client.containers.get(container_name)
            if existing.status != ContainerStatus.RUNNING.value:
                existing.start()
            return ComposeContainer(existing)
        except docker.errors.NotFound:
            pass
        
        container = self.client.containers.run(
            name=container_name,
            detach=True,
            labels={
                DockerComposeLabels.PROJECT: self.name,
                DockerComposeLabels.SERVICE: service_name,
            },
            **container_config
        )
        
        return ComposeContainer(container)
    
    def _build_container_config(self, service_name: str, service_config: Dict[str, Any]) -> Dict[str, Any]:
        """Build Docker SDK container configuration from compose service config."""
        config = {}
        
        if ComposeConfigKeys.IMAGE in service_config:
            config[ComposeConfigKeys.IMAGE] = service_config[ComposeConfigKeys.IMAGE]
        elif ComposeConfigKeys.BUILD in service_config:
            # For simplicity, we'll require pre-built images
            # In a full implementation, you'd handle building here
            raise NotImplementedError("Building images not implemented in this example")
        
        if ComposeConfigKeys.COMMAND in service_config:
            config[ComposeConfigKeys.COMMAND] = service_config[ComposeConfigKeys.COMMAND]
        
        if ComposeConfigKeys.ENVIRONMENT in service_config:
            env = service_config[ComposeConfigKeys.ENVIRONMENT]
            if isinstance(env, list):
                env_dict = {}
                for item in env:
                    if Separators.EQUALS in item:
                        key, value = item.split(Separators.EQUALS, 1)
                        env_dict[key] = value
                config[ComposeConfigKeys.ENVIRONMENT] = env_dict
            else:
                config[ComposeConfigKeys.ENVIRONMENT] = env
        
        if ComposeConfigKeys.PORTS in service_config:
            ports = {}
            for port_mapping in service_config[ComposeConfigKeys.PORTS]:
                if Separators.COLON in str(port_mapping):
                    host_port, container_port = str(port_mapping).split(Separators.COLON, 1)
                    ports[container_port] = host_port
                else:
                    ports[str(port_mapping)] = None
            config[ComposeConfigKeys.PORTS] = ports
        
        if ComposeConfigKeys.VOLUMES in service_config:
            volumes = {}
            for volume in service_config[ComposeConfigKeys.VOLUMES]:
                if Separators.COLON in volume:
                    host_path, container_path = volume.split(Separators.COLON, 1)
                    if host_path.startswith(CURRENT_DIR_PREFIX):
                        host_path = os.path.join(self.config.working_dir, host_path[2:])
                    volumes[host_path] = {VOLUME_BIND_MODE: container_path, 'mode': VOLUME_READ_WRITE_MODE}
            config[ComposeConfigKeys.VOLUMES] = volumes
        
        if ComposeConfigKeys.WORKING_DIR in service_config:
            config[ComposeConfigKeys.WORKING_DIR] = service_config[ComposeConfigKeys.WORKING_DIR]
        
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
