import os  # NOQA

from mock import patch
import pytest

import confluent.docker_utils as utils
import confluent.docker_utils.dub as dub
from confluent.docker_utils import cub

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

def test_exit_if_all_absent():
    """Should exit when none of enviroments are present"""

    all_absent_envs = ["NOT_PRESENT_1", "NOT_PRESENT_2"]

    with patch.dict("os.environ", {}):
        assert dub.exit_if_all_absent(all_absent_envs) == False

    fake_environ = {
        all_absent_envs[0]: "PRESENT",
    }

    with patch.dict("os.environ", fake_environ):
        assert dub.exit_if_all_absent(all_absent_envs)


def test_env_to_props():

    fake_environ = {
        "KAFKA_FOO": "foo",
        "KAFKA_FOO_BAR": "bar",
        "KAFKA_IGNORED": "ignored",
        "KAFKA_WITH__UNDERSCORE": "with underscore",
        "KAFKA_WITH__UNDERSCORE_AND_MORE": "with underscore and more",
        "KAFKA_WITH___DASH": "with dash",
        "KAFKA_WITH___DASH_AND_MORE": "with dash and more"
    }

    with patch.dict('os.environ', fake_environ):
        result = dub.env_to_props("KAFKA_", "kafka.", exclude = ["KAFKA_IGNORED"])
        assert "kafka.foo" in result
        assert "kafka.foo.bar" in result
        assert "kafka.ignored" not in result
        assert "kafka.with_underscore" in result
        assert "kafka.with_underscore.and.more" in result
        assert "kafka.with-dash" in result
        assert "kafka.with-dash.and.more" in result

@pytest.fixture(scope="module")
def ecr_login():
    # in AWS env, do a login.
    if os.getenv('AWS_DEFAULT_REGION') is not None:
        utils.ecr_login()


@pytest.fixture(scope="module")
def official_image(ecr_login):
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


def test_log4j_config_arg_for_log4j_v1():
    assert cub.log4j_config_arg() == '-Dlog4j.configuration'


def test_log4j_config_arg_for_log4j_v2():
    with patch('confluent.docker_utils.cub.use_log4j2', return_value=True):
        assert cub.log4j_config_arg() == '-Dlog4j2.configurationFile'


def test_log4j_config_file_for_log4j_v1():
    assert cub.log4j2_config_file() == "file:/etc/cp-base-new/log4j.properties"


def test_log4j_config_file_for_log4j_v2():
    with patch('confluent.docker_utils.cub.use_log4j2', return_value=True):
        assert cub.log4j2_config_file() == "/etc/cp-base-new/log4j2.yaml"
