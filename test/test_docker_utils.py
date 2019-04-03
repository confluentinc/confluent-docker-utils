import os  # NOQA
import unittest

from mock import patch

import confluent.docker_utils as utils


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


class IntegrationTest(unittest.TestCase):
    official_image = "confluentinc/cp-base:latest"

    @classmethod
    def setUpClass(cls):
        # pulls official image, used for the other tests.
        utils.pull_image(cls.official_image)

    def test_image_exists(self):
        self.assertTrue(utils.image_exists(self.official_image))

    def test_path_exists_in_image(self):
        self.assertTrue(utils.path_exists_in_image(self.official_image, "/usr/local/bin/dub"))
        self.assertTrue(utils.path_exists_in_image(self.official_image, "/usr/local/bin/cub"))

    def test_run_docker_command(self):
        cmd = "java -version"
        expected = b'OpenJDK Runtime Environment (Zulu 8.'
        output = utils.run_docker_command(image=self.official_image, command=cmd)
        self.assertTrue(expected in output)
