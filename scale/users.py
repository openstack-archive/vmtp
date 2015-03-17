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

import base_network

from neutronclient.v2_0 import client as neutronclient
from novaclient.client import Client

class User(object):
    """
    User class that stores router list
    Creates and deletes N routers based on num of routers
    """

    def __init__(self, user_name, user_role, tenant_id, tenant_name, keystone_client,
                 auth_url):
        """
        Store all resources
        1. Keystone client object
        2. Tenant and User information
        3. nova and neutron clients
        4. router list
        """
        self.user_name = user_name
        self.keystone_client = keystone_client
        self.tenant_id = tenant_id
        self.tenant_name = tenant_name
        self.user_id = None
        self.router_list = []
        self.auth_url = auth_url
        # Store the neutron and nova client
        self.neutron = None
        self.nova = None


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
        print "Deleting all user resources for user %s" % (self.user_name)

        # Delete all user routers
        for router in self.router_list:
            router.delete_router()

        # Finally delete the user
        self.keystone_client.users.delete(self.user_id)

    def create_user_resources(self, config_scale):
        """
        Creates all the User elements associated with a User
        1. Creates the routers
        2. Creates the neutron and nova client objects
        """

        # Create a new neutron client for this User with correct credentials
        creden = {}
        creden['username'] = self.user_name
        creden['password'] = self.user_name
        creden['auth_url'] = self.auth_url
        creden['tenant_name'] = self.tenant_name

        # Create the neutron client to be used for all operations
        self.neutron = neutronclient.Client(**creden)

        # Create a new nova client for this User with correct credentials
        creden_nova = {}
        creden_nova['username'] = self.user_name
        creden_nova['api_key'] = self.user_name
        creden_nova['auth_url'] = self.auth_url
        creden_nova['project_id'] = self.tenant_name
        creden_nova['version'] = 2
        self.nova = Client(**creden_nova)

        # Find the external network that routers need to attach to
        external_network = base_network.find_external_network(self.neutron)
        # Create the required number of routers and append them to router list
        print "Creating routers for user %s" % (self.user_name)
        for router_count in range(config_scale.routers_per_user):
            router_instance = base_network.Router(self.neutron, self.nova, self.user_name)
            self.router_list.append(router_instance)
            router_name = "kloudbuster_router_" + "_" + str(router_count)
            # Create the router and also attach it to external network
            router_instance.create_router(router_name, external_network)
            # Now create the network resources inside the router
            router_instance.create_network_resources(config_scale)
