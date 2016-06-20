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

import re

from log import LOG
import monitor
import netaddr
import sshutils


# a dictionary of sequence number indexed by a name prefix
prefix_seq = {}

#
# An openstack instance (can be a VM or a LXC)
#
class Instance(object):

    def __init__(self, name, config, comp=None, net=None):
        if name not in prefix_seq:
            prefix_seq[name] = 1
        seq = prefix_seq[name]
        prefix_seq[name] = seq + 1
        self.name = name + str(seq)
        self.comp = comp
        self.net = net
        self.az = None
        self.config = config
        # internal network IP
        self.internal_ip = None
        self.ssh_access = sshutils.SSHAccess()
        self.ssh_ip_id = None
        self.instance = None
        self.ssh = None
        self.port = None
        self.created_multicast_route = False
        if config.gmond_svr_ip:
            self.gmond_svr = config.gmond_svr_ip
        else:
            self.gmond_svr = None
        if config.gmond_svr_port:
            self.gmond_port = int(config.gmond_svr_port)
        else:
            self.gmond_port = 0
        self.config_drive = config.config_drive
        self.no_floatingip = config.no_floatingip

    # Setup the ssh connectivity
    # this function is only used for native hosts
    # Returns True if success
    def setup_ssh(self, host_access):
        # used for displaying the source IP in json results
        if not self.internal_ip:
            self.internal_ip = host_access.host
        self.ssh_access = host_access
        self.display('Setup SSH for %s@%s' % (host_access.username, host_access.host))
        self.ssh = sshutils.SSH(self.ssh_access,
                                connect_retry_count=self.config.ssh_retry_count)
        return True

    def get_network_interface(self, port_info):
        ip_address = port_info['fixed_ips'][0]['ip_address']
        subnet_id = port_info['fixed_ips'][0]['subnet_id']
        subnet_info = self.net.neutron_client.show_subnet(subnet_id)['subnet']

        cidr = netaddr.IPNetwork(subnet_info['cidr'])
        network_dict = {
            'ip_address': ip_address,
            'netmask': str(cidr.netmask),
            'network': str(cidr.network),
            'broadcast': str(cidr.broadcast),
            'gateway': subnet_info['gateway_ip'],
            'dns': ''
        }
        if subnet_info['dns_nameservers']:
            dns_servers = ','.join(subnet_info['dns_nameservers'])
            network_dict['dns'] = 'dns-nameservers %s\n' % dns_servers

        retStr = (
            '# The loopback network interface\n'
            'auto lo\n'
            'iface lo inet loopback\n'
            '\n'
            '# The primary network interface\n'
            'auto eth0\n'
            'iface eth0 inet static\n'
            '        address %(ip_address)s\n'
            '        netmask %(netmask)s\n'
            '        network %(network)s\n'
            '        broadcast %(broadcast)s\n'
            '        gateway %(gateway)s\n'
            '        %(dns)s'
        ) % network_dict

        return retStr

    # Create a new VM instance, associate a floating IP for ssh access
    # and extract internal network IP
    # Retruns True if success, False otherwise
    def create(self, image, flavor_type,
               ssh_access, int_net,
               az,
               internal_network_name,
               sec_group,
               init_file_name=None):
        # if ssh is created it means this is a native host not a vm
        if self.ssh:
            return True
        self.buginf('Starting on zone %s', az)
        self.az = az

        if init_file_name:
            user_data = open(init_file_name)
        else:
            user_data = None

        if self.config.vnic_type or self.config.no_dhcp:
            # create the VM by passing a port ID instead of a net ID
            self.port = self.net.create_port(int_net['id'],
                                             [sec_group.id],
                                             self.config.vnic_type)
            nics = [{'port-id': self.port['id']}]
            # no need to create server with a security group since
            # we already have the port created with it
            sec_group = None
        else:
            # create the VM by passing a net ID
            nics = [{'net-id': int_net['id']}]

        files = None
        if self.config.no_dhcp:
            network_interface = self.get_network_interface(self.port)
            files = {'/etc/network/interfaces': network_interface}

        self.instance = self.comp.create_server(self.name,
                                                image,
                                                flavor_type,
                                                self.config.public_key_name,
                                                nics,
                                                sec_group,
                                                az,
                                                user_data,
                                                self.config_drive,
                                                files,
                                                self.config.generic_retry_count)
        if user_data:
            user_data.close()
        if not self.instance:
            self.display('Server creation failed')
            return False

        # clone the provided ssh access to pick up user name and key pair
        self.ssh_access.copy_from(ssh_access)

        # If reusing existing management network skip the floating ip creation and association to VM
        # Assume management network has direct access
        if self.config.reuse_network_name:
            self.ssh_access.host = self.instance.networks[internal_network_name][0]
            self.internal_ip = self.ssh_access.host
        else:
            # Set the internal ip to the correct ip for v4 and v6
            for ip_address in self.instance.networks[internal_network_name]:
                ip = netaddr.IPAddress(ip_address)
                if self.config.ipv6_mode:
                    if ip.version == 6:
                        self.internal_ip = ip_address
                    else:
                        ipv4_fixed_address = ip_address
                else:
                    if ip.version == 4:
                        self.internal_ip = ip_address
                        ipv4_fixed_address = ip_address
            if self.no_floatingip:
                self.ssh_access.host = self.internal_ip
            else:
                fip = self.net.create_floating_ip()
                if not fip:
                    self.display('Floating ip creation failed.')
                    return False
                self.ssh_access.host = fip['floatingip']['floating_ip_address']
                self.ssh_ip_id = fip['floatingip']['id']
                self.display('Associating floating IP %s', self.ssh_access.host)
                self.instance.add_floating_ip(self.ssh_access.host, ipv4_fixed_address)

        # extract the IP for the data network
        self.display('Internal network IP: %s', self.internal_ip)
        self.display('SSH IP: %s', self.ssh_access.host)

        # create ssh session
        if not self.setup_ssh(self.ssh_access):
            return False
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
                self.display('error=%s' % (err))
            return None
        self.buginf('%s', cmd_output)
        return cmd_output

    # Display a status message with the standard header that has the instance
    # name (e.g. [foo] some text)
    def display(self, fmt, *args):
        LOG.info(('[%s] ' + fmt) % ((self.name,) + args))

    # Debugging message, to be printed only in debug mode
    def buginf(self, fmt, *args):
        LOG.debug(('[%s] ' + fmt) % ((self.name,) + args))

    # Ping an IP from this instance
    def ping_check(self, target_ip, ping_count, pass_threshold):
        return self.ssh.ping_check(target_ip, ping_count, pass_threshold)

    # Given a message size verify if ping without fragmentation works or fails
    # Returns True if success
    def ping_do_not_fragment(self, msg_size, ip_address):
        cmd = "ping -M do -c 1 -s " + str(msg_size) + " " + ip_address
        cmd_output = self.exec_command(cmd)
        match = re.search('100% packet loss', cmd_output)
        if match:
            return False
        else:
            return True

    def add_multicast_route(self, ifname=None):
        if not ifname:
            cmd = "route -n | grep 'UG[ \t]' | awk '{print $8}'"  # name of the default interface
            (status, ifname, err) = self.ssh.execute(cmd, timeout=10)
            if status == 127 or ifname[0:5] == "usage":
                cmd = "netstat -nr | grep default  | awk '{print $6}'"
                (status, ifname, err) = self.ssh.execute(cmd, timeout=10)

        cmd = "ip route add 224.0.0.0/4 dev " + ifname
        (status, _, _) = self.ssh.execute(cmd, timeout=10)
        if status == 127:
            cmd = "route add -net 224.0.0.0/4 dev " + ifname
            (status, _, _) = self.ssh.execute(cmd, timeout=10)
        self.created_multicast_route = status == 0
        return status

    def del_multicast_route(self):
        (status, _, _) = self.ssh.execute("ip route delete 224.0.0.0/4", timeout=10)
        if status == 127:
            status = self.ssh.execute("route delete -net 224.0.0.0/4", timeout=10)
        return status


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
        cmd_output = self.exec_command(cmd)
        return int(cmd_output)

    # scp a file from the local host to the instance
    # Returns True if dest file already exists or scp succeeded
    #         False in case of scp error
    def scp(self, tool_name, source, dest):

        # check if the dest file is already present
        if self.ssh.stat(dest):
            self.buginf('tool %s already present - skipping install',
                        tool_name)
            return True

        # scp over the tool binary
        self.buginf('Copying %s to target...', tool_name)
        rc = self.ssh.put_file_to_host(source, dest)

        return True if rc else False

    def get_cmd_duration(self):
        '''Get the duration of the client run
        Will normally return the time configured in config.time
        If cpu monitoring is enabled will make sure that this time is at least
        30 seconds (to be adjusted based on metric collection frequency)
        '''
        if self.gmond_svr:
            return max(30, self.config.time)
        return self.config.time

    def exec_with_cpu(self, cmd):
        '''If cpu monitoring is enabled (--monitor) collect CPU in the background
        while the test is running
        :param duration: how long the command will run in seconds
        :return:  a tuple (cmd_output, cpu_load)
        '''
        # ssh timeout should be at least set to the command duration
        # we add 20 seconds to it as a safety
        timeout = self.get_cmd_duration() + 20
        if self.gmond_svr:
            gmon = monitor.Monitor(self.gmond_svr, self.gmond_port)
            # Adjust this frequency based on the collectors update frequency
            # Here we assume 10 second and a max of 20 samples
            gmon.start_monitoring_thread(freq=10, count=20)
            cmd_output = self.exec_command(cmd, timeout)
            gmon.stop_monitoring_thread()
            # insert the cpu results into the results
            cpu_load = gmon.build_cpu_metrics()
        else:
            cmd_output = self.exec_command(cmd, timeout)
            cpu_load = None
        return (cmd_output, cpu_load)

    # Delete the floating IP
    # Delete the server instance
    # Dispose the ssh session
    def dispose(self):
        if self.created_multicast_route:
            self.del_multicast_route()
        if self.ssh_ip_id:
            self.net.delete_floating_ip(self.ssh_ip_id)
            self.buginf('Floating IP %s deleted', self.ssh_access.host)
            self.ssh_ip_id = None
        if self.instance:
            self.comp.delete_server(self.instance)
            self.buginf('Instance deleted')
            self.instance = None
        if self.port:
            self.net.delete_port(self.port)
        if self.ssh:
            self.ssh.close()
            self.ssh = None
