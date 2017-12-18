from unittest.mock import patch

import os

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
