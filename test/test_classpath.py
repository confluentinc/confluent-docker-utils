import os
import sys
import importlib
from mock import patch


def _load_cub_with_env(env):
    with patch.dict('os.environ', env, clear=True):
        # Ensure a fresh import to recompute CLASSPATH
        if 'confluent.docker_utils.cub' in sys.modules:
            del sys.modules['confluent.docker_utils.cub']
        mod = importlib.import_module('confluent.docker_utils.cub')
        return mod


def test_classpath_default_kept_when_no_extra():
    cub = _load_cub_with_env({})
    assert cub.CLASSPATH == cub.DEFAULT_BASE_CLASSPATH


def test_classpath_with_single_dir_via_CUB_CLASSPATH_DIRS():
    cub = _load_cub_with_env({'CUB_CLASSPATH_DIRS': '/opt/libs'})
    base_unquoted = cub.DEFAULT_BASE_CLASSPATH[1:-1]
    expected = '"' + base_unquoted + ':' + '/opt/libs/*' + '"'
    assert cub.CLASSPATH == expected


def test_classpath_with_multiple_dirs_and_delimiters():
    cub = _load_cub_with_env({'CUB_CLASSPATH_DIRS': '/opt/a, /opt/b;/opt/c: /opt/d/*'})
    base_unquoted = cub.DEFAULT_BASE_CLASSPATH[1:-1]
    extras = ['/opt/a/*', '/opt/b/*', '/opt/c/*', '/opt/d/*']
    expected = '"' + ':'.join([base_unquoted] + extras) + '"'
    assert cub.CLASSPATH == expected


def test_classpath_with_fallback_CUB_EXTRA_CLASSPATH():
    cub = _load_cub_with_env({'CUB_EXTRA_CLASSPATH': '/ext/libs/'})
    base_unquoted = cub.DEFAULT_BASE_CLASSPATH[1:-1]
    expected = '"' + base_unquoted + ':' + '/ext/libs/*' + '"'
    assert cub.CLASSPATH == expected


def test_classpath_respects_explicit_CUB_CLASSPATH_when_no_extra():
    cub = _load_cub_with_env({'CUB_CLASSPATH': '"/custom/base1/*:/custom/base2/*"'})
    assert cub.CLASSPATH == '"/custom/base1/*:/custom/base2/*"'
