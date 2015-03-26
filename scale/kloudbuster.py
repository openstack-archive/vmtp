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

import argparse

import credentials

import configure
from keystoneclient.v2_0 import client as keystoneclient
import tenant

class KloudBuster(object):
    """
    Creates resources on the cloud for loading up the cloud
    1. Tenants
    2. Users per tenant
    3. Routers per user
    4. Networks per router
    5. Instances per network
    """
    def __init__(self):
        # List of tenant objects to keep track of all tenants
        self.tenant_list = []
        self.tenant = None
        self.tenant_list_testing = []
        self.tenant_testing = None
        # Shared network between tested and testing cloud
        self.shared_network = None

    def runner(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """
        # Create the keystone client for tenant and user creation operations
        # for the tested cloud
        creds = cred.get_credentials()
        keystone = keystoneclient.Client(**creds)

        # Create the keystone client for testing cloud
        creds_testing = cred_testing.get_credentials()
        keystone_testing = keystoneclient.Client(**creds)

        # Store the auth url. Pass this around since
        # this does not change for all tenants and users
        auth_url = creds['auth_url']
        auth_url_testing = creds_testing['auth_url']

        print "Provisioning the Testing Cloud"
        # Create the resources for the testing cloud
        for tenant_count_testing in xrange(config_scale.client['number_tenants']):
            tenant_name_testing = "kloudbuster_tenant_testing_" + str(tenant_count_testing)
            self.tenant_testing = tenant.Tenant(tenant_name_testing,
                                                keystone_testing, auth_url_testing)
            self.tenant_list_testing.append(self.tenant_testing)
            # Create the user resources for that tenant
            self.tenant_testing.create_user_elements(config_scale.client)

        # Assume for now only 1 tenant and find the shared network to use
        self.shared_network = self.tenant_list_testing[0].tenant_user_list[0].\
            router_list[0].network_list[0]

        print "Now provisioning the Tested cloud"
        # The main tenant creation loop which invokes user creations
        # Create tenant resources and trigger User resource creations
        # For the tested cloud
        for tenant_count in xrange(config_scale.server['number_tenants']):
            # For now have a serial naming convention for tenants
            tenant_name = "kloudbuster_tenant_" + str(tenant_count)
            # Create the tenant and append it to global list
            print "Creating tenant %s" % (tenant_name)
            self.tenant = tenant.Tenant(tenant_name, keystone, auth_url)
            self.tenant_list.append(self.tenant)

            # Create the resources associated with the user
            # the tenant class creates the user and offloads
            # all resource creation inside a user to user class
            self.tenant.create_user_elements(config_scale.server)


        # Clean up all resources by default unless specified otherwise

        if config_scale.server['cleanup_resources']:
            self.teardown_resources("server")
        if config_scale.client['cleanup_resources']:
            self.teardown_resources("client")

    def teardown_resources(self, role):
        """
        Responsible for cleanup
        of all resources
        """
        # Clean up all tenant resources for cloud
        # Tenant class leverages the user class to clean up
        # all user resources similar to the create resource flow
        if role == "server":
            for tenant_current in self.tenant_list:
                print "Deleting tenant resources for tenant %s" % (tenant_current)
                tenant_current.delete_tenant_with_users()
        else:
            for tenant_temp in self.tenant_list_testing:
                print "Deleting tenant resources for testing tenant %s" % (tenant_temp)
                tenant_temp.delete_tenant_with_users()


if __name__ == '__main__':
    # The default configuration file for CloudScale
    default_cfg_file = "cfg.scale.yaml"

    # Read the command line arguments and parse them
    parser = argparse.ArgumentParser(description="Openstack Scale Test Tool")
    # Accept the rc file for cloud under test and testing cloud if present
    parser.add_argument('-r1', '--rc1', dest='rc1',
                        action='store',
                        help='source OpenStack credentials from rc file tested cloud',
                        metavar='<openrc1_file>')
    parser.add_argument('-r2', '--rc2', dest='rc2',
                        action='store',
                        help='source Openstack credentials from rc file testing cloud',
                        metavar='<openrc2_file>')
    parser.add_argument('-p1', '--password1', dest='pwd1',
                        action='store',
                        help='OpenStack password tested cloud',
                        metavar='<password1>')
    parser.add_argument('-p2', '--password2', dest='pwd2',
                        action='store',
                        help='Openstack password testing cloud',
                        metavar='<password2>')
    parser.add_argument('-d', '--debug', dest='debug',
                        default=False,
                        action='store_true',
                        help='debug flag (very verbose)')
    parser.add_argument('--no-env', dest='no_env',
                        default=False,
                        action='store_true',
                        help='do not read env variables')

    (opts, args) = parser.parse_known_args()


    # Read the configuration file
    config_scale = configure.Configuration.from_file(default_cfg_file).configure()
    config_scale.debug = opts.debug

    # Now parse the openrc file and store credentials for the tested and testing cloud
    cred = credentials.Credentials(opts.rc1, opts.pwd1, opts.no_env)
    cred_testing = credentials.Credentials(opts.rc2, opts.pwd2, opts.no_env)

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and
    # deletion
    kloud_buster = KloudBuster()
    kloud_buster.runner()
