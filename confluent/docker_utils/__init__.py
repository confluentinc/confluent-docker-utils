"""Confluent Docker Utilities."""

import base64
import os
import subprocess
from typing import Dict, Optional

import docker

from .compose import (
    ComposeConfig, ComposeContainer, ComposeProject, ComposeService, create_docker_client,
    STATE_KEY, EXIT_CODE_KEY, STATUS_RUNNING, STATUS_EXITED
)

# Host config keys (for backward compatibility)
HOST_CONFIG_NETWORK_MODE = "NetworkMode"
HOST_CONFIG_BINDS = "Binds"

# Testing label
TESTING_LABEL = "io.confluent.docker.testing"

try:
    import boto3
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


def api_client() -> docker.DockerClient:
    """Get Docker client."""
    return docker.from_env()


def ecr_login():
    """Login to AWS ECR."""
    if not HAS_BOTO3:
        raise ImportError("boto3 required for ECR login")
    
    ecr = boto3.client('ecr')
    auth = ecr.get_authorization_token()['authorizationData'][0]
    token = base64.b64decode(auth['authorizationToken'].encode()).decode()
    user, pwd = token.split(':')
    docker.from_env().login(user, pwd, registry=auth['proxyEndpoint'])


def build_image(image_name: str, dockerfile_dir: str):
    """Build Docker image."""
    print(f"Building image {image_name} from {dockerfile_dir}")
    _, logs = api_client().images.build(path=dockerfile_dir, rm=True, tag=image_name, decode=True)
    for line in logs:
        if isinstance(line, dict) and 'stream' in line:
            print(f"     {line['stream']}", end='')
        elif isinstance(line, (bytes, str)):
            text = line.decode(errors="ignore") if isinstance(line, bytes) else line
            print(f"     {text}", end='')


def image_exists(image_name: str) -> bool:
    """Check if image exists locally."""
    try:
        api_client().images.get(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False


def pull_image(image_name: str):
    """Pull image if not exists."""
    if not image_exists(image_name):
        api_client().images.pull(image_name)


def run_docker_command(timeout=None, **kwargs) -> bytes:
    """Run command in temporary container."""
    pull_image(kwargs["image"])
    
    cfg = {
        'image': kwargs['image'],
        'command': kwargs.get('command'),
        'labels': {TESTING_LABEL: "true"},
        'detach': True,
    }
    
    host_cfg = kwargs.get('host_config', {})
    if HOST_CONFIG_NETWORK_MODE in host_cfg:
        cfg['network_mode'] = host_cfg[HOST_CONFIG_NETWORK_MODE]
    if HOST_CONFIG_BINDS in host_cfg:
        cfg['volumes'] = {b.split(':')[0]: {'bind': b.split(':')[1], 'mode': 'rw'} 
                         for b in host_cfg[HOST_CONFIG_BINDS]}
    
    container = api_client().containers.create(**cfg)
    try:
        container.start()
        container.wait(timeout=timeout)
        logs = container.logs()
        print(f"Running command {kwargs.get('command')}: {logs}")
        return logs
    finally:
        try:
            container.stop()
            container.remove()
        except Exception:
            pass


def path_exists_in_image(image: str, path: str) -> bool:
    """Check if path exists in image."""
    print(f"Checking for {path} in {image}")
    output = run_docker_command(image=image, command=f"bash -c '[ ! -e {path} ] || echo success'")
    return b"success" in output


def executable_exists_in_image(image: str, path: str) -> bool:
    """Check if executable exists in image."""
    print(f"Checking for {path} in {image}")
    output = run_docker_command(image=image, command=f"bash -c '[ ! -x {path} ] || echo success'")
    return b"success" in output


def run_command_on_host(command: str) -> bytes:
    """Run command on host via busybox."""
    return run_docker_command(
        image="busybox", command=command,
        host_config={HOST_CONFIG_NETWORK_MODE: 'host', HOST_CONFIG_BINDS: ['/tmp:/tmp']}
    )


def run_cmd(command: str) -> bytes:
    """Run shell command locally."""
    cmd = f"bash -c {command}" if command.startswith('"') else command
    return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)


def add_registry_and_tag(image: str, scope: str = "") -> str:
    """Qualify image name with registry and tag from env vars."""
    prefix = f"{scope}_" if scope else ""
    registry = os.environ.get(f"DOCKER_{prefix}REGISTRY", "")
    tag = os.environ.get(f"DOCKER_{prefix}TAG", "latest")
    return f"{registry}{image}:{tag}"


class TestContainer(ComposeContainer):
    """Container for testing with lifecycle methods."""
    
    @classmethod
    def create(cls, client, **kwargs) -> 'TestContainer':
        cfg = {
            'image': kwargs.get('image'),
            'command': kwargs.get('command'),
            'labels': kwargs.get('labels', {}),
            'detach': True,
        }
        host_cfg = kwargs.get('host_config', {})
        if HOST_CONFIG_NETWORK_MODE in host_cfg:
            cfg['network_mode'] = host_cfg[HOST_CONFIG_NETWORK_MODE]
        if HOST_CONFIG_BINDS in host_cfg:
            cfg['volumes'] = {b.split(':')[0]: {'bind': b.split(':')[1], 'mode': 'rw'} 
                             for b in host_cfg[HOST_CONFIG_BINDS]}
        return cls(client.containers.create(**cfg))
    
    def state(self) -> Dict:
        self.container.reload()
        return self.container.attrs[STATE_KEY]
    
    def status(self) -> str:
        return self.state()['Status']
    
    def shutdown(self):
        self.stop()
        self.remove()
    
    def execute(self, command: str) -> bytes:
        return self.exec_run(command)


class TestCluster:
    """Multi-container test cluster."""
    
    def __init__(self, name: str, working_dir: str, config_file: str):
        self.name = name
        self.config = ComposeConfig(working_dir, config_file)
    
    def get_project(self) -> ComposeProject:
        return ComposeProject(self.name, self.config, create_docker_client())
    
    def start(self):
        self.shutdown()
        self.get_project().up()
    
    def shutdown(self):
        p = self.get_project()
        p.down(remove_volumes=True)
        p.remove_stopped()
    
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
            containers = self.get_project().containers([service_name], stopped=True)
            if containers:
                return containers[0]
            raise RuntimeError(f"No container for '{service_name}'")
        return self.get_project().get_service(service_name).get_container()
    
    def exit_code(self, service_name: str) -> Optional[int]:
        containers = self.get_project().containers([service_name], stopped=True)
        return containers[0].exit_code if containers else None
    
    def wait(self, service_name: str, timeout=None):
        containers = self.get_project().containers([service_name], stopped=True)
        if containers and containers[0].is_running:
            return containers[0].wait(timeout)
    
    def service_logs(self, service_name: str, stopped: bool = False) -> bytes:
        if stopped:
            containers = self.get_project().containers([service_name], stopped=True)
            return containers[0].logs() if containers else b''
        return self.get_container(service_name).logs()
    
    def run_command_on_service(self, service_name: str, command: str) -> bytes:
        return self.run_command(command, self.get_container(service_name))
    
    def run_command(self, command: str, container: ComposeContainer) -> bytes:
        print(f"Running {command} on {container.name}:")
        output = container.exec_run(command)
        print(f"\n{output.decode('utf-8', errors='ignore') if isinstance(output, bytes) else output}")
        return output
    
    def run_command_on_all(self, command: str) -> Dict[str, bytes]:
        return {c.name_without_project: self.run_command(command, c) 
                for c in self.get_project().containers()}
