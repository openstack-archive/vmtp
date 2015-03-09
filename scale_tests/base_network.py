import time

# Module containing a helper class for operating on OpenStack networks
from neutronclient.common.exceptions import NetworkInUseClient
import netaddr

def create_floating_ip(neutron_client, ext_net):
    """
    Function that creates a floating ip and returns it
    Accepts the neutron client and ext_net
    Module level function since this is not associated with a
    specific network instance
    """
    body = {
        "floatingip": {
            "floating_network_id" : ext_net['id']
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
    """

    # Global CIDR shared by all objects of this class
    # Enables each network to get a unique CIDR
    START_CIDR = "1.0.0.0/16"
    cidr = None

    def __init__(self, neutron_client, user_name):
        """
        Store the neutron client
        User name for this network
        and network object
        """
        self.neutron_client = neutron_client
        self.user_name = user_name
        self.network = None
        self.cidr = self.START_CIDR

    def create_network_and_subnet(self, network_name):
        """
        Create a network with 1 subnet inside it
        """
        subnet_name = "cloud_scale_subnet" + network_name
        body = {
            'network': {
                'name': network_name,
                'admin_state_up': True
            }
        }
        self.network = self.neutron_client.create_network(body)['network']

        #Now create the subnet inside this network support ipv6 in future
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

    def generate_cidr(self):
        """Generate next CIDR for network or subnet, without IP overlapping.
        """
        self.cidr = str(netaddr.IPNetwork(self.cidr).next())
        return self.cidr

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


class Router(object):
    """
    Router class to create a new routers
    Supports addition of network interfaces to router
    Finds the external network to attach to
    """

    def __init__(self, neutron_client):
        self.neutron_client = neutron_client
        self.router = None


    def create_router(self, router_name, ext_net):
        """
        Create the router and attach it to
        external network
        """
        body = {
            "router": {
                "name": router_name,
                "admin_state_up": True,
                "external_gateway_info": {
                    "network_id": ext_net['id']
                }
            }
        }
        self.router = self.neutron_client.create_router(body)
        return self.router['router']

    def delete_router(self):
        """
        Delete the router
        """
        self.neutron_client.delete_router(self.router['router']['id'])


    def attach_router_interface(self, network_instance):
        """
        Attach a network interface to the router
        """
        body = {
            'subnet_id': network_instance.network['subnets'][0]
        }
        self.neutron_client.add_interface_router(self.router['router']['id'], body)


    def remove_router_interface(self, network_instance):
        """
        Remove the network interface from router
        """
        body = {
            'subnet_id': network_instance.network['subnets'][0]
        }
        self.neutron_client.remove_interface_router(self.router['router']['id'], body)

