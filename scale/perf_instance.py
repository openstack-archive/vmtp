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
        self.ssh_access = None
        self.ssh = None
        self.port = None
        self.az = None

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
        res['ip_from'] = self.ssh_access.host
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

    # Send a command on the ssh session
    def exec_command(self, cmd, timeout=30):
        (status, cmd_output, err) = self.ssh.execute(cmd, timeout=timeout)
        return (status, cmd_output, err)

    # Dispose the ssh session
    def dispose(self):
        if self.ssh:
            self.ssh.close()
            self.ssh = None
