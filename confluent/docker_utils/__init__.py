import base64
import os
import subprocess

import boto3
import docker
from .compose_replacement import (
    ComposeConfig, ComposeProject, ComposeContainer, 
    create_docker_client
)


def api_client():
    """Get Docker client compatible with both legacy and new usage."""
    return docker.from_env()


def ecr_login():
    # see docker/docker-py#1677
    ecr = boto3.client('ecr')
    login = ecr.get_authorization_token()
    b64token = login['authorizationData'][0]['authorizationToken'].encode('utf-8')
    username, password = base64.b64decode(b64token).decode('utf-8').split(':')
    registry = login['authorizationData'][0]['proxyEndpoint']
    client = docker.from_env()
    client.login(username, password, registry=registry)


def build_image(image_name, dockerfile_dir):
    print("Building image %s from %s" % (image_name, dockerfile_dir))
    client = api_client()
    image, build_logs = client.images.build(path=dockerfile_dir, rm=True, tag=image_name)
    response = "".join(["     %s" % (line.get('stream', '')) for line in build_logs if 'stream' in line])
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
    pull_image(kwargs["image"])
    client = api_client()
    kwargs["labels"] = {"io.confluent.docker.testing": "true"}
    container = TestContainer.create(client, **kwargs)
    container.start()
    container.wait(timeout)
    logs = container.logs()
    print("Running command %s: %s" % (kwargs["command"], logs))
    container.shutdown()
    return logs


def path_exists_in_image(image, path):
    print("Checking for %s in %s" % (path, image))
    cmd = "bash -c '[ ! -e %s ] || echo success' " % (path,)
    output = run_docker_command(image=image, command=cmd)
    return b"success" in output


def executable_exists_in_image(image, path):
    print("Checking for %s in %s" % (path, image))
    cmd = "bash -c '[ ! -x %s ] || echo success' " % (path,)
    output = run_docker_command(image=image, command=cmd)
    return b"success" in output


def run_command_on_host(command):
    logs = run_docker_command(
        image="busybox",
        command=command,
        host_config={'NetworkMode': 'host', 'Binds': ['/tmp:/tmp']})
    print("Running command %s: %s" % (command, logs))
    return logs


def run_cmd(command):
    if command.startswith('"'):
        cmd = "bash -c %s" % command
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
        scope += "_"

    return "{0}{1}:{2}".format(os.environ.get("DOCKER_{0}REGISTRY".format(scope), ""),
                               image,
                               os.environ.get("DOCKER_{0}TAG".format(scope), "latest")
                               )


class TestContainer(ComposeContainer):
    """Extended container class for testing purposes."""
    
    def __init__(self, container):
        super().__init__(container)
    
    @classmethod
    def create(cls, client, **kwargs):
        """Create a new container using Docker SDK."""
        # Extract Docker SDK compatible parameters
        image = kwargs.get('image')
        command = kwargs.get('command')
        labels = kwargs.get('labels', {})
        host_config = kwargs.get('host_config', {})
        
        # Create container configuration
        container_config = {
            'image': image,
            'command': command,
            'labels': labels,
            'detach': True,
        }
        
        # Add host configuration if provided
        if host_config:
            if 'NetworkMode' in host_config:
                container_config['network_mode'] = host_config['NetworkMode']
            if 'Binds' in host_config:
                volumes = {}
                for bind in host_config['Binds']:
                    host_path, container_path = bind.split(':')
                    volumes[host_path] = {'bind': container_path, 'mode': 'rw'}
                container_config['volumes'] = volumes
        
        # Create the container
        docker_container = client.containers.create(**container_config)
        
        # Return wrapped container
        return cls(docker_container)
    
    def start(self):
        """Start the container."""
        self.container.start()
    
    def state(self):
        """Get container state information."""
        self.container.reload()
        return self.container.attrs["State"]

    def status(self):
        """Get container status."""
        return self.state()["Status"]

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
        print("Running %s on %s :" % (command, container.name))
        result = container.container.exec_run(command)
        output = result.output
        if isinstance(output, bytes):
            print("\n%s " % output.decode('utf-8', errors='ignore'))
        else:
            print("\n%s " % output)
        return output

    def run_command_on_all(self, command):
        """Run a command on all containers in the cluster."""
        results = {}
        for container in self.get_project().containers():
            results[container.name_without_project] = self.run_command(command, container)
        return results
