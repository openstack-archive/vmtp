# Copyright 2015 Cisco Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

import os
import stat
import subprocess
import time

import sshutils

from base_compute import BaseCompute
import log as logging
import redis
from wrk_tool import WrkTool

LOG = logging.getLogger(__name__)

# An openstack instance (can be a VM or a LXC)
class PerfInstance(BaseCompute):

    def __init__(self, vm_name, nova_client, user_name, config, is_server=False):
        BaseCompute.__init__(self, vm_name, nova_client, user_name)

        self.config = config
        self.internal_ip = None
        self.is_server = is_server

        # SSH Configuration
        self.ssh_ip = None
        self.ssh_user = config.ssh_vm_username
        self.ssh = None
        self.port = None

        # Redis Configuration
        self.redis_obj = None
        self.pubsub = None
        self.up_flag = False
        self.orches_chan_name = self.vm_name.lower() + "_orches"
        self.report_chan_name = self.vm_name.lower() + "_report"

        if 'tp_tool' not in config:
            self.tp_tool = None
        # elif config.tp_tool.lower() == 'nuttcp':
        #     self.tp_tool = nuttcp_tool.NuttcpTool
        # elif opts.tp_tool.lower() == 'iperf':
        #     self.tp_tool = iperf_tool.IperfTool
        # else:
        #     self.tp_tool = None

        if 'http_tool' not in config:
            self.http_tool = None
        elif config.http_tool.lower() == 'wrk':
            self.http_tool = WrkTool(self)
            self.target_server = None
            self.target_url = None
        else:
            self.http_tool = None

    def run_tp_client(self, label, dest_ip, target_instance,
                      mss=None, bandwidth=0, bidirectional=False, az_to=None):
        # NOTE: This function will not work, and pending to convert to use redis
        '''test iperf client using the default TCP window size
        (tcp window scaling is normally enabled by default so setting explicit window
        size is not going to help achieve better results)
        :return: a dictionary containing the results of the run
        '''
        # TCP/UDP throughput with tp_tool, returns a list of dict
        if self.tp_tool:
            tp_tool_res = self.tp_tool.run_client(dest_ip,
                                                  target_instance,
                                                  mss=mss,
                                                  bandwidth=bandwidth,
                                                  bidirectional=bidirectional)
        else:
            tp_tool_res = []

        res = {'ip_to': dest_ip}
        if self.internal_ip:
            res['ip_from'] = self.internal_ip
        if label:
            res['desc'] = label
        if self.az:
            res['az_from'] = self.az
        if az_to:
            res['az_to'] = az_to
        res['distro_id'] = self.ssh.distro_id
        res['distro_version'] = self.ssh.distro_version

        # consolidate results for all tools
        res['results'] = tp_tool_res
        return res

    # Target URL is supposed to be provided during the mapping stage
    def run_http_client(self, threads, connections,
                        timeout=5, connection_type="Keep-alive"):
        # HTTP Performance Measurement
        cmd = self.http_tool.cmd_run_client(self.target_url,
                                            threads,
                                            connections,
                                            timeout,
                                            connection_type)
        parser_cb = 'self.run_http_client_parser'
        self.redis_exec_command(cmd, parser_cb)

    def run_http_client_parser(self, status, stdout, stderr):
        http_tool_res = self.http_tool.cmd_parser_run_client(status, stdout, stderr)
        res = {'target_url': self.target_url}
        if self.internal_ip:
            res['ip_from'] = self.internal_ip

        # consolidate results for all tools
        res['results'] = http_tool_res
        return res

    # Setup the ssh connectivity
    # Returns True if success
    def setup_ssh(self, ssh_ip, ssh_user):
        # used for displaying the source IP in json results
        if not self.internal_ip:
            self.internal_ip = ssh_ip
        self.ssh_ip = ssh_ip
        self.ssh_user = ssh_user
        self.ssh = sshutils.SSH(self.ssh_user, self.ssh_ip,
                                key_filename=self.config.private_key_file,
                                connect_retry_count=self.config.ssh_retry_count)
        return True

    # Send a command on the ssh session
    def exec_command(self, cmd, timeout=30):
        (status, cmd_output, err) = self.ssh.execute(cmd, timeout=timeout)
        return (status, cmd_output, err)

    # Setup the redis connectivity
    def setup_redis(self, host=None, port=None, connection_pool=None):
        if connection_pool:
            self.redis_obj = redis.StrictRedis(connection_pool=connection_pool)
        else:
            self.redis_obj = redis.StrictRedis(host=host, port=port)

        # Check for connections to redis server
        for retry in xrange(1, self.config.redis_retry_count + 1):
            try:
                self.redis_obj.get("test")
            except (redis.exceptions.ConnectionError):
                LOG.warn("Connecting to redis server... Retry #%d", retry)
                time.sleep(1)
                continue
            break
        # Subscribe to message channel
        self.pubsub = self.redis_obj.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.report_chan_name)

        return True

    def redis_get_message(self):
        message = self.pubsub.get_message()
        while message and message['data'] == 'hello':
            # If a "hello" packet is received, the corresponding VM is up
            # running. We mark the flag for that VM, and skip all "hello"
            # messages received afterwards.
            if self.up_flag:
                message = self.pubsub.get_message()
            else:
                self.up_flag = True
                self.redis_acknowledge_hello()
                return (0, "", "")
        if not message:
            return None

        LOG.kbdebug(message)
        msg_body = eval(message['data'])
        status = int(msg_body['status'])
        stdout = msg_body['stdout']
        stderr = msg_body['stderr']
        parser_cb = msg_body['parser_cb']

        if parser_cb is not None:
            stdout = eval("%s(status, stdout, stderr)" % parser_cb)

        return (status, stdout, stderr)

    def redis_acknowledge_hello(self):
        self.redis_obj.publish(self.orches_chan_name, "iamhere")

    def redis_exec_command(self, cmd, parser_cb=None, timeout=30):
        # TODO(Add timeout support)
        msg_body = {'cmd': cmd, 'parser_cb': parser_cb}
        LOG.kbdebug(msg_body)
        self.redis_obj.publish(self.orches_chan_name, msg_body)

    # Check whether the HTTP Service is up running
    def check_http_service(self):
        cmd = 'while true; do\n'
        cmd += 'curl --head %s --connect-timeout 2 --silent\n' % (self.target_url)
        cmd += 'if [ $? -eq 0 ]; then break; fi\n'
        cmd += 'done'
        self.redis_exec_command(cmd, None)

    # Add static route
    def add_static_route(self, network, next_hop_ip, if_name=None):
        debug_msg = "Adding static route %s with next hop %s" % (network, next_hop_ip)
        cmd = "sudo ip route add %s via %s" % (network, next_hop_ip)
        if if_name:
            debug_msg += " and %s" % if_name
            cmd += " dev %s" % if_name
        LOG.kbdebug(debug_msg)
        self.redis_exec_command(cmd, None)

    # Get static route
    def get_static_route(self, network, next_hop_ip=None, if_name=None):
        cmd = "ip route show %s" % network
        if next_hop_ip:
            cmd += " via %s" % next_hop_ip
        if if_name:
            cmd += " dev %s" % if_name
        # TODO(Need to implement a parser_cb instead of passing None)
        self.redis_exec_command(cmd, None)

    # Delete static route
    def delete_static_route(self, network, next_hop_ip=None, if_name=None):
        debug_msg = "[%s] Deleting static route %s" % (self.vm_name, network)
        cmd = "sudo ip route del %s" % network
        if next_hop_ip:
            debug_msg = " with next hop %s" % next_hop_ip
            cmd += " via %s" % next_hop_ip
        if if_name:
            if next_hop_ip:
                debug_msg = " and %s" % if_name
            else:
                debug_msg = "with next hop %s" % if_name
            cmd += " dev %s" % if_name
        LOG.kbdebug(debug_msg)
        self.redis_exec_command(cmd, None)

    # scp a file from the local host to the instance
    # Returns True if dest file already exists or scp succeeded
    #         False in case of scp error
    def scp(self, tool_name, source, dest):

        # check if the dest file is already present
        if self.ssh.stat(dest):
            LOG.kbdebug("[%s] Tool %s already present - skipping install"
                        % (self.vm_name, tool_name))
            return True
        # scp over the tool binary
        # first chmod the local copy since git does not keep the permission
        os.chmod(source, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)

        # scp to the target
        scp_opts = '-o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'
        scp_cmd = 'scp -i %s %s %s %s@%s:%s' % (self.config.private_key_file,
                                                scp_opts,
                                                source,
                                                self.ssh_user,
                                                self.ssh_ip,
                                                dest)
        LOG.kbdebug("[%s] Copying %s to target..." % (self.vm_name, tool_name))
        LOG.kbdebug("[%s] %s" % (self.vm_name, scp_cmd))
        devnull = open(os.devnull, 'wb')
        rc = subprocess.call(scp_cmd, shell=True,
                             stdout=devnull, stderr=devnull)
        if rc:
            LOG.error("[%s] Copy to target failed rc=%d" % (self.vm_name, rc))
            LOG.error("[%s] %s" % (self.vm_name, scp_cmd))
            return False
        return True

    # Dispose the ssh session
    def dispose(self):
        if self.ssh:
            self.ssh.close()
            self.ssh = None
        if self.redis_obj:
            self.pubsub.unsubscribe()
            self.pubsub.close()
