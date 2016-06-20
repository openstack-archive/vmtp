# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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

from instance import Instance as Instance
from perf_tool import PingTool

class PerfInstance(Instance):
    '''An openstack instance to run performance tools
    '''
    def __init__(self, name, config, comp=None, net=None, server=False):
        Instance.__init__(self, name, config, comp, net)
        self.is_server = server
        if 'I' in config.protocols:
            self.ping = PingTool(self)
        else:
            self.ping = None
        if config.tp_tool:
            self.tp_tool = config.tp_tool(self)
        else:
            self.tp_tool = None

    # No args is reserved for native host server
    def create(self, image=None, flavor_type=None,
               ssh_access=None, nics=None, az=None,
               management_network_name=None,
               sec_group=None,
               init_file_name=None):
        '''Create an instance
        :return: True on success, False on error
        '''
        rc = Instance.create(self, image, flavor_type, ssh_access,
                             nics, az,
                             management_network_name,
                             sec_group,
                             init_file_name)
        if not rc:
            return False
        if self.tp_tool and not self.tp_tool.install():
            return False
        self.add_multicast_route()
        if not self.is_server:
            return True
        if self.tp_tool and not self.tp_tool.start_server():
            return False
        return True

    def run_client(self, label, dest_ip, target_instance, mss=None,
                   bandwidth=0,
                   bidirectional=False,
                   az_to=None):
        '''test iperf client using the default TCP window size
        (tcp window scaling is normally enabled by default so setting explicit window
        size is not going to help achieve better results)
        :return: a dictionary containing the results of the run
        '''
        # Latency (ping rtt)
        if 'I' in self.config.protocols:
            ping_res = self.ping.run_client(dest_ip)
        else:
            ping_res = None

        # TCP/UDP throughput with tp_tool, returns a list of dict
        if self.tp_tool and (not ping_res or 'error' not in ping_res):
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
        if 'multicast_addr' in self.config:
            res['multicast_address'] = self.config.multicast_addr
        # consolidate results for all tools
        if ping_res:
            tp_tool_res.append(ping_res)
        res['results'] = tp_tool_res
        return res

    # Override in order to terminate the perf server
    def dispose(self):
        if self.tp_tool:
            self.tp_tool.dispose()
        Instance.dispose(self)
