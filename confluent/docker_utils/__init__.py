import base64
import os
import subprocess
from enum import StrEnum

import boto3
import docker
from .compose import (
    ComposeConfig, ComposeProject, ComposeContainer, 
    create_docker_client, ContainerStatus, STATE_KEY, STATUS_KEY,
    Separators, VOLUME_BIND_MODE, VOLUME_READ_WRITE_MODE
)


DOCKER_TESTING_LABEL = "io.confluent.docker.testing"
TRUE_VALUE = "true"


class ECRKeys(StrEnum):
    """AWS ECR service keys."""
    ECR_SERVICE = "ecr"
    AUTH_DATA = "authorizationData"
    AUTH_TOKEN = "authorizationToken"
    PROXY_ENDPOINT = "proxyEndpoint"


BASH_C = "bash -c"
SUCCESS_TEXT = "success"
SUCCESS_BYTES = b"success"

BUSYBOX_IMAGE = "busybox"
HOST_NETWORK = "host"
TMP_VOLUME = "/tmp:/tmp"


DOCKER_PREFIX = "DOCKER_"
REGISTRY_SUFFIX = "REGISTRY"
TAG_SUFFIX = "TAG"
DEFAULT_TAG = "latest"
UPSTREAM_SCOPE = "UPSTREAM"
TEST_SCOPE = "TEST"
SCOPE_SEPARATOR = "_"


class ContainerConfigKeys(StrEnum):
    """Container configuration keys."""
    IMAGE = "image"
    COMMAND = "command"
    LABELS = "labels"
    HOST_CONFIG = "host_config"
    NETWORK_MODE = "NetworkMode"
    BINDS = "Binds"
    DETACH = "detach"
    NETWORK_MODE_KEY = "network_mode"
    VOLUMES = "volumes"


UTF8_ENCODING = "utf-8"
IGNORE_DECODE_ERRORS = "ignore" 
DOCKER_STREAM_KEY = "stream"


def api_client():
    """Get Docker client compatible with both legacy and new usage."""
    return docker.from_env()


def ecr_login():
    # see docker/docker-py#1677
    ecr = boto3.client(ECRKeys.ECR_SERVICE)
    login = ecr.get_authorization_token()
    b64token = login[ECRKeys.AUTH_DATA][0][ECRKeys.AUTH_TOKEN].encode(UTF8_ENCODING)
    username, password = base64.b64decode(b64token).decode(UTF8_ENCODING).split(Separators.COLON)
    registry = login[ECRKeys.AUTH_DATA][0][ECRKeys.PROXY_ENDPOINT]
    client = docker.from_env()
    client.login(username, password, registry=registry)


def build_image(image_name, dockerfile_dir):
    print(f"Building image {image_name} from {dockerfile_dir}")
    client = api_client()
    image, build_logs = client.images.build(path=dockerfile_dir, rm=True, tag=image_name)
    response = "".join([f"     {line.get(DOCKER_STREAM_KEY, '')}" for line in build_logs if DOCKER_STREAM_KEY in line])
    print(response)


def image_exists(image_name):
    client = api_client()
    try:
        client.images.get(image_name)
        return True
    except docker.errors.ImageNotFound:
        return False


def pull_image(image_name):
    client = api_client()
    if not image_exists(image_name):
        client.images.pull(image_name)


def run_docker_command(timeout=None, **kwargs):
    pull_image(kwargs[ContainerConfigKeys.IMAGE])
    client = api_client()
    kwargs[ContainerConfigKeys.LABELS] = {DOCKER_TESTING_LABEL: TRUE_VALUE}
    container = TestContainer.create(client, **kwargs)
    container.start()
    container.wait(timeout)
    logs = container.logs()
    print(f"Running command {kwargs[ContainerConfigKeys.COMMAND]}: {logs}")
    container.shutdown()
    return logs


def path_exists_in_image(image, path):
    print(f"Checking for {path} in {image}")
    cmd = f"{BASH_C} '[ ! -e {path} ] || echo {SUCCESS_TEXT}' "
    output = run_docker_command(image=image, command=cmd)
    return SUCCESS_BYTES in output


def executable_exists_in_image(image, path):
    print(f"Checking for {path} in {image}")
    cmd = f"{BASH_C} '[ ! -x {path} ] || echo {SUCCESS_TEXT}' "
    output = run_docker_command(image=image, command=cmd)
    return SUCCESS_BYTES in output


def run_command_on_host(command):
    logs = run_docker_command(
        image=BUSYBOX_IMAGE,
        command=command,
        host_config={ContainerConfigKeys.NETWORK_MODE: HOST_NETWORK, ContainerConfigKeys.BINDS: [TMP_VOLUME]})
    print(f"Running command {command}: {logs}")
    return logs


def run_cmd(command):
    if command.startswith('"'):
        cmd = f"{BASH_C} {command}"
    else:
        cmd = command

    output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)

    return output


def add_registry_and_tag(image, scope=""):
    """
    Fully qualify an image name. `scope` may be an empty
    string, "UPSTREAM" for upstream dependencies, or "TEST"
    for test dependencies. The injected values correspond to
    DOCKER_(${scope}_)REGISTRY and DOCKER_(${scope}_)TAG environment
    variables, which are set up by the Maven build.

    :param str image: Image name, without registry prefix and tag postfix.
    :param str scope:
    """

    if scope:
        scope += SCOPE_SEPARATOR

    registry = os.environ.get(f"{DOCKER_PREFIX}{scope}{REGISTRY_SUFFIX}", "")
    tag = os.environ.get(f"{DOCKER_PREFIX}{scope}{TAG_SUFFIX}", DEFAULT_TAG)
    return f"{registry}{image}:{tag}"


class TestContainer(ComposeContainer):
    """Extended container class for testing purposes."""
    
    def __init__(self, container):
        super().__init__(container)
    
    @classmethod
    def create(cls, client, **kwargs):
        """Create a new container using Docker SDK."""
        # Extract Docker SDK compatible parameters
        image = kwargs.get(ContainerConfigKeys.IMAGE)
        command = kwargs.get(ContainerConfigKeys.COMMAND)
        labels = kwargs.get(ContainerConfigKeys.LABELS, {})
        host_config = kwargs.get(ContainerConfigKeys.HOST_CONFIG, {})
        
        container_config = {
            ContainerConfigKeys.IMAGE: image,
            ContainerConfigKeys.COMMAND: command,
            ContainerConfigKeys.LABELS: labels,
            ContainerConfigKeys.DETACH: True,
        }
        
        if host_config:
            if ContainerConfigKeys.NETWORK_MODE in host_config:
                container_config[ContainerConfigKeys.NETWORK_MODE_KEY] = host_config[ContainerConfigKeys.NETWORK_MODE]
            if ContainerConfigKeys.BINDS in host_config:
                volumes = {}
                for bind in host_config[ContainerConfigKeys.BINDS]:
                    host_path, container_path = bind.split(Separators.COLON)
                    volumes[host_path] = {VOLUME_BIND_MODE: container_path, 'mode': VOLUME_READ_WRITE_MODE}
                container_config[ContainerConfigKeys.VOLUMES] = volumes
        
        docker_container = client.containers.create(**container_config)
        return cls(docker_container)
    
    def start(self):
        """Start the container."""
        self.container.start()
    
    def state(self):
        """Get container state information."""
        self.container.reload()
        return self.container.attrs[STATE_KEY]

    def status(self):
        """Get container status."""
        return self.state()[STATUS_KEY]

    def shutdown(self):
        """Stop and remove the container."""
        self.stop()
        self.remove()

    def execute(self, command):
        """Execute a command in the container."""
        result = self.container.exec_run(command)
        return result.output

    def wait(self, timeout):
        """Wait for the container to stop."""
        return self.container.wait(timeout=timeout)


class TestCluster():
    """Test cluster management using modern Docker SDK."""

    def __init__(self, name, working_dir, config_file):
        self.name = name
        self.config = ComposeConfig(working_dir, config_file)
        self._project = None

    def get_project(self):
        """Get the compose project, creating a new client each time to avoid issues."""
        # Create a new client each time to avoid reuse issues
        client = create_docker_client()
        self._project = ComposeProject(self.name, self.config, client)
        return self._project

    def start(self):
        """Start all services in the cluster."""
        self.shutdown()
        self.get_project().up()

    def is_running(self):
        """Check if all services in the cluster are running."""
        containers = self.get_project().containers()
        if not containers:
            return False
        return all(container.is_running for container in containers)

    def is_service_running(self, service_name):
        """Check if a specific service is running."""
        try:
            return self.get_container(service_name).is_running
        except RuntimeError:
            return False

    def shutdown(self):
        """Shutdown all services in the cluster."""
        project = self.get_project()
        project.down(remove_volumes=True, remove_orphans=True)
        project.remove_stopped()

    def get_container(self, service_name, stopped=False):
        """Get a container for a specific service."""
        if stopped:
            containers = self.get_project().containers([service_name], stopped=True)
            if containers:
                return containers[0]
            raise RuntimeError(f"No container found for service '{service_name}'")
        return self.get_project().get_service(service_name).get_container()

    def exit_code(self, service_name):
        """Get the exit code of a service container."""
        containers = self.get_project().containers([service_name], stopped=True)
        if containers:
            return containers[0].exit_code
        return None

    def wait(self, service_name, timeout):
        """Wait for a service container to stop."""
        containers = self.get_project().containers([service_name], stopped=True)
        if containers and containers[0].is_running:
            return containers[0].wait(timeout)

    def run_command_on_service(self, service_name, command):
        """Run a command on a specific service container."""
        return self.run_command(command, self.get_container(service_name))

    def service_logs(self, service_name, stopped=False):
        """Get logs from a service container."""
        if stopped:
            containers = self.get_project().containers([service_name], stopped=True)
            if containers:
                logs = containers[0].logs()
                print(logs)
                return logs
            return b''
        else:
            return self.get_container(service_name).logs()

    def run_command(self, command, container):
        """Run a command on a container."""
        print(f"Running {command} on {container.name} :")
        result = container.container.exec_run(command)
        output = result.output
        if isinstance(output, bytes):
            print(f"\n{output.decode(UTF8_ENCODING, errors=IGNORE_DECODE_ERRORS)} ")
        else:
            print(f"\n{output} ")
        return output

    def run_command_on_all(self, command):
        """Run a command on all containers in the cluster."""
        results = {}
        for container in self.get_project().containers():
            results[container.name_without_project] = self.run_command(command, container)
        return results
