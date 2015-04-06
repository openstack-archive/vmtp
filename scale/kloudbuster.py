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
import traceback

import credentials
import sshutils

import configure
from keystoneclient.v2_0 import client as keystoneclient
from novaclient.exceptions import ClientException
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

    def run(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """

        try:
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
            target_url = "http://%s/index.html" % (svr.fip_ip or svr.fixed_ip)

            print "Server IP: %s" % (svr.fip_ip or svr.fixed_ip)
            print "Client IP: %s" % client.fip_ip
            print target_url

            client.setup_ssh(client.fip_ip, "ubuntu")
            if not svr.fip_ip:
                rc = client.add_static_route(svr.subnet_ip,
                                             svr.shared_interface_ip)
                if rc > 0:
                    print "Failed to add static route, error code: %i" % rc
                    raise
                if svr.subnet_ip not in client.get_static_route(svr.subnet_ip):
                    print "Failed to get static route for %s" % svr.subnet_ip
                    raise
                if not client.ping_check(svr.fixed_ip, 2, 80):
                    print "Failed to ping server %%" % svr.fixed_ip
                    raise
            # HACK ALERT!!!
            # Need to wait until all servers are up running before starting to inject traffic
            time.sleep(20)
            res = client.run_http_client(target_url, threads=2, connections=10000,
                                         timeout=5, connection_type="Keep-alive")
            print res
        except KeyboardInterrupt:
            traceback.format_exc()
        except (sshutils.SSHError, ClientException, Exception):
            traceback.print_exc()

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

    def get_credentials(self, rc, passwd, no_env):
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
    parser.add_argument('-r', '--rc', dest='tested_rc',
                        action='store',
                        help='tested cloud openrc credentials file',
                        metavar='<tested_openrc_file>')
    parser.add_argument('--testing-rc', dest='testing_rc',
                        action='store',
                        help='testing cloud openrc credentials file',
                        metavar='<testing_openrc_file>')
    parser.add_argument('-p', '--passwd', dest='passwd_tested',
                        action='store',
                        help='tested cloud password',
                        metavar='<passwd_tested>')
    parser.add_argument('--passwd_testing', dest='passwd_testing',
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
    kloudbuster = KloudBuster()
    # Retrieve the credentials
    cred = kloudbuster.get_credentials(opts.tested_rc, opts.passwd_tested, opts.no_env)
    if opts.testing_rc and opts.testing_rc != opts.tested_rc:
        cred_testing = kloudbuster.get_credentials(opts.testing_rc,
                                                   opts.passwd_testing,
                                                   opts.no_env)
    else:
        # Use the same openrc file for both cases
        cred_testing = cred

    kloudbuster.run()
