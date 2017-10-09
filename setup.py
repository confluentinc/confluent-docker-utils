#!/usr/bin/env python

from pip.req import parse_requirements
import setuptools

# Filters out relative/local requirements (i.e. ../lib/utils)
remote_requirements = '\n'.join(str(r.req) for r in parse_requirements("requirements.txt", session='dummy') if r.req)

setuptools.setup(
    name='confluent-docker-utils',
    version='0.0.7',

    author="Confluent, Inc.",
    author_email="partner-support@confluent.io",

    description='Common utils for Docker image sanity tests',

    url="https://github.com/confluentinc/confluent-docker-utils",

    install_requires=remote_requirements,

    packages=['confluent'],

    include_package_data=True,

    python_requires='>=2.7',
    setup_requires=['setuptools-git'],

    entry_points={
        "console_scripts": [
            "cub = confluent.docker_utils.cub:main",
            "dub = confluent.docker_utils.dub:main",
        ]
    }
)
