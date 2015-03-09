import base_network
import base_compute
from neutronclient.v2_0 import client as neutronclient
from novaclient.client import Client
class User(object):
    """
    User class the performs all the resource creations
    1. Leverages BaseNetwork class for network resources
    2. Leverages Router class for router resources
    3. Leverages Instance class for compute resources
    """
    def __init__(self, user_name, user_role, tenant_id, tenant_name, keystone_client,
                 auth_url):
        """
        Store all resources
        1. Keystone client object
        2. List of network instances
        3. List of router instances
        """
        self.user_name = user_name
        self.keystone_client = keystone_client
        self.tenant_id = tenant_id
        self.tenant_name = tenant_name
        self.user_id = None
        self.router_list = []
        self.network_list = []
        self.instance_list = []
        self.secgroup_list = []
        self.keypair_list = []
        self.auth_url = auth_url


        # Create the user within the given tenant associate
        # admin role with user. We need admin role for user
        # since we perform VM placement in future
        admin_user = self.keystone_client.users.create(name=user_name,
                                                       password=user_name,
                                                       email="test.com",
                                                       tenant_id=tenant_id)
        current_role = None
        for role in self.keystone_client.roles.list():
            if role.name == user_role:
                current_role = role
                break
        self.keystone_client.roles.add_user_role(admin_user, current_role, tenant_id)
        self.user_id = admin_user.id

    def delete_user(self):
        print "Deleting all user resources for user %s" %(self.user_name)
        #Delete all instances
        for instance in self.instance_list:
            instance.delete_server()
            # Delete the associated floating ip we need to create a neutron client
            # to do this needs to be a better way
            # Create a new neutron client for this User with correct credentials
            creden = {}
            creden['username'] = self.user_name
            creden['password'] = self.user_name
            creden['auth_url'] = self.auth_url
            creden['tenant_name'] = self.tenant_name

            # Create the neutron client to be used for all operations
            neutron = neutronclient.Client(**creden)
            base_network.delete_floating_ip(neutron, instance.fip['floatingip']['id'])

        # Delete all security groups
        for secgroup_instance in self.secgroup_list:
            secgroup_instance.delete_secgroup()

        # Delete all keypairs

        for keypair_instance in self.keypair_list:
            keypair_instance.remove_public_key()

        # Delete all routers
        for router in self.router_list:
            for network in self.network_list:
                router.remove_router_interface(network)

        # Delete all user networks
        for network in self.network_list:
            network.delete_network()

        #Delete all user routers
        for router in self.router_list:
            router.delete_router()

        # Finally delete the user
        self.keystone_client.users.delete(self.user_id)

    def create_user_resources(self, config_scale):
        """
        Creates all the User elements associated with a User
        1. Creates the routers
        2. Creates the networks
        3. Attaches networks to the routers
        4. Creates the instances
        """
        # Create a new neutron client for this User with correct credentials
        creden = {}
        creden['username'] = self.user_name
        creden['password'] = self.user_name
        creden['auth_url'] = self.auth_url
        creden['tenant_name'] = self.tenant_name

        # Create the neutron client to be used for all operations
        neutron = neutronclient.Client(**creden)

        # Create the required number of networks and append them to network list
        print "Creating the networks for user %s" %(self.user_name)
        for network_count in range(config_scale.networks_per_user):
            network_instance = base_network.BaseNetwork(neutron, self.user_name)
            self.network_list.append(network_instance)
            # Create the network and subnet
            network_name = "cloud_scale_network_" + "_" + str(network_count)
            network_instance.create_network_and_subnet(network_name)

        # Find the external network that routers need to attach to
        external_network = base_network.find_external_network(neutron)
        # Create the required number of routers and append them to router list
        print "Creating routers for user %s" %(self.user_name)
        for router_count in range(config_scale.routers_per_user):
            router_instance = base_network.Router(neutron)
            self.router_list.append(router_instance)
            router_name = "cloud_scale_router_"  + "_" + str(router_count)
            router_instance.create_router(router_name, external_network)

        # Attach all networks to all routers in the given user
        # For now this code assumes only 1 router per user
        # Need to figure out what to do when user specifies multiple routers
        print "Attaching router interfaces to networks for user %s" %(self.user_name)
        for router in self.router_list:
            for network in self.network_list:
                router.attach_router_interface(network)

        print "Creating compute resources for user %s" %(self.user_name)
        # Create a new nova client for this User with correct credentials
        creden_nova = {}
        creden_nova['username'] = self.user_name
        creden_nova['api_key'] = self.user_name
        creden_nova['auth_url'] = self.auth_url
        creden_nova['project_id'] = self.tenant_name
        creden_nova['version'] = 2
        nova = Client(**creden_nova)

        # First create the required number of security groups
        print "Creating security groups for user %s" %(self.user_name)
        for secgroup_count in range(config_scale.secgroups_per_user):
            secgroup_instance = base_compute.SecGroup(nova)
            self.secgroup_list.append(secgroup_instance)
            secgroup_name = "cloud_scale_secgroup" + "_" + str(secgroup_count)
            secgroup_instance.create_secgroup_with_rules(secgroup_name)

        # Now create the required number of keypairs per user
        print "Creating keypair for user %s" %(self.user_name)
        for keypair_count in range(config_scale.keypairs_per_user):
            keypair_instance = base_compute.KeyPair(nova)
            self.keypair_list.append(keypair_instance)
            keypair_name = "cloud_scale_keypair" + "_" + str(keypair_count)
            keypair_instance.add_public_key(keypair_name, config_scale.public_key_file)


        # Create the required number of VMs
        # For now code does not have distribution
        # Create the VM on first network, first keypair, first secgroup

        print "Creating Virtual machines for user %s" %(self.user_name)
        for instance_count in range(config_scale.vms_per_user):
            nova_instance = base_compute.BaseCompute(nova, self.user_name)
            self.instance_list.append(nova_instance)
            vm_name = "cloud_scale_vm" + "_" + str(instance_count)
            nic_used = [{'net-id': self.network_list[0].network['id']}]
            nova_instance.create_server(vm_name, config_scale.image_name,
                                        config_scale.flavor_type,
                                        self.keypair_list[0].keypair_name,
                                        nic_used,
                                        self.secgroup_list[0].secgroup,
                                        config_scale.public_key_file,
                                        None,
                                        None,
                                        None)
            # Create the floating ip for the instance store it and the ip address in instance object
            nova_instance.fip = base_network.create_floating_ip(neutron, external_network)
            nova_instance.fip_ip = nova_instance.fip['floatingip']['floating_ip_address']
            # Associate the floating ip with this instance
            nova_instance.instance.add_floating_ip(nova_instance.fip_ip)


