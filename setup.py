from setuptools import setup


setup(
    name='confluent-docker-utils',
    version='0.0.36',

    author="Confluent, Inc.",
    author_email="partner-support@confluent.io",

    description='Common utils for Docker image sanity tests',

    url="https://github.com/confluentinc/confluent-docker-utils",

    install_requires=open('requirements.txt').read(),

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
