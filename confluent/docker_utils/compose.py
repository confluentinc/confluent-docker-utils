"""Docker Compose replacement using official Docker SDK."""

import os
import re
from typing import Any, Dict, List, Optional

import docker
import docker.errors
import yaml

__all__ = [
    'ComposeConfig',
    'ComposeContainer',
    'ComposeProject',
    'ComposeService',
    'create_docker_client',
    'LABEL_PROJECT',
    'LABEL_SERVICE',
    'STATUS_RUNNING',
    'STATUS_EXITED',
    'STATE_KEY',
    'EXIT_CODE_KEY',
    'VOLUME_MODE_RW',
]

# Docker Compose labels
LABEL_PROJECT = "com.docker.compose.project"
LABEL_SERVICE = "com.docker.compose.service"

# Container states
STATUS_RUNNING = "running"
STATUS_EXITED = "exited"

# Container attribute keys
STATE_KEY = "State"
EXIT_CODE_KEY = "ExitCode"

# Network driver
NETWORK_DRIVER_BRIDGE = "bridge"

# Volume mode
VOLUME_MODE_RW = "rw"

# Environment variable patterns
ENV_VAR_BRACED_PATTERN = re.compile(r'\$\{([^}]+)\}')
ENV_VAR_SIMPLE_PATTERN = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)')


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand environment variables in config values.
    
    Supports: ${VAR}, ${VAR:-default}, ${VAR-default}, $VAR
    """
    if isinstance(value, str):
        def _replace_braced(match: re.Match) -> str:
            expr = match.group(1)
            if ':-' in expr:
                name, default = expr.split(':-', 1)
                return os.environ.get(name, default)
            if '-' in expr and not expr.startswith('-'):
                name, default = expr.split('-', 1)
                env_val = os.environ.get(name)
                return env_val if env_val is not None else default
            return os.environ.get(expr, '')
        
        result = ENV_VAR_BRACED_PATTERN.sub(_replace_braced, value)
        result = ENV_VAR_SIMPLE_PATTERN.sub(lambda m: os.environ.get(m.group(1), ''), result)
        return result
    
    if isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    
    if isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    
    return value


def create_docker_client() -> docker.DockerClient:
    """Create Docker client from environment."""
    return docker.from_env()


class ComposeConfig:
    """Parses docker-compose.yml configuration."""
    
    def __init__(self, working_dir: str, config_file: str):
        self.working_dir = working_dir
        self.config_file_path = os.path.join(working_dir, config_file)
        self._config = self._load()
    
    def _load(self) -> Dict[str, Any]:
        with open(self.config_file_path, encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        
        if not raw_config or 'services' not in raw_config:
            raise ValueError(f"Invalid compose file: missing 'services' in {self.config_file_path}")
        
        return _expand_env_vars(raw_config)
    
    @property
    def services(self) -> Dict[str, Dict[str, Any]]:
        return self._config.get('services', {})
    
    def get_service(self, name: str) -> Dict[str, Any]:
        if name not in self.services:
            raise ValueError(f"Service '{name}' not found in compose file")
        return self.services[name]


class ComposeContainer:
    """Wrapper around Docker SDK container."""
    
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
        service_label = self.container.labels.get(LABEL_SERVICE)
        if service_label:
            return service_label
        # Container name format: {project}_{service}_{instance}
        # Extract service name (middle part)
        parts = self.name.split('_')
        if len(parts) >= 3:
            return '_'.join(parts[1:-1])
        if len(parts) == 2:
            return parts[1]
        return self.name
    
    @property
    def is_running(self) -> bool:
        self.container.reload()
        return self.container.status == STATUS_RUNNING
    
    @property
    def exit_code(self) -> Optional[int]:
        self.container.reload()
        if self.container.status == STATUS_EXITED:
            return self.container.attrs[STATE_KEY][EXIT_CODE_KEY]
        return None
    
    @property
    def client(self):
        """Low-level API client for backward compatibility."""
        return self.container.client.api
    
    @property
    def inspect_container(self) -> Dict[str, Any]:
        """Container attributes for backward compatibility."""
        self.container.reload()
        return self.container.attrs
    
    def start(self) -> None:
        self.container.start()
    
    def stop(self, timeout: int = 10) -> None:
        try:
            self.container.stop(timeout=timeout)
        except docker.errors.APIError:
            pass
    
    def remove(self, force: bool = False, v: bool = False) -> None:
        try:
            self.container.remove(force=force, v=v)
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
    
    def wait(self, timeout: Optional[int] = None) -> Dict[str, Any]:
        return self.container.wait(timeout=timeout)
    
    def logs(self) -> bytes:
        return self.container.logs()
    
    def create_exec(self, command: str) -> str:
        """Create exec instance for backward compatibility."""
        return self.container.client.api.exec_create(self.container.id, command)['Id']
    
    def start_exec(self, exec_id: str) -> bytes:
        """Start exec instance for backward compatibility."""
        return self.container.client.api.exec_start(exec_id)
    
    def exec_run(self, command: str) -> bytes:
        return self.container.exec_run(command).output


class ComposeService:
    """Represents a service in the compose project."""
    
    def __init__(self, name: str, project: 'ComposeProject'):
        self.name = name
        self.project = project
    
    def get_container(self) -> ComposeContainer:
        containers = self.project.containers(service_names=[self.name])
        if not containers:
            raise RuntimeError(f"No running container for service '{self.name}'")
        return containers[0]


class ComposeProject:
    """Manages multi-container compose project."""
    
    _PASSTHROUGH_KEYS = ('network_mode', 'working_dir', 'hostname', 'entrypoint', 'user', 'tty', 'stdin_open')
    
    def __init__(self, name: str, config: ComposeConfig, client: docker.DockerClient):
        self.name = name
        self.config = config
        self.client = client
        self._network = None
    
    @property
    def network_name(self) -> str:
        return f"{self.name}_default"
    
    def _get_or_create_network(self) -> docker.models.networks.Network:
        if self._network:
            return self._network
        
        try:
            self._network = self.client.networks.get(self.network_name)
        except docker.errors.NotFound:
            self._network = self.client.networks.create(
                self.network_name,
                driver=NETWORK_DRIVER_BRIDGE,
                labels={LABEL_PROJECT: self.name}
            )
        return self._network
    
    def up(self, services: Optional[List[str]] = None) -> None:
        self._get_or_create_network()
        service_list = services or list(self.config.services.keys())
        for service_name in service_list:
            self._start_service(service_name)
    
    def down(self, remove_images: Optional[str] = None, remove_volumes: bool = False,
             remove_orphans: bool = False) -> None:
        for container in self.containers(stopped=True):
            try:
                container.stop()
                container.remove(force=True, v=remove_volumes)
            except (docker.errors.NotFound, docker.errors.APIError):
                pass
        
        self._remove_network()
    
    def _remove_network(self) -> None:
        try:
            network = self.client.networks.get(self.network_name)
            network.remove()
        except (docker.errors.NotFound, docker.errors.APIError):
            pass
        self._network = None
    
    def remove_stopped(self) -> None:
        for container in self.containers(stopped=True):
            if not container.is_running:
                container.remove(force=True)
    
    def containers(self, service_names: Optional[List[str]] = None,
                   stopped: bool = False) -> List[ComposeContainer]:
        filters = {'label': f'{LABEL_PROJECT}={self.name}'}
        if not stopped:
            filters['status'] = STATUS_RUNNING
        
        all_containers = self.client.containers.list(all=stopped, filters=filters)
        result = [ComposeContainer(c) for c in all_containers]
        
        if service_names:
            result = [c for c in result if c.container.labels.get(LABEL_SERVICE) in service_names]
        
        return result
    
    def get_service(self, name: str) -> ComposeService:
        return ComposeService(name, self)
    
    def _start_service(self, service_name: str) -> ComposeContainer:
        container_name = f"{self.name}_{service_name}_1"
        
        existing = self._get_existing_container(container_name)
        if existing:
            return existing
        
        service_config = self.config.get_service(service_name)
        run_kwargs = self._build_run_kwargs(service_name, service_config)
        
        try:
            container = self.client.containers.run(**run_kwargs)
        except docker.errors.APIError as err:
            raise RuntimeError(f"Failed to start service '{service_name}': {err}") from err
        
        self._verify_container_running(container, service_name)
        return ComposeContainer(container)
    
    def _get_existing_container(self, container_name: str) -> Optional[ComposeContainer]:
        try:
            existing = self.client.containers.get(container_name)
            if existing.status != STATUS_RUNNING:
                existing.start()
            return ComposeContainer(existing)
        except docker.errors.NotFound:
            return None
    
    def _build_run_kwargs(self, service_name: str, service_config: Dict[str, Any]) -> Dict[str, Any]:
        container_config = self._parse_service_config(service_config)
        
        if 'image' not in container_config or not container_config['image']:
            raise ValueError(f"Service '{service_name}' has no valid image")
        
        kwargs = {
            'name': f"{self.name}_{service_name}_1",
            'detach': True,
            'labels': {LABEL_PROJECT: self.name, LABEL_SERVICE: service_name},
            **container_config
        }
        
        if 'network_mode' not in container_config:
            network = self._get_or_create_network()
            kwargs['network'] = network.name
            if 'hostname' not in container_config:
                kwargs['hostname'] = service_name
        
        return kwargs
    
    def _parse_service_config(self, service_config: Dict[str, Any]) -> Dict[str, Any]:
        config = {}
        
        if 'image' in service_config:
            config['image'] = service_config['image']
        
        if 'command' in service_config:
            config['command'] = service_config['command']
        
        if 'environment' in service_config:
            config['environment'] = self._parse_environment(service_config['environment'])
        
        if 'ports' in service_config:
            config['ports'] = self._parse_ports(service_config['ports'])
        
        if 'volumes' in service_config:
            config['volumes'] = self._parse_volumes(service_config['volumes'])
        
        for key in self._PASSTHROUGH_KEYS:
            if key in service_config:
                config[key] = service_config[key]
        
        return config
    
    def _parse_environment(self, env: Any) -> Dict[str, str]:
        if isinstance(env, list):
            result = {}
            for item in env:
                if not isinstance(item, str):
                    continue
                if '=' in item:
                    key, value = item.split('=', 1)
                else:
                    key, value = item, os.environ.get(item, '')
                result[key] = value
            return result
        
        if isinstance(env, dict):
            return {
                key: os.environ.get(key, '') if value is None else str(value)
                for key, value in env.items()
            }
        
        return env
    
    def _parse_ports(self, ports: List[Any]) -> Dict[str, Any]:
        result = {}
        for port_spec in ports:
            port_str = str(port_spec)
            parts = port_str.split(':')
            
            if len(parts) == 1:
                result[parts[0]] = None
            elif len(parts) == 2:
                host_port, container_port = parts
                result[container_port] = int(host_port) if host_port.isdigit() else host_port
            elif len(parts) == 3:
                ip_addr, host_port, container_port = parts
                host_binding = int(host_port) if host_port else None
                result[container_port] = (ip_addr, host_binding)
        
        return result
    
    def _parse_volumes(self, volumes: List[str]) -> Dict[str, Dict[str, str]]:
        result = {}
        for volume_spec in volumes:
            if ':' not in volume_spec:
                continue
            
            parts = volume_spec.split(':')
            host_path = parts[0]
            container_path = parts[1]
            mode = parts[2] if len(parts) > 2 else VOLUME_MODE_RW
            
            if host_path.startswith('./'):
                host_path = os.path.join(self.config.working_dir, host_path[2:])
            
            result[host_path] = {'bind': container_path, 'mode': mode}
        
        return result
    
    def _verify_container_running(self, container: docker.models.containers.Container,
                                   service_name: str) -> None:
        container.reload()
        if container.status != STATUS_RUNNING:
            logs = container.logs().decode('utf-8', errors='ignore')[-500:]
            raise RuntimeError(
                f"Service '{service_name}' exited immediately.\nLogs:\n{logs}"
            )
