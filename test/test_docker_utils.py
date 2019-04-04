import os  # NOQA

AWS_DEFAULT_REGION = os.getenv('AWS_DEFAULT_REGION')

from mock import patch
import pytest

import confluent.docker_utils as utils


OFFICIAL_IMAGE = "confluentinc/cp-base:latest"


def test_imports():
    """ Basic sanity tests until we write some real tests """
    import confluent.docker_utils  # noqa


def test_add_registry_and_tag():
    """ Inject registry and tag values from environment """

    base_image = "confluentinc/example"

    fake_environ = {
        "DOCKER_REGISTRY": "default-registry/",
        "DOCKER_TAG": "default-tag",
        "DOCKER_UPSTREAM_REGISTRY": "upstream-registry/",
        "DOCKER_UPSTREAM_TAG": "upstream-tag",
        "DOCKER_TEST_REGISTRY": "test-registry/",
        "DOCKER_TEST_TAG": "test-tag",
    }

    with patch.dict('os.environ', fake_environ):
        assert utils.add_registry_and_tag(base_image) == 'default-registry/confluentinc/example:default-tag'
        assert utils.add_registry_and_tag(base_image, scope="UPSTREAM") == 'upstream-registry/confluentinc/example:upstream-tag'
        assert utils.add_registry_and_tag(base_image, scope="TEST") == 'test-registry/confluentinc/example:test-tag'


@pytest.fixture(scope="module")
def official_image():
    # docker-py #1677
    import boto3
    import base64
    import docker
    import os
    print('AWS_DEFAULT_REGION=%s' % AWS_DEFAULT_REGION)
    assert os.getenv('AWS_DEFAULT_REGION') is not None
    ecr = boto3.client('ecr')
    login = ecr.get_authorization_token()
    b64token = login['authorizationData'][0]['authorizationToken'].encode('utf-8')
    username, password = base64.b64decode(b64token).decode('utf-8').split(':')
    registry = login['authorizationData'][0]['proxyEndpoint']
    client = docker.from_env()
    client.login(username, password, registry=registry)
    utils.pull_image(OFFICIAL_IMAGE)


@pytest.mark.integration
def test_image_exists(official_image):
    assert utils.image_exists(OFFICIAL_IMAGE)


@pytest.mark.integration
def test_path_exists_in_image(official_image):
    assert utils.path_exists_in_image(OFFICIAL_IMAGE, "/usr/local/bin/dub")
    assert utils.path_exists_in_image(OFFICIAL_IMAGE, "/usr/local/bin/cub")


@pytest.mark.integration
def test_run_docker_command(official_image):
    cmd = "java -version"
    expected = b'OpenJDK Runtime Environment (Zulu 8.'
    output = utils.run_docker_command(image=OFFICIAL_IMAGE, command=cmd)
    assert expected in output
