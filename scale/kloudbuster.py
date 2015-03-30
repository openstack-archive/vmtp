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
import time

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

    def create_keystone_client(self, cred_current):
        """
        Return the keystone client given a credential
        """
        creds = cred_current.get_credentials()
        return (keystoneclient.Client(**creds), creds['auth_url'])

    def create_tenant_resources(self, role, keystone, auth_url):
        if role == "testing":
            print "===================================="
            print "Creating resources for Testing cloud"
            for tenant_count_testing in xrange(config_scale.client['number_tenants']):
                tenant_name_testing = "kloudbuster_tenant_testing_" + str(tenant_count_testing)
                self.tenant_testing = tenant.Tenant(tenant_name_testing,
                                                    keystone, auth_url)
                self.tenant_list_testing.append(self.tenant_testing)
                self.tenant_testing.create_user_elements(config_scale.client)
        else:
            print "==================================="
            print "Creating resources for tested cloud"
            for tenant_count in xrange(config_scale.server['number_tenants']):
                # For now have a serial naming convention for tenants
                tenant_name = "kloudbuster_tenant_" + str(tenant_count)
                # Create the tenant and append it to global list
                self.tenant = tenant.Tenant(tenant_name, keystone, auth_url, self.shared_network)
                self.tenant_list.append(self.tenant)
                self.tenant.create_user_elements(config_scale.server)

    def print_vms_info(self, role):
        pass

    def print_provision_info(self):
        """
        Function that iterates and prints all VM info
        for tested and testing cloud
        """
        pass

    def runner(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """

        # Create the keystone client for tenant and user creation operations
        # for the tested cloud
        keystone, auth_url = self.create_keystone_client(cred)
        keystone_testing, auth_url_testing = self.create_keystone_client(cred_testing)

        # Create the testing cloud resources
        self.create_tenant_resources("testing", keystone_testing, auth_url_testing)
        # Find the shared network if the cloud used to testing is same
        if config_scale.client['run_on_same_cloud']:
            self.shared_network = self.tenant_list_testing[0].tenant_user_list[0].\
                router_list[0].network_list[0]
        self.create_tenant_resources("tested", keystone, auth_url)

        # Function that print all the provisioning info
        self.print_provision_info()

        svr = self.tenant.tenant_user_list[0].router_list[0].network_list[0].instance_list[0]
        client = self.tenant_testing.tenant_user_list[0].router_list[0].network_list[0].\
            instance_list[0]
        target_url = "http://" + svr.fip_ip + "/index.html"

        print "Server IP: " + svr.fip_ip
        print "Client IP: " + client.fip_ip
        print target_url

        client.setup_ssh(client.fip_ip, "ubuntu")
        # HACK ALERT!!!
        # Need to wait until all servers are up running before starting to inject traffic
        time.sleep(20)
        res = client.run_http_client(target_url, threads=2, connections=10000,
                                     timeout=5, connection_type="New")
        print res

        if config_scale.server['cleanup_resources']:
            self.teardown_resources("tested")
        if config_scale.client['cleanup_resources']:
            self.teardown_resources("testing")

    def teardown_resources(self, role):
        """
        Responsible for cleanup
        of all resources
        """
        # Clean up all tenant resources for cloud
        # Tenant class leverages the user class to clean up
        # all user resources similar to the create resource flow
        if role == "tested":
            for tenant_current in self.tenant_list:
                print "Deleting tenant resources for tenant %s" % (tenant_current)
                tenant_current.delete_tenant_with_users()
        else:
            for tenant_temp in self.tenant_list_testing:
                print "Deleting tenant resources for testing tenant %s" % (tenant_temp)
                tenant_temp.delete_tenant_with_users()

    def return_credentials(self, rc, passwd, no_env):
        """
        Retrieve the credentials based on
        supplied parameters or sourced openrc
        """
        return credentials.Credentials(rc, passwd, no_env)

if __name__ == '__main__':
    # The default configuration file for CloudScale
    default_cfg_file = "cfg.scale.yaml"

    # Read the command line arguments and parse them
    parser = argparse.ArgumentParser(description="Openstack Scale Test Tool")
    # Accept the rc file for cloud under test and testing cloud if present
    parser.add_argument('-tested_rc', '--tested_rc', dest='tested_rc',
                        action='store',
                        help='source OpenStack credentials from rc file tested cloud',
                        metavar='<tested_openrc_file>')
    parser.add_argument('-testing_rc', '--testing_rc', dest='testing_rc',
                        action='store',
                        help='source Openstack credentials from rc file testing cloud',
                        metavar='<testing_openrc_file>')
    parser.add_argument('-passwd_tested', '--passwd_tested', dest='passwd_tested',
                        action='store',
                        help='OpenStack password tested cloud',
                        metavar='<passwd_tested>')
    parser.add_argument('-passwd_testing', '--passwd_testing', dest='passwd_testing',
                        action='store',
                        help='Openstack password testing cloud',
                        metavar='<passwd_testing>')
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

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and
    # deletion
    kloud_buster = KloudBuster()
    # Retrieve the credentials
    cred = kloud_buster.return_credentials(opts.tested_rc, opts.passwd_tested, opts.no_env)
    if opts.testing_rc:
        cred_testing = kloud_buster.return_credentials(opts.rc2, opts.pwd2, opts.no_env)
    else:
        # Use the same openrc file for both cases
        cred_testing = cred
    kloud_buster.runner()
