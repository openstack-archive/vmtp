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

import os
import re
import stat
import subprocess

from perf_tool import PingTool
import sshutils

from base_compute import BaseCompute
from wrk_tool import WrkTool

# An openstack instance (can be a VM or a LXC)
class PerfInstance(BaseCompute):

    def __init__(self, nova_client, user_name, config=None, is_server=False):

        BaseCompute.__init__(self, nova_client, user_name)

        if not config:
            # HACK ALERT!!!
            # We are expecting to see a valid config, here we just hack
            class config:
                ssh_vm_username = "ubuntu"
                gmond_svr_ip = None
                gmond_svr_port = None
                tp_tool = None
                http_tool = WrkTool
                perf_tool_path = './tools'
                private_key_file = './ssh/id_rsa'
                ssh_retry_count = 50
                debug = True
                time = 10
                vm_bandwidth = None

        self.config = config
        self.internal_ip = None
        self.ssh_ip = None
        self.ssh_user = config.ssh_vm_username
        self.ssh = None
        self.port = None
        self.is_server = is_server
        self.name = "Test"

        if config.gmond_svr_ip:
            self.gmond_svr = config.gmond_svr_ip
        else:
            self.gmond_svr = None
        if config.gmond_svr_port:
            self.gmond_port = int(config.gmond_svr_port)
        else:
            self.gmond_port = 0

        self.ping = PingTool(self)
        if config.tp_tool:
            self.tp_tool = config.tp_tool(self, config.perf_tool_path)
        else:
            self.tp_tool = None
        if config.http_tool:
            self.http_tool = config.http_tool(self, config.perf_tool_path)
        else:
            self.http_tool = None

    def run_tp_client(self, label, dest_ip, target_instance,
                      mss=None, bandwidth=0, bidirectional=False, az_to=None):
        '''test iperf client using the default TCP window size
        (tcp window scaling is normally enabled by default so setting explicit window
        size is not going to help achieve better results)
        :return: a dictionary containing the results of the run
        '''
        # Latency (ping rtt)
        ping_res = self.ping.run_client(dest_ip)

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

        # consolidate results for all tools
        if ping_res:
            tp_tool_res.append(ping_res)
        res['results'] = tp_tool_res
        return res

    def run_http_client(self, target_url, threads, connections,
                        timeout=5, connection_type="New"):
        # Latency (ping rtt)
        # ping_res = self.ping.run_client(dest_ip)

        # HTTP Performance Measurement
        if self.http_tool:
            http_tool_res = self.http_tool.run_client(target_url,
                                                      threads,
                                                      connections,
                                                      timeout,
                                                      connection_type)
            res = {'target_url': target_url}
            if self.internal_ip:
                res['ip_from'] = self.internal_ip
            res['distro_id'] = self.ssh.distro_id
            res['distro_version'] = self.ssh.distro_version
        else:
            http_tool_res = []

        # consolidate results for all tools
        # if ping_res:
        #     http_tool_res.append(ping_res)
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
    # returns stdout
    def exec_command(self, cmd, timeout=30):
        (status, cmd_output, err) = self.ssh.execute(cmd, timeout=timeout)
        if status:
            self.display('ERROR cmd=%s' % (cmd))
            if cmd_output:
                self.display("%s", cmd_output)
            if err:
                self.display('error=%s', err)
        self.buginf('%s', cmd_output)
        return (status, cmd_output, err)

    # Display a status message with the standard header that has the instance
    # name (e.g. [foo] some text)
    def display(self, fmt, *args):
        print('[%s] ' + fmt) % ((self.name,) + args)

    # Debugging message, to be printed only in debug mode
    def buginf(self, fmt, *args):
        if self.config.debug:
            self.display(fmt, *args)

    # Ping an IP from this instance
    def ping_check(self, target_ip, ping_count, pass_threshold):
        return self.ssh.ping_check(target_ip, ping_count, pass_threshold)

    # Given a message size verify if ping without fragmentation works or fails
    # Returns True if success
    def ping_do_not_fragment(self, msg_size, ip_address):
        cmd = "ping -M do -c 1 -s " + str(msg_size) + " " + ip_address
        (_, cmd_output, _) = self.exec_command(cmd)
        match = re.search('100% packet loss', cmd_output)
        if match:
            return False
        else:
            return True

    # Set the interface IP address and mask
    def set_interface_ip(self, if_name, ip, mask):
        self.buginf('Setting interface %s to %s mask %s', if_name, ip, mask)
        cmd2apply = "sudo ifconfig %s %s netmask %s" % (if_name, ip, mask)
        (rc, _, _) = self.ssh.execute(cmd2apply)
        return rc

    # Get an interface IP address (returns None if error)
    def get_interface_ip(self, if_name):
        self.buginf('Getting interface %s IP and mask', if_name)
        cmd2apply = "ifconfig %s" % (if_name)
        (rc, res, _) = self.ssh.execute(cmd2apply)
        if rc:
            return None
        # eth5      Link encap:Ethernet  HWaddr 90:e2:ba:40:74:05
        #  inet addr:172.29.87.29  Bcast:172.29.87.31  Mask:255.255.255.240
        #  inet6 addr: fe80::92e2:baff:fe40:7405/64 Scope:Link
        match = re.search(r'inet addr:([\d\.]*) ', res)
        if not match:
            return None
        return match.group(1)

    # Set an interface MTU to passed in value
    def set_interface_mtu(self, if_name, mtu):
        self.buginf('Setting interface %s mtu to %d', if_name, mtu)
        cmd2apply = "sudo ifconfig %s mtu %d" % (if_name, mtu)
        (rc, _, _) = self.ssh.execute(cmd2apply)
        return rc

    # Get the MTU of an interface
    def get_interface_mtu(self, if_name):
        cmd = "cat /sys/class/net/%s/mtu" % (if_name)
        (_, cmd_output, _) = self.exec_command(cmd)
        return int(cmd_output)

    # Add static route
    def add_static_route(self, network, next_hop_ip, if_name=None):
        buginf_msg = "Adding static route %s with next hop %s" % (network,
                                                                  next_hop_ip)
        cmd = "sudo ip route add %s via %s" % (network, next_hop_ip)
        if if_name:
            buginf_msg += " and %s" % if_name
            cmd += " dev %s" % if_name
        self.buginf(buginf_msg)
        return self.ssh.execute(cmd)[0]

    # Get static route
    def get_static_route(self, network, next_hop_ip=None, if_name=None):
        cmd = "ip route show %s" % network
        if next_hop_ip:
            cmd += " via %s" % next_hop_ip
        if if_name:
            cmd += " dev %s" % if_name
        (rc, out, err) = self.ssh.execute(cmd)
        if rc:
            return err
        else:
            return out

    # Delete static route
    def delete_static_route(self, network, next_hop_ip=None, if_name=None):
        buginf_msg = "Deleting static route %s" % network
        cmd = "sudo ip route del %s" % network
        if next_hop_ip:
            buginf_msg = " with next hop %s" % next_hop_ip
            cmd += " via %s" % next_hop_ip
        if if_name:
            if next_hop_ip:
                buginf_msg = " and %s" % if_name
            else:
                buginf_msg = "with next hop %s" % if_name
            cmd += " dev %s" % if_name
        self.buginf(buginf_msg)
        return self.ssh.execute(cmd)[0]

    # scp a file from the local host to the instance
    # Returns True if dest file already exists or scp succeeded
    #         False in case of scp error
    def scp(self, tool_name, source, dest):

        # check if the dest file is already present
        if self.ssh.stat(dest):
            self.buginf('tool %s already present - skipping install', tool_name)
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
        self.buginf('Copying %s to target...', tool_name)
        self.buginf(scp_cmd)
        devnull = open(os.devnull, 'wb')
        rc = subprocess.call(scp_cmd, shell=True,
                             stdout=devnull, stderr=devnull)
        if rc:
            self.display('Copy to target failed rc=%d', rc)
            self.display(scp_cmd)
            return False
        return True

    def get_cmd_duration(self):
        '''Get the duration of the client run
        Will normally return the time configured in config.time
        If cpu monitoring is enabled will make sure that this time is at least
        30 seconds (to be adjusted based on metric collection frequency)
        '''
        if self.gmond_svr:
            return max(30, self.config.time)
        return self.config.time

    # Dispose the ssh session
    def dispose(self):
        if self.ssh:
            self.ssh.close()
            self.ssh = None
        # BaseCompute.dispose(self)
