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

import base_compute
import base_network
from cinderclient.v2 import client as cinderclient
import keystoneclient.openstack.common.apiclient.exceptions as keystone_exception
import log as logging
from neutronclient.v2_0 import client as neutronclient
from novaclient.client import Client

LOG = logging.getLogger(__name__)

class KBFlavorCheckException(Exception):
    pass

class KBQuotaCheckException(Exception):
    pass

class User(object):
    """
    User class that stores router list
    Creates and deletes N routers based on num of routers
    """

    def __init__(self, user_name, password, tenant, user_role):
        """
        Store all resources
        1. Keystone client object
        2. Tenant and User information
        3. nova and neutron clients
        4. router list
        """
        self.user_name = user_name
        self.password = password
        self.tenant = tenant
        self.router_list = []
        # Store the nova, neutron and cinder client
        self.nova_client = None
        self.neutron_client = None
        self.cinder_client = None
        # Each user is associated to 1 key pair at most
        self.key_pair = None
        self.key_name = None

        # Create the user within the given tenant associate
        # admin role with user. We need admin role for user
        # since we perform VM placement in future
        #
        # If running on top of existing tenants/users, skip
        # the step for admin role association.
        if not self.tenant.reusing_users:
            self.user = self._get_user()
            current_role = self.tenant.kloud.keystone.roles.find(name=user_role)
            self.tenant.kloud.keystone.roles.add_user_role(self.user,
                                                           current_role,
                                                           tenant.tenant_id)
        else:
            # Only admin can retrive the object via Keystone API
            self.user = None
            LOG.info("Using user: " + self.user_name)


    def _create_user(self):
        LOG.info("Creating user: " + self.user_name)
        return self.tenant.kloud.keystone.users.create(name=self.user_name,
                                                       password=self.password,
                                                       email="kloudbuster@localhost",
                                                       tenant_id=self.tenant.tenant_id)

    def _get_user(self):
        '''
        Create a new user or reuse if it already exists (on a different tenant)
        delete the user and create a new one
        '''
        try:
            user = self._create_user()
            return user
        except keystone_exception.Conflict as exc:
            # Most likely the entry already exists (leftover from past failed runs):
            # Conflict: Conflict occurred attempting to store user - Duplicate Entry (HTTP 409)
            if exc.http_status != 409:
                raise exc
            # Try to repair keystone by removing that user
            LOG.warn("User creation failed due to stale user with same name: " +
                     self.user_name)
            user = self.tenant.kloud.keystone.users.find(name=self.user_name)
            LOG.info("Deleting stale user with name: " + self.user_name)
            self.tenant.kloud.keystone.users.delete(user)
            return self._create_user()

        # Should never come here
        raise Exception()

    def delete_resources(self):
        LOG.info("Deleting all user resources for user %s" % self.user_name)

        # Delete key pair
        if self.key_pair:
            self.key_pair.remove_public_key()

        # Delete all user routers
        for router in self.router_list:
            router.delete_router()

        if not self.tenant.reusing_users:
            # Finally delete the user
            self.tenant.kloud.keystone.users.delete(self.user.id)

    def update_tenant_quota(self, tenant_quota):
        nova_quota = base_compute.NovaQuota(self.nova_client, self.tenant.tenant_id)
        nova_quota.update_quota(**tenant_quota['nova'])

        cinder_quota = base_compute.CinderQuota(self.cinder_client, self.tenant.tenant_id)
        cinder_quota.update_quota(**tenant_quota['cinder'])

        neutron_quota = base_network.NeutronQuota(self.neutron_client, self.tenant.tenant_id)
        neutron_quota.update_quota(tenant_quota['neutron'])

    def check_resources_quota(self):
        # Flavor check
        flavor_manager = base_compute.Flavor(self.nova_client)
        flavor_to_use = None
        for flavor in flavor_manager.list():
            flavor = flavor.__dict__
            if flavor['vcpus'] < 1 or flavor['ram'] < 1024 or flavor['disk'] < 10:
                continue
            flavor_to_use = flavor
            break
        if flavor_to_use:
            LOG.info('Automatically selects flavor %s to instantiate VMs.' %
                     (flavor_to_use['name']))
            self.tenant.kloud.flavor_to_use = flavor_to_use['name']
        else:
            LOG.error('Cannot find a flavor which meets the minimum '
                      'requirements to instantiate VMs.')
            raise KBFlavorCheckException()

        # Nova/Cinder/Neutron quota check
        tenant_id = self.tenant.tenant_id
        meet_quota = True
        for quota_type in ['nova', 'cinder', 'neutron']:
            if quota_type == 'nova':
                quota_manager = base_compute.NovaQuota(self.nova_client, tenant_id)
            elif quota_type == 'cinder':
                quota_manager = base_compute.CinderQuota(self.cinder_client, tenant_id)
            else:
                quota_manager = base_network.NeutronQuota(self.neutron_client, tenant_id)

            meet_quota = True
            quota = quota_manager.get()
            for key, value in self.tenant.tenant_quota[quota_type].iteritems():
                if quota[key] < value:
                    meet_quota = False
                    break

        if not meet_quota:
            LOG.error('%s quota is too small. Minimum requirement: %s.' %
                      (quota_type, self.tenant.tenant_quota[quota_type]))
            raise KBQuotaCheckException()

    def create_resources(self):
        """
        Creates all the User elements associated with a User
        1. Creates the routers
        2. Creates the neutron and nova client objects
        """
        # Create a new neutron client for this User with correct credentials
        creden = {}
        creden['username'] = self.user_name
        creden['password'] = self.password
        creden['auth_url'] = self.tenant.kloud.auth_url
        creden['tenant_name'] = self.tenant.tenant_name

        # Create the neutron client to be used for all operations
        self.neutron_client = neutronclient.Client(**creden)

        # Create a new nova and cinder client for this User with correct credentials
        creden_nova = {}
        creden_nova['username'] = self.user_name
        creden_nova['api_key'] = self.password
        creden_nova['auth_url'] = self.tenant.kloud.auth_url
        creden_nova['project_id'] = self.tenant.tenant_name
        creden_nova['version'] = 2

        self.nova_client = Client(**creden_nova)
        self.cinder_client = cinderclient.Client(**creden_nova)

        if self.tenant.kloud.reusing_tenants:
            self.check_resources_quota()
        else:
            self.update_tenant_quota(self.tenant.tenant_quota)

        config_scale = self.tenant.kloud.scale_cfg

        # Create the user's keypair if configured
        if config_scale.public_key_file:
            self.key_pair = base_compute.KeyPair(self.nova_client)
            self.key_name = self.user_name + '-K'
            self.key_pair.add_public_key(self.key_name, config_scale.public_key_file)

        # Find the external network that routers need to attach to
        external_network = base_network.find_external_network(self.neutron_client)

        # Create the required number of routers and append them to router list
        LOG.info("Creating routers and networks for user %s" % self.user_name)
        for router_count in range(config_scale['routers_per_user']):
            router_instance = base_network.Router(self)
            self.router_list.append(router_instance)
            router_name = self.user_name + "-R" + str(router_count)
            # Create the router and also attach it to external network
            router_instance.create_router(router_name, external_network)
            # Now create the network resources inside the router
            router_instance.create_network_resources(config_scale)

    def get_first_network(self):
        if self.router_list:
            return self.router_list[0].get_first_network()
        return None

    def get_all_instances(self):
        all_instances = []
        for router in self.router_list:
            all_instances.extend(router.get_all_instances())
        return all_instances
