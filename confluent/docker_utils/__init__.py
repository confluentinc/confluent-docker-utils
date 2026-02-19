import base64
import os
import subprocess
from typing import Any, Dict, Optional, Tuple

import boto3
import docker

from .compose import (
    ComposeConfig,
    ComposeContainer,
    ComposeProject,
    ComposeService,
    create_docker_client,
    STATE_KEY,
    STATUS_RUNNING,
    VOLUME_MODE_RW,
)

HOST_CONFIG_NETWORK_MODE = "NetworkMode"
HOST_CONFIG_BINDS = "Binds"
TESTING_LABEL = "io.confluent.docker.testing"


def docker_client() -> docker.DockerClient:
    return docker.from_env()


def ecr_login() -> None:
    ecr = boto3.client('ecr')
    auth_data = ecr.get_authorization_token()['authorizationData'][0]
    token = base64.b64decode(auth_data['authorizationToken'].encode()).decode()
    username, password = token.split(':')
    docker.from_env().login(username, password, registry=auth_data['proxyEndpoint'])


def build_image(image_name: str, dockerfile_dir: str) -> None:
    print(f"Building image {image_name} from {dockerfile_dir}")
    _, build_logs = docker_client().images.build(
        path=dockerfile_dir, rm=True, tag=image_name, decode=True
    )
    for log_line in build_logs:
        if isinstance(log_line, dict) and 'stream' in log_line:
            print(f"     {log_line['stream']}", end='')
        elif isinstance(log_line, (bytes, str)):
            text = log_line.decode(errors='ignore') if isinstance(log_line, bytes) else log_line
            print(f"     {text}", end='')


def image_exists(image_name: str) -> bool:
    try:
        docker_client().images.get(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False


def pull_image(image_name: str) -> None:
    if image_exists(image_name):
        return
    try:
        docker_client().images.pull(image_name)
    except docker.errors.APIError as err:
        raise RuntimeError(f"Failed to pull image '{image_name}': {err}") from err


def parse_bind_mount(bind_spec: str) -> Tuple[str, Dict[str, str]]:
    parts = bind_spec.split(':')
    if len(parts) < 2:
        raise ValueError(f"Invalid bind mount format: {bind_spec}")
    host_path = parts[0]
    container_path = parts[1]
    mode = parts[2] if len(parts) > 2 else VOLUME_MODE_RW
    return host_path, {'bind': container_path, 'mode': mode}


def _parse_binds(binds: list) -> Dict[str, Dict[str, str]]:
    result = {}
    for bind_spec in binds:
        host_path, mount_config = parse_bind_mount(bind_spec)
        result[host_path] = mount_config
    return result


def _build_container_config(image: str, command: Optional[str], labels: Dict[str, str],
                            host_config: Dict[str, Any]) -> Dict[str, Any]:
    config = {
        'image': image,
        'command': command,
        'labels': labels,
        'detach': True,
    }
    
    if HOST_CONFIG_NETWORK_MODE in host_config:
        config['network_mode'] = host_config[HOST_CONFIG_NETWORK_MODE]
    if HOST_CONFIG_BINDS in host_config:
        config['volumes'] = _parse_binds(host_config[HOST_CONFIG_BINDS])
    
    return config


def run_docker_command(timeout: Optional[int] = None, **kwargs) -> bytes:
    pull_image(kwargs['image'])
    
    container_config = _build_container_config(
        image=kwargs['image'],
        command=kwargs.get('command'),
        labels={TESTING_LABEL: 'true'},
        host_config=kwargs.get('host_config', {})
    )
    
    container = docker_client().containers.create(**container_config)
    try:
        container.start()
        container.wait(timeout=timeout)
        output = container.logs()
        print(f"Running command {kwargs.get('command')}: {output}")
        return output
    finally:
        _cleanup_container(container)


def _cleanup_container(container) -> None:
    try:
        container.stop()
        container.remove()
    except docker.errors.NotFound:
        print(f"Container {container.id} already removed")


def path_exists_in_image(image: str, path: str) -> bool:
    print(f"Checking for {path} in {image}")
    output = run_docker_command(
        image=image,
        command=f"bash -c '[ ! -e {path} ] || echo success'"
    )
    return b'success' in output


def executable_exists_in_image(image: str, path: str) -> bool:
    print(f"Checking for {path} in {image}")
    output = run_docker_command(
        image=image,
        command=f"bash -c '[ ! -x {path} ] || echo success'"
    )
    return b'success' in output


def run_command_on_host(command: str) -> bytes:
    return run_docker_command(
        image='busybox',
        command=command,
        host_config={
            HOST_CONFIG_NETWORK_MODE: 'host',
            HOST_CONFIG_BINDS: ['/tmp:/tmp']
        }
    )


def run_cmd(command: str) -> bytes:
    shell_command = f'bash -c {command}' if command.startswith('"') else command
    return subprocess.check_output(shell_command, shell=True, stderr=subprocess.STDOUT)


def add_registry_and_tag(image: str, scope: str = '') -> str:
    prefix = f'{scope}_' if scope else ''
    registry = os.environ.get(f'DOCKER_{prefix}REGISTRY', '')
    tag = os.environ.get(f'DOCKER_{prefix}TAG', 'latest')
    return f'{registry}{image}:{tag}'


class TestContainer(ComposeContainer):
    @classmethod
    def create(cls, client: docker.DockerClient, **kwargs) -> 'TestContainer':
        container_config = _build_container_config(
            image=kwargs.get('image'),
            command=kwargs.get('command'),
            labels=kwargs.get('labels', {}),
            host_config=kwargs.get('host_config', {})
        )
        return cls(client.containers.create(**container_config))
    
    def state(self) -> Dict:
        self.container.reload()
        return self.container.attrs[STATE_KEY]
    
    def status(self) -> str:
        return self.state()['Status']
    
    def shutdown(self) -> None:
        self.stop()
        self.remove()
    
    def execute(self, command: str) -> bytes:
        return self.exec_run(command)


class TestCluster:
    def __init__(self, name: str, working_dir: str, config_file: str):
        self.name = name
        self._config = ComposeConfig(working_dir, config_file)
    
    def get_project(self) -> ComposeProject:
        return ComposeProject(self.name, self._config, create_docker_client())
    
    def start(self) -> None:
        self.shutdown()
        self.get_project().up()
    
    def shutdown(self) -> None:
        self.get_project().down(remove_volumes=True)
    
    def is_running(self) -> bool:
        containers = self.get_project().containers()
        return bool(containers) and all(c.is_running for c in containers)
    
    def is_service_running(self, service_name: str) -> bool:
        try:
            return self.get_container(service_name).is_running
        except RuntimeError:
            return False
    
    def get_container(self, service_name: str, stopped: bool = False) -> ComposeContainer:
        if stopped:
            containers = self.get_project().containers(
                service_names=[service_name], stopped=True
            )
            if containers:
                return containers[0]
            raise RuntimeError(f"No container for '{service_name}'")
        return self.get_project().get_service(service_name).get_container()
    
    def exit_code(self, service_name: str) -> Optional[int]:
        containers = self.get_project().containers(
            service_names=[service_name], stopped=True
        )
        return containers[0].exit_code if containers else None
    
    def wait(self, service_name: str, timeout: Optional[int] = None) -> Optional[Dict]:
        containers = self.get_project().containers(
            service_names=[service_name], stopped=True
        )
        if containers and containers[0].is_running:
            return containers[0].wait(timeout)
        return None
    
    def service_logs(self, service_name: str, stopped: bool = False) -> bytes:
        if stopped:
            containers = self.get_project().containers(
                service_names=[service_name], stopped=True
            )
            return containers[0].logs() if containers else b''
        return self.get_container(service_name).logs()
    
    def run_command_on_service(self, service_name: str, command: str) -> bytes:
        return self.run_command(command, self.get_container(service_name))
    
    def run_command(self, command: str, container: ComposeContainer) -> bytes:
        print(f"Running {command} on {container.name}:")
        output = container.exec_run(command)
        decoded = output.decode('utf-8', errors='ignore') if isinstance(output, bytes) else output
        print(f"\n{decoded}")
        return output
    
    def run_command_on_all(self, command: str) -> Dict[str, bytes]:
        return {
            container.name_without_project: self.run_command(command, container)
            for container in self.get_project().containers()
        }
