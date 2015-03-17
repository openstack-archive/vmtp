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

    def runner(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """
        # Create the keystone client for tenant and user creation operations
        creds = cred.get_credentials()
        keystone = keystoneclient.Client(**creds)

        # Store the auth url. Pass this around since
        # this does not change for all tenants and users
        auth_url = creds['auth_url']

        # The main tenant creation loop which invokes user creations
        # Create tenant resources and trigger User resource creations
        for tenant_count in xrange(config_scale.number_tenants):
            # For now have a serial naming convention for tenants
            tenant_name = "kloudbuster_tenant_" + str(tenant_count)
            # Create the tenant and append it to global list
            print "Creating tenant %s" % (tenant_name)
            self.tenant = tenant.Tenant(tenant_name, keystone, auth_url)
            self.tenant_list.append(self.tenant)

            # Create the resources associated with the user
            # the tenant class creates the user and offloads
            # all resource creation inside a user to user class
            self.tenant.create_user_elements(config_scale)

        # Clean up all resources by default unless specified otherwise
        if config_scale.cleanup_resources:
            self.teardown_resources()

    def teardown_resources(self):
        """
        Responsible for cleanup
        of all resources
        """
        # Clean up all tenant resources
        # Tenant class leverages the user class to clean up
        # all user resources similar to the create resource flow
        for tenant_current in self.tenant_list:
            print "Deleting tenant resources for tenant %s" % (tenant_current)
            tenant_current.delete_tenant_with_users()


if __name__ == '__main__':
    # The default configuration file for CloudScale
    default_cfg_file = "cfg.scale.yaml"

    # Read the command line arguments and parse them
    parser = argparse.ArgumentParser(description="Openstack Scale Test Tool")
    parser.add_argument('-r', '--rc', dest='rc',
                        action='store',
                        help='source OpenStack credentials from rc file',
                        metavar='<openrc_file>')
    parser.add_argument('-p', '--password', dest='pwd',
                        action='store',
                        help='OpenStack password',
                        metavar='<password>')
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

    # Now parse the openrc file and store credentials
    cred = credentials.Credentials(opts.rc, opts.pwd, opts.no_env)

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and
    # deletion
    kloud_buster = KloudBuster()
    kloud_buster.runner()
