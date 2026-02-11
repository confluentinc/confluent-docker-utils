"""
Docker Compose replacement using official Docker SDK.

Drop-in replacement for the deprecated docker-compose Python library.
"""

import os
import re
from typing import Dict, List, Optional, Any, Union

import yaml
import docker
import docker.errors


def expand_env_vars(value: Any) -> Any:
    """Expand environment variables in compose config values.
    
    Supports ${VAR}, ${VAR:-default}, ${VAR-default}, $VAR formats.
    """
    if isinstance(value, str):
        # Pattern for ${VAR}, ${VAR:-default}, ${VAR-default}
        def replace_var(match):
            var_expr = match.group(1)
            # Handle ${VAR:-default} or ${VAR-default}
            if ':-' in var_expr:
                var_name, default = var_expr.split(':-', 1)
                return os.environ.get(var_name, default)
            elif '-' in var_expr and not var_expr.startswith('-'):
                var_name, default = var_expr.split('-', 1)
                return os.environ.get(var_name) if os.environ.get(var_name) is not None else default
            else:
                return os.environ.get(var_expr, '')
        
        # Replace ${VAR} patterns
        result = re.sub(r'\$\{([^}]+)\}', replace_var, value)
        # Replace $VAR patterns (word boundary)
        result = re.sub(r'\$([A-Za-z_][A-Za-z0-9_]*)', lambda m: os.environ.get(m.group(1), ''), result)
        return result
    elif isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    return value

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
        # Expand environment variables in all config values
        return expand_env_vars(config)
    
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
        self._network = None
    
    @property
    def network_name(self) -> str:
        """Default network name for the project."""
        return f"{self.name}_default"
    
    def _ensure_network(self):
        """Create project network if it doesn't exist."""
        if self._network:
            return self._network
        
        try:
            self._network = self.client.networks.get(self.network_name)
        except docker.errors.NotFound:
            self._network = self.client.networks.create(
                self.network_name,
                driver="bridge",
                labels={LABEL_PROJECT: self.name}
            )
        return self._network
    
    def up(self, services: Optional[List[str]] = None):
        """Start services."""
        self._ensure_network()
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
        
        # Remove project network
        try:
            network = self.client.networks.get(self.network_name)
            network.remove()
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
        self._network = None
    
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
        
        # Validate image is set
        if 'image' not in run_config or not run_config['image']:
            raise ValueError(f"Service '{service_name}' has no valid image specified")
        
        # Use project network for inter-service communication
        network = self._ensure_network()
        
        container = self.client.containers.run(
            name=container_name,
            detach=True,
            network=network.name,
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
