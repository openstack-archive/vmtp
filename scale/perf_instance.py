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

import sshutils

from base_compute import BaseCompute
import log as logging
from wrk_tool import WrkTool

LOG = logging.getLogger(__name__)

# An openstack instance (can be a VM or a LXC)
class PerfInstance(BaseCompute):

    def __init__(self, vm_name, network, config, is_server=False):
        BaseCompute.__init__(self, vm_name, network)

        self.config = config
        self.is_server = is_server
        self.boot_info = {}
        self.user_data = {}
        self.up_flag = False

        # SSH Configuration
        self.ssh_ip = None
        self.ssh_user = config.ssh_vm_username
        self.ssh = None
        self.port = None

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
        elif config.http_tool.name.lower() == 'wrk':
            self.http_tool = WrkTool(self, config.http_tool)
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
        res['ip_from'] = self.ssh_ip
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

    def http_client_parser(self, status, stdout, stderr):
        http_tool_res = self.http_tool.cmd_parser_run_client(status, stdout, stderr)
        res = {'vm_name': self.vm_name}
        res['target_url'] = self.target_url
        res['ip_from'] = self.ssh_ip

        # consolidate results for all tools
        res['results'] = http_tool_res
        return res

    # Setup the ssh connectivity
    # Returns True if success
    def setup_ssh(self, ssh_ip, ssh_user):
        # used for displaying the source IP in json results
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
