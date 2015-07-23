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
import log as logging
import users

LOG = logging.getLogger(__name__)


class Tenant(object):
    """
    Holds the tenant resources
    1. Provides ability to create users in a tenant
    2. Uses the User class to perform all user resource creation and deletion
    """

    def __init__(self, tenant_name, kloud, tenant_quota, reusing_users=None):
        """
        Holds the tenant name
        tenant id and keystone client
        Also stores the auth_url for constructing credentials
        Stores the shared network in case of testing and
        tested cloud being on same cloud
        """
        self.kloud = kloud
        self.tenant_name = tenant_name
        if not self.kloud.reusing_tenants:
            self.tenant_object = self._get_tenant()
            self.tenant_id = self.tenant_object.id
        else:
            LOG.info("Using tenant: " + self.tenant_name)
            # Only admin can retrive the object via Keystone API
            self.tenant_object = None
            try:
                # Try to see if we have the admin access to retrive the tenant id using
                # tenant name directly from keystone
                self.tenant_id = self.kloud.keystone.tenants.find(name=self.tenant_name).id
            except Exception:
                self.tenant_id = self.kloud.keystone.tenant_id

        self.tenant_quota = tenant_quota
        self.reusing_users = reusing_users
        # Contains a list of user instance objects
        self.user_list = []

    def _get_tenant(self):

        '''
        Create or reuse a tenant object of a given name
        '''
        try:
            LOG.info("Creating tenant: " + self.tenant_name)
            tenant_object = \
                self.kloud.keystone.tenants.create(tenant_name=self.tenant_name,
                                                   description="KloudBuster tenant",
                                                   enabled=True)
            return tenant_object
        except keystone_exception.Conflict as exc:
            # ost likely the entry already exists:
            # Conflict: Conflict occurred attempting to store project - Duplicate Entry (HTTP 409)
            if exc.http_status != 409:
                raise exc
            LOG.info("Tenant %s already present, reusing it" % self.tenant_name)
            return self.kloud.keystone.tenants.find(name=self.tenant_name)

        # Should never come here
        raise Exception()

    def create_resources(self):
        """
        Creates all the entities associated with
        a user offloads tasks to user class
        """
        if self.reusing_users:
            for user_info in self.reusing_users:
                user_name = user_info['username']
                password = user_info['password']
                user_instance = users.User(user_name, password, self, '_member_')
                self.user_list.append(user_instance)
        else:
            # Loop over the required number of users and create resources
            for user_count in xrange(self.kloud.scale_cfg['users_per_tenant']):
                user_name = self.tenant_name + "-U" + str(user_count)
                user_instance = users.User(user_name, user_name, self,
                                           self.kloud.scale_cfg['keystone_admin_role'])
                # Global list with all user instances
                self.user_list.append(user_instance)

        for user_instance in self.user_list:
            # Now create the user resources like routers which inturn trigger network and
            # vm creation
            user_instance.create_resources()

    def get_first_network(self):
        if self.user_list:
            return self.user_list[0].get_first_network()
        return None

    def get_all_instances(self):
        all_instances = []
        for user in self.user_list:
            all_instances.extend(user.get_all_instances())
        return all_instances

    def get_prefix(self):
        return self.kloud.get_prefix() + '_' + self.prefix

    def delete_resources(self):
        """
        Delete all user resources and than
        deletes the tenant
        """
        # Delete all the users in the tenant along with network and compute elements
        for user in self.user_list:
            user.delete_resources()

        if not self.reusing_users:
            # Delete the tenant (self)
            self.kloud.keystone.tenants.delete(self.tenant_id)
