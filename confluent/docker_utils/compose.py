"""
Docker Compose replacement using official Docker SDK.

Drop-in replacement for the deprecated docker-compose Python library.
"""

import os
from typing import Dict, List, Optional, Any

import yaml
import docker
import docker.errors

# Labels for compose container identification
LABEL_PROJECT = "com.docker.compose.project"
LABEL_SERVICE = "com.docker.compose.service"

# Container status
STATUS_RUNNING = "running"
STATUS_EXITED = "exited"

# Container state keys
STATE_KEY = "State"
EXIT_CODE_KEY = "ExitCode"


def create_docker_client() -> docker.DockerClient:
    """Create Docker client from environment."""
    return docker.from_env()


class ComposeConfig:
    """Parses and manages docker-compose.yml configuration."""
    
    def __init__(self, working_dir: str, config_file: str):
        self.working_dir = working_dir
        self.config_file_path = os.path.join(working_dir, config_file)
        self.config = self._load()
    
    def _load(self) -> Dict[str, Any]:
        with open(self.config_file_path) as f:
            config = yaml.safe_load(f)
        if not config or 'services' not in config:
            raise ValueError("Invalid compose file: missing 'services'")
        return config
    
    @property
    def services(self) -> Dict[str, Dict]:
        return self.config.get('services', {})
    
    def get_service(self, name: str) -> Dict[str, Any]:
        if name not in self.services:
            raise ValueError(f"Service '{name}' not found")
        return self.services[name]


class ComposeContainer:
    """Wrapper around Docker SDK container with compose-like interface."""
    
    def __init__(self, container: docker.models.containers.Container):
        self.container = container
    
    @property
    def id(self) -> str:
        return self.container.id
    
    @property
    def name(self) -> str:
        return self.container.name
    
    @property
    def name_without_project(self) -> str:
        """Service name from container."""
        label_service = self.container.labels.get(LABEL_SERVICE)
        if label_service:
            return label_service
        if '_' in self.name:
            return self.name.rsplit('_', 1)[-1]
        return self.name
    
    @property
    def is_running(self) -> bool:
        self.container.reload()
        return self.container.status == STATUS_RUNNING
    
    @property
    def exit_code(self) -> Optional[int]:
        self.container.reload()
        return self.container.attrs[STATE_KEY][EXIT_CODE_KEY] if self.container.status == STATUS_EXITED else None
    
    @property
    def client(self):
        """For backward compatibility."""
        return self.container.client.api
    
    @property
    def inspect_container(self) -> Dict:
        """For backward compatibility."""
        self.container.reload()
        return self.container.attrs
    
    def start(self):
        self.container.start()
    
    def stop(self, timeout: int = 10):
        try:
            self.container.stop(timeout=timeout)
        except docker.errors.APIError:
            pass
    
    def remove(self, force: bool = False, v: bool = False):
        try:
            self.container.remove(force=force, v=v)
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
    
    def wait(self, timeout: Optional[int] = None) -> Dict:
        return self.container.wait(timeout=timeout)
    
    def logs(self) -> bytes:
        return self.container.logs()
    
    def create_exec(self, command: str) -> str:
        """For backward compatibility."""
        return self.container.client.api.exec_create(self.container.id, command)['Id']
    
    def start_exec(self, exec_id: str) -> bytes:
        """For backward compatibility."""
        return self.container.client.api.exec_start(exec_id)
    
    def exec_run(self, command: str) -> bytes:
        return self.container.exec_run(command).output


class ComposeService:
    """Represents a service in the compose project."""
    
    def __init__(self, name: str, project: 'ComposeProject'):
        self.name = name
        self.project = project
    
    def get_container(self) -> ComposeContainer:
        containers = self.project.containers([self.name])
        if not containers:
            raise RuntimeError(f"No running container for service '{self.name}'")
        return containers[0]


class ComposeProject:
    """Manages multi-container compose project using Docker SDK."""
    
    def __init__(self, name: str, config: ComposeConfig, client: docker.DockerClient):
        self.name = name
        self.config = config
        self.client = client
    
    def up(self, services: Optional[List[str]] = None):
        """Start services."""
        for svc in (services or list(self.config.services.keys())):
            self._start_service(svc)
    
    def down(self, remove_images=None, remove_volumes: bool = False, remove_orphans: bool = False):
        """Stop and remove containers."""
        for c in self.containers(stopped=True):
            try:
                c.stop()
                c.remove(force=True, v=remove_volumes)
            except (docker.errors.NotFound, docker.errors.APIError):
                pass
    
    def remove_stopped(self):
        """Remove stopped containers."""
        for c in self.containers(stopped=True):
            if not c.is_running:
                c.remove(force=True)
    
    def containers(self, service_names: Optional[List[str]] = None, stopped: bool = False) -> List[ComposeContainer]:
        """Get project containers."""
        filters = {'label': f'{LABEL_PROJECT}={self.name}'}
        if not stopped:
            filters['status'] = STATUS_RUNNING
        
        result = [ComposeContainer(c) for c in self.client.containers.list(all=stopped, filters=filters)]
        
        if service_names:
            result = [c for c in result if c.container.labels.get(LABEL_SERVICE) in service_names]
        return result
    
    def get_service(self, name: str) -> ComposeService:
        return ComposeService(name, self)
    
    def _start_service(self, service_name: str) -> ComposeContainer:
        """Start a single service."""
        container_name = f"{self.name}_{service_name}_1"
        
        # Check if exists
        try:
            existing = self.client.containers.get(container_name)
            if existing.status != STATUS_RUNNING:
                existing.start()
            return ComposeContainer(existing)
        except docker.errors.NotFound:
            pass
        
        # Create new
        svc_config = self.config.get_service(service_name)
        run_config = self._build_config(svc_config)
        
        container = self.client.containers.run(
            name=container_name,
            detach=True,
            labels={LABEL_PROJECT: self.name, LABEL_SERVICE: service_name},
            **run_config
        )
        return ComposeContainer(container)
    
    def _build_config(self, svc: Dict) -> Dict:
        """Convert compose service config to Docker SDK format."""
        cfg = {}
        
        if 'image' in svc:
            cfg['image'] = svc['image']
        
        if 'command' in svc:
            cfg['command'] = svc['command']
        
        if 'environment' in svc:
            env = svc['environment']
            if isinstance(env, list):
                env_dict: Dict[str, str] = {}
                for item in env:
                    if not isinstance(item, str):
                        continue
                    if '=' in item:
                        key, value = item.split('=', 1)
                    else:
                        key = item
                        value = os.environ.get(key, "")
                    env_dict[key] = value
                cfg['environment'] = env_dict
            elif isinstance(env, dict):
                resolved_env: Dict[str, Any] = {}
                for key, value in env.items():
                    if value is None:
                        resolved_env[key] = os.environ.get(key, "")
                    else:
                        resolved_env[key] = value
                cfg['environment'] = resolved_env
            else:
                cfg['environment'] = env
        
        if 'ports' in svc:
            ports: Dict[str, Any] = {}
            for port_spec in svc['ports']:
                port_str = str(port_spec)
                parts = port_str.split(':')
                if len(parts) == 1:
                    # Just container port (e.g., "80" or "80/tcp")
                    ports[parts[0]] = None
                elif len(parts) == 2:
                    # HOST:CONTAINER (e.g., "8080:80")
                    host_port, container_port = parts
                    ports[container_port] = int(host_port) if host_port.isdigit() else host_port
                elif len(parts) == 3:
                    # IP:HOST:CONTAINER (e.g., "127.0.0.1:8080:80")
                    ip, host_port, container_port = parts
                    ports[container_port] = (ip, int(host_port) if host_port else None)
            cfg['ports'] = ports
        
        if 'volumes' in svc:
            cfg['volumes'] = {}
            for v in svc['volumes']:
                if ':' in v:
                    parts = v.split(':')
                    host = parts[0]
                    if host.startswith('./'):
                        host = os.path.join(self.config.working_dir, host[2:])
                    cfg['volumes'][host] = {'bind': parts[1], 'mode': parts[2] if len(parts) > 2 else 'rw'}
        
        for key in ['network_mode', 'working_dir', 'hostname', 'entrypoint']:
            if key in svc:
                cfg[key] = svc[key]
        
        return cfg
