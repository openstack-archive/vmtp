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

import time

# Module containing a helper class for operating on OpenStack networks
from neutronclient.common.exceptions import NetworkInUseClient
from neutronclient.common.exceptions import NeutronException

class Network(object):

    #
    # This constructor will try to find an external network (will use the
    # first network that is tagged as external - irrespective of its name)
    # and a router attached to it (irrespective of the router name).
    # ext_router_name is the name of the external router to create if not None
    # and if no external router is found
    #
    def __init__(self, neutron_client, config):
        self.neutron_client = neutron_client
        self.networks = neutron_client.list_networks()['networks']
        self.ext_net = None
        self.ext_router = None
        self.ext_router_created = False
        self.config = config
        # mgmt/data network:
        # - first for same network
        # - second for network to network communication
        self.vm_int_net = []
        self.ext_router_name = None
        # Store state if the network is ipv4/ipv6 dual stack
        self.ipv6_enabled = False

        self.agent_type = self._get_agent_type()

        # If reusing existing management network just find this network
        if self.config.reuse_network_name:
            # An existing management network must be reused
            int_net = self.lookup_network(self.config.reuse_network_name)
            self.vm_int_net.append(int_net)
            return

        ##############################################
        # If a user provided ext_net_name is not available,
        # then find the first network that is external
        ##############################################
        for network in self.networks:
            if network['router:external']:
                try:
                    if network['name'] == config.ext_net_name:
                        self.ext_net = network
                        break
                    if not self.ext_net:
                        self.ext_net = network
                except KeyError:
                    ###############################################
                    # A key error indicates, no user defined
                    # external network defined, so use the first one
                    ###############################################
                    self.ext_net = network
                    break

        if not self.ext_net:
            print "No external network found."
            return

        print "Using external network: " + self.ext_net['name']

        # Find or create the router to the external network
        ext_net_id = self.ext_net['id']
        routers = neutron_client.list_routers()['routers']
        for router in routers:
            external_gw_info = router['external_gateway_info']
            if external_gw_info:
                if external_gw_info['network_id'] == ext_net_id:
                    self.ext_router = router
                    print 'Found external router: %s' % \
                          (self.ext_router['name'])
                    break

        # create a new external router if none found and a name was given
        self.ext_router_name = config.router_name
        if (not self.ext_router) and self.ext_router_name:
            self.ext_router = self.create_router(self.ext_router_name,
                                                 self.ext_net['id'])
            print '[%s] Created ext router' % (self.ext_router_name)
            self.ext_router_created = True

        if config.ipv6_mode:
            self.ipv6_enabled = True

        # Create the networks and subnets depending on v4 or v6
        if config.ipv6_mode:
            for (net, subnet, cidr, subnet_ipv6, cidr_ipv6) in zip(config.internal_network_name,
                                                                   config.internal_subnet_name,
                                                                   config.internal_cidr,
                                                                   config.internal_subnet_name_ipv6,
                                                                   config.internal_cidr_v6):
                int_net = self.create_net(net, subnet, cidr,
                                          config.dns_nameservers,
                                          subnet_ipv6, cidr_ipv6, config.ipv6_mode)
                self.vm_int_net.append(int_net)
        else:
            for (net, subnet, cidr) in zip(config.internal_network_name,
                                           config.internal_subnet_name,
                                           config.internal_cidr):
                int_net = self.create_net(net, subnet, cidr,
                                          config.dns_nameservers)
                self.vm_int_net.append(int_net)

        # Add both internal networks to router interface to enable network to network connectivity
        self.__add_router_interface()

    # Create a network with associated subnet
    # Check first if a network with the same name exists, if it exists
    # return that network.
    # dns_nameservers: a list of name servers e.g. ['8.8.8.8']
    def create_net(self, network_name, subnet_name, cidr, dns_nameservers,
                   subnet_name_ipv6=None, cidr_ipv6=None, ipv6_mode=None):

        for network in self.networks:
            if network['name'] == network_name:
                print ('Found existing internal network: %s'
                       % (network_name))
                return network

        body = {
            'network': {
                'name': network_name,
                'admin_state_up': True
            }
        }
        network = self.neutron_client.create_network(body)['network']
        body = {
            'subnet': {
                'name': subnet_name,
                'cidr': cidr,
                'network_id': network['id'],
                'enable_dhcp': True,
                'ip_version': 4,
                'dns_nameservers': dns_nameservers
            }
        }
        subnet = self.neutron_client.create_subnet(body)['subnet']
        # add subnet id to the network dict since it has just been added
        network['subnets'] = [subnet['id']]
        # If ipv6 is enabled than create and add ipv6 network
        if ipv6_mode:
            body = {
                'subnet': {
                    'name': subnet_name_ipv6,
                    'cidr': cidr_ipv6,
                    'network_id': network['id'],
                    'enable_dhcp': True,
                    'ip_version': 6,
                    'ipv6_ra_mode': ipv6_mode,
                    'ipv6_address_mode': ipv6_mode
                }
            }
            subnet = self.neutron_client.create_subnet(body)['subnet']
            # add the subnet id to the network dict
            network['subnets'].append(subnet['id'])
        print 'Created internal network: %s' % (network_name)
        return network

    # Delete a network and associated subnet
    def delete_net(self, network):
        if network:
            name = network['name']
            # it may take some time for ports to be cleared so we need to retry
            for _ in range(1, 5):
                try:
                    self.neutron_client.delete_network(network['id'])
                    print 'Network %s deleted' % (name)
                    break
                except NetworkInUseClient:
                    time.sleep(1)

    # Add a network/subnet to a logical router
    # Check that it is not already attached to the network/subnet
    def __add_router_interface(self):

        # and pick the first in the list - the list should be non empty and
        # contain only 1 subnet since it is supposed to be a private network

        # But first check that the router does not already have this subnet
        # so retrieve the list of all ports, then check if there is one port
        # - matches the subnet
        # - and is attached to the router
        # Assumed that both management networks are created together so checking for one of them
        ports = self.neutron_client.list_ports()['ports']
        for port in ports:
            port_ip = port['fixed_ips'][0]
            if (port['device_id'] == self.ext_router['id']) and \
               (port_ip['subnet_id'] == self.vm_int_net[0]['subnets'][0]):
                print 'Ext router already associated to the internal network'
                return

        for int_net in self.vm_int_net:
            body = {
                'subnet_id': int_net['subnets'][0]
            }
            self.neutron_client.add_interface_router(self.ext_router['id'], body)
            if self.config.debug:
                print 'Ext router associated to ' + int_net['name']
            # If ipv6 is enabled than add second subnet
            if self.ipv6_enabled:
                body = {
                    'subnet_id': int_net['subnets'][1]
                }
                self.neutron_client.add_interface_router(self.ext_router['id'], body)

    # Detach the ext router from the mgmt network
    def __remove_router_interface(self):
        for int_net in self.vm_int_net:
            if int_net:
                # If ipv6 is enabled remove that subnet too
                if self.ipv6_enabled:
                    body = {
                        'subnet_id': int_net['subnets'][1]
                    }
                    self.neutron_client.remove_interface_router(self.ext_router['id'],
                                                                body)
                body = {
                    'subnet_id': int_net['subnets'][0]
                }
                try:
                    self.neutron_client.remove_interface_router(self.ext_router['id'],
                                                                body)
                except NeutronException:
                    # May fail with neutronclient.common.exceptions.Conflict
                    # if there are floating IP in use - just ignore
                    print('Router interface may have floating IP in use: not deleted')

    # Lookup network given network name
    def lookup_network(self, network_name):
        networks = self.neutron_client.list_networks(name=network_name)
        return networks['networks'][0]

    # Create a router and up-date external gateway on router
    # to external network
    def create_router(self, router_name, net_id):
        body = {
            "router": {
                "name": router_name,
                "admin_state_up": True,
                "external_gateway_info": {
                    "network_id": net_id
                }
            }
        }
        router = self.neutron_client.create_router(body)
        return router['router']

    # Show a router based on name
    def show_router(self, router_name):
        router = self.neutron_client.show_router(router_name)
        return router

    # Update a router given router and network id
    def update_router(self, router_id, net_id):
        print net_id
        body = {
            "router": {
                "name": "pns-router",
                "external_gateway_info": {
                    "network_id": net_id
                }
            }
        }
        router = self.neutron_client.update_router(router_id, body)
        return router['router']

    # Create a floating ip on the external network and return it
    def create_floating_ip(self):
        body = {
            "floatingip": {
                "floating_network_id": self.ext_net['id']
            }
        }
        fip = self.neutron_client.create_floatingip(body)
        return fip

    # Delete floating ip given a floating ip ad
    def delete_floating_ip(self, floatingip):
        self.neutron_client.delete_floatingip(floatingip)

    # Dispose all network resources, call after all VM have been deleted
    def dispose(self):
        # Delete the internal networks only of we did not reuse an existing
        # network
        if not self.config.reuse_network_name:
            self.__remove_router_interface()
            for int_net in self.vm_int_net:
                self.delete_net(int_net)
            # delete the router only if its name matches the pns router name
            if self.ext_router_created:
                try:
                    if self.ext_router['name'] == self.ext_router_name:
                        self.neutron_client.delete_router(self.ext_router['id'])
                        print 'External router %s deleted' % \
                              (self.ext_router['name'])
                except TypeError:
                    print "No external router set"

    def _get_agent_type(self):
        '''
        Retrieve the list of agents
        return 'Linux bridge agent' or 'Open vSwitch agent' or 'Unknown agent'
        '''
        agents = self.neutron_client.list_agents(fields='agent_type')['agents']
        for agent in agents:
            agent_type = agent['agent_type']
            if 'Linux bridge' in agent_type or 'Open vSwitch' in agent_type:
                return agent_type
        return 'Unknown agent'
