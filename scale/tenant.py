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

import keystoneclient.openstack.common.apiclient.exceptions as keystone_exception
import users

class Tenant(object):
    """
    Holds the tenant resources
    1. Provides ability to create users in a tenant
    2. Uses the User class to perform all user resource creation and deletion
    """

    def __init__(self, tenant_name, keystone_client, auth_url, shared_network=None):
        """
        Holds the tenant name
        tenant id and keystone client
        Also stores the auth_url for constructing credentials
        Stores the shared network in case of testing and
        tested cloud being on same cloud
        """
        self.tenant_name = tenant_name
        self.keystone_client = keystone_client
        self.tenant_object = self._get_tenant()
        self.tenant_id = self.tenant_object.id
        # Contains a list of user instance objects
        self.tenant_user_list = []
        self.auth_url = auth_url
        self.shared_network = shared_network

    def _get_tenant(self):
        '''
        Create or reuse a tenant object of a given name
        '''
        try:
            print 'Creating tenant: ' + self.tenant_name
            self.tenant_object = \
                self.keystone_client.tenants.create(tenant_name=self.tenant_name,
                                                    description="Test tenant",
                                                    enabled=True)
        except keystone_exception.Conflict as exc:
            # ost likely the entry already exists:
            # Conflict: Conflict occurred attempting to store project - Duplicate Entry (HTTP 409)
            if exc.http_status != 409:
                raise exc
        print 'Tenant %s already present, reusing it' % (self.tenant_name)
        # It is a hassle to find a tenant by name as the only way seems to retrieve
        # the list of all tenants which can be very large
        tenant_list = self.keystone_client.tenants.list()
        for tenant in tenant_list:
            if tenant.name == self.tenant_name:
                return tenant
        # Should never come here
        raise Exception("Tenant not found")

    def create_user_elements(self, config_scale):
        """
        Creates all the entities associated with
        a user offloads tasks to user class
        """

        # Loop over the required number of users and create resources
        for user_count in xrange(config_scale['users_per_tenant']):
            user_name = "kloudbuster_user_" + self.tenant_name + "_" + str(user_count)
            print "Creating user %s" % (user_name)
            user_instance = users.User(user_name, config_scale['keystone_admin_role'],
                                       self.tenant_id, self.tenant_name,
                                       self.keystone_client,
                                       self.auth_url,
                                       self.shared_network)
            # Global list with all user instances
            self.tenant_user_list.append(user_instance)

            # Now create the user resources like routers which inturn trigger network and
            # vm creation
            user_instance.create_user_resources(config_scale)


    def delete_tenant_with_users(self):
        """
        Delete all user resources and than
        deletes the tenant
        """
        # Delete all the users in the tenant along with network and compute elements
        for user in self.tenant_user_list:
            user.delete_user()

        # Delete the tenant
        self.keystone_client.tenants.delete(self.tenant_id)
