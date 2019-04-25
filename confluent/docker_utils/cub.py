#!/usr/bin/env python
#
# Copyright 2017 Confluent Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Confluent utility belt.

This script contains a set of utility functions required for running the
Confluent platform on docker.

The script supports following commands:

1. kafka-ready : Ensures a Kafka cluster is ready to accept client requests.
2. zk-ready: Ensures that a Zookeeper ensemble is ready to accept client requests.
3. sr-ready: Ensures that Schema Registry is ready to accept client requests.
4. kr-ready: Ensures that Kafka REST Proxy is ready to accept client requests.
5. listeners: Derives the listeners property from advertised.listeners.
6. ensure-topic: Ensure that topic exists and is vaild.
7. connect-ready : Ensures a Connect cluster is ready to accept connector tasks.
8. ksql-server-ready : Ensures a KSQL server cluster is ready to accept KSQL queries.
9. control-center-ready : Ensures Confluent Control Center UI is ready.

These commands log any output to stderr and returns with exitcode 0 if successful, 1 otherwise.

"""
from __future__ import print_function
import os
import sys
import socket
import time
import re
import requests
import subprocess

CLASSPATH = os.environ.get("CUB_CLASSPATH", '"/usr/share/java/cp-base/*:/usr/share/java/cp-base-new/*"')


def wait_for_service(host, port, timeout):
    """Waits for a service to start listening on a port.

    Args:
        host: Hostname where the service is hosted.
        port: Port where the service is expected to bind.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and the service is unreachable, True otherwise.

    """
    start = time.time()
    while True:
        try:
            s = socket.create_connection((host, int(port)), float(timeout))
            s.close()
            return True
        except socket.error:
            pass

        time.sleep(1)
        if time.time() - start > timeout:
            return False


def check_zookeeper_ready(connect_string, timeout):
    """Waits for a Zookeeper ensemble be ready. This commands uses the Java
       docker-utils library to get the Zookeeper status.
       This command supports a secure Zookeeper cluster. It expects the KAFKA_OPTS
       enviornment variable to contain the JAAS configuration.

    Args:
        connect_string: Zookeeper connection string (host:port, ....)
        timeout: Time in secs to wait for the Zookeeper to be available.

    Returns:
        False, if the timeout expires and Zookeeper is unreachable, True otherwise.

    """
    cmd_template = """
             java {jvm_opts} \
                 -cp {classpath} \
                 io.confluent.admin.utils.cli.ZookeeperReadyCommand \
                 {connect_string} \
                 {timeout_in_ms}"""

    # This is to ensure that we include KAFKA_OPTS only if the jaas.conf has
    # entries for zookeeper. If you enable SASL, it is recommended that you
    # should enable it for all the components. This is an option if SASL
    # cannot be enabled on Zookeeper.
    jvm_opts = ""
    is_zk_sasl_enabled = os.environ.get("ZOOKEEPER_SASL_ENABLED") or ""

    if (not is_zk_sasl_enabled.upper() == "FALSE") and os.environ.get("KAFKA_OPTS"):
        jvm_opts = os.environ.get("KAFKA_OPTS")

    cmd = cmd_template.format(
        classpath=CLASSPATH,
        jvm_opts=jvm_opts or "",
        connect_string=connect_string,
        timeout_in_ms=timeout * 1000)

    return subprocess.call(cmd, shell=True) == 0


def check_kafka_ready(expected_brokers, timeout, config, bootstrap_broker_list=None, zookeeper_connect=None, security_protocol=None):
    """Waits for a Kafka cluster to be ready and have at least the
       expected_brokers to present. This commands uses the Java docker-utils
       library to get the Kafka status.

       This command supports a secure Kafka cluster. If SSL is enabled, it
       expects the client_properties file to have the relevant SSL properties.
       If SASL is enabled, the command expects the JAAS config to be present in the
       KAFKA_OPTS environment variable and the SASL properties to present in the
       client_properties file.


    Args:
        expected_brokers: expected number of brokers in the cluster.
        timeout: Time in secs to wait for the Zookeeper to be available.
        config: properties file with client config for SSL and SASL.
        security_protocol: Security protocol to use.
        bootstrap_broker_list: Kafka bootstrap broker list string (host:port, ....)
        zookeeper_connect: Zookeeper connect string.

    Returns:
        False, if the timeout expires and Kafka cluster is unreachable, True otherwise.

    """
    cmd_template = """
             java {jvm_opts} \
                 -cp {classpath} \
                 io.confluent.admin.utils.cli.KafkaReadyCommand \
                 {expected_brokers} \
                 {timeout_in_ms}"""

    cmd = cmd_template.format(
        classpath=CLASSPATH,
        jvm_opts=os.environ.get("KAFKA_OPTS") or "",
        bootstrap_broker_list=bootstrap_broker_list,
        expected_brokers=expected_brokers,
        timeout_in_ms=timeout * 1000)

    if config:
        cmd = "{cmd} --config {config_path}".format(cmd=cmd, config_path=config)

    if security_protocol:
        cmd = "{cmd} --security-protocol {protocol}".format(cmd=cmd, protocol=security_protocol)

    if bootstrap_broker_list:
        cmd = "{cmd} -b {broker_list}".format(cmd=cmd, broker_list=bootstrap_broker_list)
    else:
        cmd = "{cmd} -z {zookeeper_connect}".format(cmd=cmd, zookeeper_connect=zookeeper_connect)

    exit_code = subprocess.call(cmd, shell=True)

    if exit_code == 0:
        return True
    else:
        return False


def check_schema_registry_ready(host, port, service_timeout):
    """Waits for Schema registry to be ready.

    Args:
        host: Hostname where schema registry is hosted.
        port: Schema registry port.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and Schema registry is unreachable, True otherwise.

    """

    # Check if you can connect to the endpoint
    status = wait_for_service(host, port, service_timeout)

    if status:
        # Check if service is responding as expected to basic request
        url = "http://%s:%s/config" % (host, port)
        r = requests.get(url)
        # The call should always return the compatibilityLevel
        if r.status_code // 100 == 2 and 'compatibilityLevel' in str(r.text):
            return True
        else:
            print("Unexpected response with code: %s and content: %s" % (str(r.status_code), str(r.text)), file=sys.stderr)
            return False
    else:
        print("%s cannot be reached on port %s." % (str(host), str(port)), file=sys.stderr)
        return False


def check_kafka_rest_ready(host, port, service_timeout):
    """Waits for Kafka REST Proxy to be ready.

    Args:
        host: Hostname where Kafka REST Proxy is hosted.
        port: Kafka REST Proxy port.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and Kafka REST Proxy is unreachable, True otherwise.

    """
    # Check if you can connect to the endpoint
    status = wait_for_service(host, port, service_timeout)

    if status:

        # Check if service is responding as expected to basic request
        # Try to get topic list
        # NOTE: this will only test ZK <> REST Proxy interaction
        url = "http://%s:%s/topics" % (host, port)
        r = requests.get(url)
        if r.status_code // 100 == 2:
            return True
        else:
            print("Unexpected response with code: %s and content: %s" % (str(r.status_code), str(r.text)), file=sys.stderr)
            return False
    else:
        print("%s cannot be reached on port %s." % (str(host), str(port)), file=sys.stderr)
        return False


def check_connect_ready(host, port, service_timeout):
    """Waits for Connect to be ready.

    Args:
        host: Hostname where Connect worker is hosted.
        port: Connect port.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and Connect is not ready, True otherwise.

    """

    # Check if you can connect to the endpoint
    status = wait_for_service(host, port, service_timeout)

    if status:
        # Check if service is responding as expected to basic request
        url = "http://%s:%s" % (host, port)
        r = requests.get(url)
        # The call should always return a json string including version
        if r.status_code // 100 == 2 and 'version' in str(r.text):
            return True
        else:
            print("Unexpected response with code: %s and content: %s" % (str(r.status_code), str(r.text)), file=sys.stderr)
            return False
    else:
        print("%s cannot be reached on port %s." % (str(host), str(port)), file=sys.stderr)
        return False


def check_ksql_server_ready(host, port, service_timeout):
    """Waits for KSQL server to be ready.

    Args:
        host: Hostname where KSQL server is hosted.
        port: KSQL server port.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and KSQL server is not ready, True otherwise.

    """

    # Check if you can connect to the endpoint
    status = wait_for_service(host, port, service_timeout)

    if status:
        # Check if service is responding as expected to basic request
        url = "http://%s:%s/info" % (host, port)
        r = requests.get(url)
        # The call should always return a json string including version
        if r.status_code // 100 == 2 and 'Ksql' in str(r.text):
            return True
        else:
            print("Unexpected response with code: %s and content: %s" % (str(r.status_code), str(r.text)), file=sys.stderr)
            return False
    else:
        print("%s cannot be reached on port %s." % (str(host), str(port)), file=sys.stderr)
        return False


def check_control_center_ready(host, port, service_timeout):
    """Waits for Confluent Control Center to be ready.

    Args:
        host: Hostname where Control Center is hosted.
        port: Control Center port.
        timeout: Time in secs to wait for the service to be available.

    Returns:
        False, if the timeout expires and Connect is not ready, True otherwise.

    """

    # Check if you can connect to the endpoint
    status = wait_for_service(host, port, service_timeout)

    if status:
        # Check if service is responding as expected to basic request
        url = "http://%s:%s" % (host, port)
        r = requests.get(url)
        # The call should always return a json string including version
        if r.status_code // 100 == 2 and 'Control Center' in str(r.text):
            return True
        else:
            print("Unexpected response with code: %s and content: %s" % (str(r.status_code), str(r.text)), file=sys.stderr)
            return False
    else:
        print("%s cannot be reached on port %s." % (str(host), str(port)), file=sys.stderr)
        return False


def get_kafka_listeners(advertised_listeners):
    """Derives listeners property from advertised.listeners. It just converts the
       hostname to 0.0.0.0 so that Kafka process listens to all the interfaces.

       For example, if
            advertised_listeners = PLAINTEXT://foo:9999,SSL://bar:9098, SASL_SSL://10.0.4.5:7888
            then, the function will return
            PLAINTEXT://0.0.0.0:9999,SSL://0.0.0.0:9098, SASL_SSL://0.0.0.0:7888

    Args:
        advertised_listeners: advertised.listeners string.

    Returns:
        listeners string.

    """
    host = re.compile(r'://(.*?):', re.UNICODE)
    return host.sub(r'://0.0.0.0:', advertised_listeners)


def ensure_topic(config, file, timeout, create_if_not_exists):
    """Ensures that the topic in the file exists on the cluster and has valid config.


    Args:
        config: client config (properties file).
        timeout: Time in secs for all operations.
        file: YAML file with topic config.
        create_if_not_exists: Creates topics if they dont exist.

    Returns:
        False, if the timeout expires and Kafka cluster is unreachable, True otherwise.

    """
    cmd_template = """
             java {jvm_opts} \
                 -cp {classpath} \
                 io.confluent.kafkaensure.cli.TopicEnsureCommand \
                 --config {config} \
                 --file {file} \
                 --create-if-not-exists {create_if_not_exists} \
                 --timeout {timeout_in_ms}"""

    cmd = cmd_template.format(
        classpath=CLASSPATH,
        jvm_opts=os.environ.get("KAFKA_OPTS") or "",
        config=config,
        file=file,
        timeout_in_ms=timeout * 1000,
        create_if_not_exists=create_if_not_exists)

    exit_code = subprocess.call(cmd, shell=True)

    if exit_code == 0:
        return True
    else:
        return False


def main():
    import argparse
    root = argparse.ArgumentParser(description='Confluent Platform Utility Belt.')

    actions = root.add_subparsers(help='Actions', dest='action')

    zk = actions.add_parser('zk-ready', description='Check if ZK is ready.')
    zk.add_argument('connect_string', help='Zookeeper connect string.')
    zk.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    kafka = actions.add_parser('kafka-ready', description='Check if Kafka is ready.')
    kafka.add_argument('expected_brokers', help='Minimum number of brokers to wait for', type=int)
    kafka.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)
    kafka_or_zk = kafka.add_mutually_exclusive_group(required=True)
    kafka_or_zk.add_argument('-b', '--bootstrap_broker_list', help='List of bootstrap brokers.')
    kafka_or_zk.add_argument('-z', '--zookeeper_connect', help='Zookeeper connect string.')
    kafka.add_argument('-c', '--config', help='Path to config properties file (required when security is enabled).')
    kafka.add_argument('-s', '--security-protocol', help='Security protocol to use when multiple listeners are enabled.')

    sr = actions.add_parser('sr-ready', description='Check if Schema Registry is ready.')
    sr.add_argument('host', help='Hostname for Schema Registry.')
    sr.add_argument('port', help='Port for Schema Registry.')
    sr.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    kr = actions.add_parser('kr-ready', description='Check if Kafka REST Proxy is ready.')
    kr.add_argument('host', help='Hostname for REST Proxy.')
    kr.add_argument('port', help='Port for REST Proxy.')
    kr.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    config = actions.add_parser('listeners', description='Get listeners value from advertised.listeners. Replaces host to 0.0.0.0')
    config.add_argument('advertised_listeners', help='advertised.listeners string.')

    te = actions.add_parser('ensure-topic', description='Ensure that topic exists and is valid.')
    te.add_argument('config', help='client config (properties file).')
    te.add_argument('file', help='YAML file with topic config.')
    te.add_argument('timeout', help='Time in secs for all operations.', type=int)
    te.add_argument('--create_if_not_exists', help='Create topics if they do not yet exist.', action='store_true')

    cr = actions.add_parser('connect-ready', description='Check if Connect is ready.')
    cr.add_argument('host', help='Hostname for Connect worker.')
    cr.add_argument('port', help='Port for Connect worker.')
    cr.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    ksqlr = actions.add_parser('ksql-server-ready', description='Check if KSQL server is ready.')
    ksqlr.add_argument('host', help='Hostname for KSQL server.')
    ksqlr.add_argument('port', help='Port for KSQL server.')
    ksqlr.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    c3r = actions.add_parser('control-center-ready', description='Check if Confluent Control Center is ready.')
    c3r.add_argument('host', help='Hostname for Control Center.')
    c3r.add_argument('port', help='Port for Control Center.')
    c3r.add_argument('timeout', help='Time in secs to wait for service to be ready.', type=int)

    if len(sys.argv) < 2:
        root.print_help()
        sys.exit(1)

    args = root.parse_args()

    success = False

    if args.action == "zk-ready":
        success = check_zookeeper_ready(args.connect_string, int(args.timeout))
    elif args.action == "kafka-ready":
        success = check_kafka_ready(int(args.expected_brokers), int(args.timeout), args.config, args.bootstrap_broker_list, args.zookeeper_connect,
                                    args.security_protocol)
    elif args.action == "sr-ready":
        success = check_schema_registry_ready(args.host, args.port, int(args.timeout))
    elif args.action == "kr-ready":
        success = check_kafka_rest_ready(args.host, args.port, int(args.timeout))
    elif args.action == "connect-ready":
        success = check_connect_ready(args.host, args.port, int(args.timeout))
    elif args.action == "ksql-server-ready":
        success = check_ksql_server_ready(args.host, args.port, int(args.timeout))
    elif args.action == "control-center-ready":
        success = check_control_center_ready(args.host, args.port, int(args.timeout))
    elif args.action == "ensure-topic":
        success = ensure_topic(args.config, args.file, int(args.timeout), args.create_if_not_exists)
    elif args.action == "listeners":
        listeners = get_kafka_listeners(args.advertised_listeners)
        if listeners:
            # Print the output to stdout. Don't delete this, this is not for debugging.
            print(listeners)
            success = True

    if success:
        sys.exit(0)
    else:
        sys.exit(1)
