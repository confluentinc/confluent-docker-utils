import docker
import os

from compose.config.config import ConfigDetails, ConfigFile, load
from compose.container import Container
from compose.project import Project
from compose.service import ImageType
from compose.cli.docker_client import docker_client
from compose.config.environment import Environment

import subprocess


DOCKER_HOST = os.environ.get("DOCKER_HOST", 'unix://var/run/docker.sock')


def build_image(image_name, dockerfile_dir):
    print("Building image %s from %s" % (image_name, dockerfile_dir))
    client = docker.APIClient(base_url=DOCKER_HOST)
    output = client.build(dockerfile_dir, rm=True, tag=image_name)
    response = "".join(["     %s" % (line,) for line in output])
    print(response)


def image_exists(image_name):
    client = docker.APIClient(base_url=DOCKER_HOST)
    tags = [t for image in client.images() for t in image['RepoTags'] or []]
    return image_name in tags


def pull_image(image_name):
    client = docker.APIClient(base_url=DOCKER_HOST)
    if not image_exists(image_name):
        client.pull(image_name)


def run_docker_command(timeout=None, **kwargs):
    pull_image(kwargs["image"])
    client = docker.APIClient(base_url=DOCKER_HOST)
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
    return "success" in output


def executable_exists_in_image(image, path):
    print("Checking for %s in %s" % (path, image))
    cmd = "bash -c '[ ! -x %s ] || echo success' " % (path,)
    output = run_docker_command(image=image, command=cmd)
    return "success" in output


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


class TestContainer(Container):

    def state(self):
        return self.inspect_container["State"]

    def status(self):
        return self.state()["Status"]

    def shutdown(self):
        self.stop()
        self.remove()

    def execute(self, command):
        eid = self.create_exec(command)
        return self.start_exec(eid)

    def wait(self, timeout):
        return self.client.wait(self.id, timeout)


class TestCluster():

    def __init__(self, name, working_dir, config_file):
        config_file_path = os.path.join(working_dir, config_file)
        cfg_file = ConfigFile.from_filename(config_file_path)
        c = ConfigDetails(working_dir, [cfg_file],)
        self.cd = load(c)
        self.name = name

    def get_project(self):
        # Dont reuse the client to fix this bug : https://github.com/docker/compose/issues/1275
        client = docker_client(Environment())
        project = Project.from_config(self.name, self.cd, client)
        return project

    def start(self):
        self.shutdown()
        self.get_project().up()

    def is_running(self):
        state = [container.is_running for container in self.get_project().containers()]
        return all(state) and len(state) > 0

    def is_service_running(self, service_name):
        return self.get_container(service_name).is_running

    def shutdown(self):
        project = self.get_project()
        project.down(ImageType.none, True, True)
        project.remove_stopped()

    def get_container(self, service_name, stopped=False):
        return self.get_project().get_service(service_name).get_container()

    def exit_code(self, service_name):
        containers = self.get_project().containers([service_name], stopped=True)
        return containers[0].exit_code

    def wait(self, service_name, timeout):
        container = self.get_project().containers([service_name], stopped=True)
        if container[0].is_running:
            return self.get_project().client.wait(container[0].id, timeout)

    def run_command_on_service(self, service_name, command):
        return self.run_command(command, self.get_container(service_name))

    def service_logs(self, service_name, stopped=False):
        if stopped:
            containers = self.get_project().containers([service_name], stopped=True)
            print(containers[0].logs())
            return containers[0].logs()
        else:
            return self.get_container(service_name).logs()

    def run_command(self, command, container):
        print("Running %s on %s :" % (command, container))
        eid = container.create_exec(command)
        output = container.start_exec(eid)
        print("\n%s " % output)
        return output

    def run_command_on_all(self, command):
        results = {}
        for container in self.get_project().containers():
            results[container.name_without_project] = self.run_command(command, container)

        return results
