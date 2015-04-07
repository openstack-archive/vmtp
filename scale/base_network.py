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

import time

from perf_instance import PerfInstance

import base_compute
import netaddr
from neutronclient.common.exceptions import NetworkInUseClient

# Global CIDR shared by all objects of this class
# Enables each network to get a unique CIDR
START_CIDR = "1.0.0.0/16"
cidr = START_CIDR

def create_floating_ip(neutron_client, ext_net):
    """
    Function that creates a floating ip and returns it
    Accepts the neutron client and ext_net
    Module level function since this is not associated with a
    specific network instance
    """
    body = {
        "floatingip": {
            "floating_network_id": ext_net['id']
        }
    }
    fip = neutron_client.create_floatingip(body)
    return fip

def delete_floating_ip(neutron_client, fip):
    """
    Deletes the floating ip
    Module level function since this operation
    is not associated with a network
    """
    neutron_client.delete_floatingip(fip)

def find_external_network(neutron_client):
    """
    Find the external network
    and return it
    If no external network is found return None
    """
    networks = neutron_client.list_networks()['networks']
    for network in networks:
        if network['router:external']:
            return network

    print "No external network found!!!"
    return None


class BaseNetwork(object):
    """
    The Base class for neutron network operations
    1. Creates networks with 1 subnet inside each network
    2. Increments a global CIDR for all network instances
    3. Deletes all networks on completion
    4. Also interacts with the compute class for instances
    """



    def __init__(self, neutron_client, nova_client, user_name, shared_interface_ip=None):
        """
        Store the neutron client
        User name for this network
        and network object
        """
        self.neutron_client = neutron_client
        self.nova_client = nova_client
        self.user_name = user_name
        self.network = None
        self.instance_list = []
        self.secgroup_list = []
        self.keypair_list = []
        # Store the shared interface ip of router for tested and testing cloud
        self.shared_interface_ip = shared_interface_ip

    def create_compute_resources(self, network_prefix, config_scale):
        """
        Creates the compute resources includes the following resources
        1. VM instances
        2. Security groups
        3. Keypairs
        """
        # Create the security groups first
        for secgroup_count in range(config_scale['secgroups_per_network']):
            secgroup_instance = base_compute.SecGroup(self.nova_client)
            self.secgroup_list.append(secgroup_instance)
            secgroup_name = network_prefix + "_SG" + str(secgroup_count)
            secgroup_instance.create_secgroup_with_rules(secgroup_name)

        # Create the keypair list
        for keypair_count in range(config_scale['keypairs_per_network']):
            keypair_instance = base_compute.KeyPair(self.nova_client)
            self.keypair_list.append(keypair_instance)
            keypair_name = network_prefix + "_K" + str(keypair_count)
            keypair_instance.add_public_key(keypair_name, config_scale['public_key_file'])

        # Create the required number of VMs
        # Create the VMs on  specified network, first keypair, first secgroup
        if config_scale['use_floatingip']:
            external_network = find_external_network(self.neutron_client)
        print "Creating Virtual machines for user %s" % (self.user_name)
        for instance_count in range(config_scale['vms_per_network']):
            perf_instance = PerfInstance(self.nova_client, self.user_name)
            self.instance_list.append(perf_instance)
            vm_name = network_prefix + "_I" + str(instance_count)
            nic_used = [{'net-id': self.network['id']}]
            print 'Creating Instance: ' + vm_name
            perf_instance.create_server(vm_name, config_scale['image_name'],
                                        config_scale['flavor_type'],
                                        self.keypair_list[0].keypair_name,
                                        nic_used,
                                        self.secgroup_list[0].secgroup,
                                        config_scale['public_key_file'],
                                        None,
                                        None,
                                        None)
            # Store the subnet info and fixed ip address in instance
            perf_instance.subnet_ip = self.network['subnet_ip']
            print perf_instance.instance.networks.values()
            print '++++++++++++++++++++++++++++++'
            perf_instance.fixed_ip = perf_instance.instance.networks.values()[0][0]
            if self.shared_interface_ip:
                perf_instance.shared_interface_ip = self.shared_interface_ip
            # Create the floating ip for the instance store it and the ip address in instance object
            if config_scale['use_floatingip']:
                perf_instance.fip = create_floating_ip(self.neutron_client, external_network)
                perf_instance.fip_ip = perf_instance.fip['floatingip']['floating_ip_address']
                # Associate the floating ip with this instance
                perf_instance.instance.add_floating_ip(perf_instance.fip_ip)
                perf_instance.ssh_ip = perf_instance.fip_ip
            else:
                # Store the fixed ip as ssh ip since there is no floating ip
                perf_instance.ssh_ip = perf_instance.fixed_ip
            print "VM Information"
            print "SSH IP:%s" % (perf_instance.ssh_ip)
            print "Subnet Info: %s" % (perf_instance.subnet_ip)
            if self.shared_interface_ip:
                print "Shared router interface ip %s" % (self.shared_interface_ip)

    def delete_compute_resources(self):
        """
        Deletes the compute resources
        Security groups,keypairs and instances
        """
        # Delete the instances first
        for instance in self.instance_list:
            instance.delete_server()
            if instance.fip:
                delete_floating_ip(self.neutron_client, instance.fip['floatingip']['id'])

        # Delete all security groups
        for secgroup_instance in self.secgroup_list:
            secgroup_instance.delete_secgroup()

        # Delete all keypairs
        for keypair_instance in self.keypair_list:
            keypair_instance.remove_public_key()


    def create_network_and_subnet(self, network_name):
        """
        Create a network with 1 subnet inside it
        """
        subnet_name = "kloudbuster_subnet" + network_name
        body = {
            'network': {
                'name': network_name,
                'admin_state_up': True
            }
        }
        self.network = self.neutron_client.create_network(body)['network']

        # Now create the subnet inside this network support ipv6 in future
        body = {
            'subnet': {
                'name': subnet_name,
                'cidr': self.generate_cidr(),
                'network_id': self.network['id'],
                'enable_dhcp': True,
                'ip_version': 4
            }
        }
        subnet = self.neutron_client.create_subnet(body)['subnet']
        # add subnet id to the network dict since it has just been added
        self.network['subnets'] = [subnet['id']]
        self.network['subnet_ip'] = cidr

    def generate_cidr(self):
        """Generate next CIDR for network or subnet, without IP overlapping.
        """
        global cidr
        cidr = str(netaddr.IPNetwork(cidr).next())
        return cidr

    def delete_network(self):
        """
        Deletes the network and associated subnet
        retry the deletion since network may be in use
        """
        for _ in range(1, 5):
            try:
                self.neutron_client.delete_network(self.network['id'])
                break
            except NetworkInUseClient:
                time.sleep(1)

    def get_all_instances(self):
        return self.instance_list

class Router(object):
    """
    Router class to create a new routers
    Supports addition and deletion
    of network interfaces to router
    """

    def __init__(self, neutron_client, nova_client, user_name, shared_network=None):
        self.neutron_client = neutron_client
        self.nova_client = nova_client
        self.router = None
        self.user_name = user_name
        # Stores the list of networks
        self.network_list = []
        # Store the shared network
        self.shared_network = shared_network
        self.shared_port_id = None
        # Store the interface ip of shared network attached to router
        self.shared_interface_ip = None

    def create_network_resources(self, config_scale):
        """
        Creates the required number of networks per router
        Also triggers the creation of compute resources inside each
        network
        """
        # If a shared network exists create a port on this
        # network and attach to router interface
        if self.shared_network:
            self.attach_router_interface(self.shared_network, use_port=True)
        for network_count in range(config_scale['networks_per_router']):
            network_instance = BaseNetwork(self.neutron_client, self.nova_client, self.user_name,
                                           self.shared_interface_ip)
            self.network_list.append(network_instance)
            # Create the network and subnet
            network_name = self.user_name + "_N" + str(network_count)
            network_instance.create_network_and_subnet(network_name)
            # Attach the created network to router interface
            self.attach_router_interface(network_instance)
            # Create the compute resources in the network
            network_instance.create_compute_resources(network_name, config_scale)

    def get_first_network(self):
        if self.network_list:
            return self.network_list[0]
        return None

    def get_all_instances(self):
        all_instances = []
        for network in self.network_list:
            all_instances.extend(network.get_all_instances())
        return all_instances

    def delete_network_resources(self):
        """
        Delete all network and compute resources
        associated with a router
        """

        for network in self.network_list:
            # Now delete the compute resources and the network resources
            network.delete_compute_resources()
            self.remove_router_interface(network)
            network.delete_network()
        # Also delete the shared port and remove it from router interface
        if self.shared_network:
            self.remove_router_interface(self.shared_network, use_port=True)
            self.shared_network = None

    def create_router(self, router_name, ext_net):
        """
        Create the router and attach it to
        external network
        """
        # Attach an external network if available
        if ext_net:
            body = {
                "router": {
                    "name": router_name,
                    "admin_state_up": True,
                    "external_gateway_info": {
                        "network_id": ext_net['id']
                    }
                }
            }
        else:
            body = {
                "router": {
                    "name": router_name,
                    "admin_state_up": True
                }
            }
        self.router = self.neutron_client.create_router(body)
        return self.router['router']

    def delete_router(self):
        """
        Delete the router
        Also delete the networks attached to this router
        """
        # Delete the network resources first and than delete the router itself
        self.delete_network_resources()
        self.neutron_client.delete_router(self.router['router']['id'])

    def _port_create_neutron(self, network_instance):
        """
        Creates a port on a specific network
        """
        body = {
            "port": {
                "admin_state_up": True,
                "network_id": network_instance.network['id']
            }
        }
        post_output = self.neutron_client.create_port(body)
        self.shared_interface_ip = post_output['port']['fixed_ips'][0]['ip_address']
        return post_output['port']['id']

    def _port_delete_neutron(self, port):
        self.neutron_client.delete_port(port)

    def attach_router_interface(self, network_instance, use_port=False):
        """
        Attach a network interface to the router
        """
        # If shared port is specified use that
        if use_port:
            self.shared_port_id = self._port_create_neutron(network_instance)
            body = {
                'port_id': self.shared_port_id
            }
        else:
            body = {
                'subnet_id': network_instance.network['subnets'][0]
            }
        self.neutron_client.add_interface_router(self.router['router']['id'], body)



    def remove_router_interface(self, network_instance, use_port=False):
        """
        Remove the network interface from router
        """
        if use_port:
            body = {
                'port_id': self.shared_port_id
            }
        else:
            body = {
                'subnet_id': network_instance.network['subnets'][0]
            }
        self.neutron_client.remove_interface_router(self.router['router']['id'], body)
