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

import log as logging

LOG = logging.getLogger(__name__)

class KBVMMappingAlgoNotSup(Exception):
    pass

class KBVMPlacementAlgoNotSup(Exception):
    pass

class KBScheduler(object):
    """
    1. VM Placements
    2. Mapping client VMs to target servers
    """

    @staticmethod
    def setup_vm_placement(role, vm_list, topology, avail_zone, algorithm):
        if not topology:
            # Will use nova-scheduler to pick up the hypervisors
            return
        if not avail_zone:
            # Default availability zone in NOVA
            avail_zone = "nova"

        if role == "Server":
            host_list = topology.servers_rack.split()
        else:
            host_list = topology.clients_rack.split()
        host_count = len(host_list)

        if algorithm == "Round-robin":
            host_idx = 0
            for ins in vm_list:
                ins.boot_info['avail_zone'] = "%s:%s" % (avail_zone, host_list[host_idx])
                host_idx = (host_idx + 1) % host_count
        else:
            LOG.error("Unsupported algorithm!")
            raise KBVMPlacementAlgoNotSup()

    @staticmethod
    def setup_vm_mappings(client_list, server_list, algorithm):
        # VM Mapping framework/algorithm to mapping clients to servers.
        # e.g. 1:1 mapping, 1:n mapping, n:1 mapping, etc.
        # Here we only support N*1:1, i.e. 1 client VM maps to 1 server VM, total of N pairs.
        if algorithm == "1:1":
            for idx, ins in enumerate(client_list):
                ins.target_url = "http://%s/index.html" %\
                    (server_list[idx].fip_ip or server_list[idx].fixed_ip)
                ins.user_data['target_url'] = ins.target_url
        else:
            LOG.error("Unsupported algorithm!")
            raise KBVMMappingAlgoNotSup()
