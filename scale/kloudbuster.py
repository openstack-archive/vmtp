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

import configure
import os
import sys
import traceback

from keystoneclient.v2_0 import client as keystoneclient
from novaclient.exceptions import ClientException
from oslo_config import cfg

import credentials
import kb_scheduler
import log as logging
import sshutils
import tenant

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def get_absolute_path_for_file(file_name):
    '''
    Return the filename in absolute path for any file
    passed as relateive path.
    '''
    if os.path.isabs(__file__):
        abs_file_path = os.path.join(__file__.split("kloudbuster.py")[0],
                                     file_name)
    else:
        abs_file = os.path.abspath(__file__)
        abs_file_path = os.path.join(abs_file.split("kloudbuster.py")[0],
                                     file_name)

    return abs_file_path

def create_keystone_client(cred):
    """
    Return the keystone client and auth URL given a credential
    """
    creds = cred.get_credentials()
    return (keystoneclient.Client(**creds), creds['auth_url'])

class Kloud(object):
    def __init__(self, scale_cfg, cred, testing_side=False):
        self.cred = cred
        self.tenant_list = []
        self.testing_side = testing_side
        self.scale_cfg = scale_cfg
        self.keystone, self.auth_url = create_keystone_client(cred)
        if testing_side:
            self.prefix = 'KBc'
        else:
            self.prefix = 'KBs'
        LOG.info("Creating kloud: " + self.prefix)
        # if this cloud is sharing a network then all tenants must hook up to
        # it and on deletion that shared network must NOT be deleted
        # as it will be deleted by the owner
        self.shared_network = None

    def create_resources(self, shared_net=None):
        self.shared_network = shared_net
        for tenant_count in xrange(self.scale_cfg['number_tenants']):
            tenant_name = self.prefix + "_T" + str(tenant_count)
            new_tenant = tenant.Tenant(tenant_name, self)
            self.tenant_list.append(new_tenant)
            new_tenant.create_resources()

    def delete_resources(self):
        for tnt in self.tenant_list:
            tnt.delete_resources()

    def get_first_network(self):
        if self.tenant_list:
            return self.tenant_list[0].get_first_network()
        return None

    def get_all_instances(self):
        all_instances = []
        for tnt in self.tenant_list:
            all_instances.extend(tnt.get_all_instances())
        return all_instances

class KloudBuster(object):
    """
    Creates resources on the cloud for loading up the cloud
    1. Tenants
    2. Users per tenant
    3. Routers per user
    4. Networks per router
    5. Instances per network
    """
    def __init__(self, cred, testing_cred):
        # List of tenant objects to keep track of all tenants
        self.tenant_list = []
        self.tenant = None
        self.tenant_list_testing = []
        self.tenant_testing = None
        # to do : check on same auth_url instead
        if cred == testing_cred:
            self.single_cloud = True
        else:
            self.single_cloud = False
        self.kloud = Kloud(config_scale.server, cred)
        self.testing_kloud = Kloud(config_scale.client, testing_cred, testing_side=True)

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
            # Create the testing cloud resources
            self.testing_kloud.create_resources()
            # Find the shared network if the cloud used to testing is same
            if self.single_cloud:
                shared_network = self.testing_kloud.get_first_network()
            else:
                shared_network = None
            self.kloud.create_resources(shared_network)

            # Function that print all the provisioning info
            self.print_provision_info()

            # We supposed to have a mapping framework/algorithm to mapping clients to servers.
            # e.g. 1:1 mapping, 1:n mapping, n:1 mapping, etc.
            # Here we are using N*1:1
            client_list = self.testing_kloud.get_all_instances()
            for idx, svr in enumerate(self.kloud.get_all_instances()):
                client_list[idx].target_server = svr
                client_list[idx].target_url = "http://%s/index.html" %\
                    (svr.fip_ip or svr.fixed_ip)

            kbscheduler = kb_scheduler.KBScheduler()
            kbscheduler.run(client_list)
        except KeyboardInterrupt:
            traceback.format_exc()
        except (sshutils.SSHError, ClientException, Exception):
            traceback.print_exc()

        # Cleanup: start with tested side first
        # then testing side last (order is important because of the shared network)
        if config_scale.server['cleanup_resources']:
            self.kloud.delete_resources()
        if config_scale.client['cleanup_resources']:
            self.testing_kloud.delete_resources()

if __name__ == '__main__':
    # The default configuration file for KloudBuster
    default_cfg_file = get_absolute_path_for_file("cfg.scale.yaml")

    cli_opts = [
        cfg.StrOpt("config",
                   short="c",
                   default=None,
                   help="Override default values with a config file"),
        cfg.StrOpt("tested-rc",
                   default=None,
                   help="Tested cloud openrc credentials file"),
        cfg.StrOpt("testing-rc",
                   default=None,
                   help="Testing cloud openrc credentials file"),
        cfg.StrOpt("passwd_tested",
                   default=None,
                   help="Tested cloud password"),
        cfg.StrOpt("passwd_testing",
                   default=None,
                   help="OpenStack password testing cloud"),
        cfg.BoolOpt("no-env",
                    default=False,
                    help="Do not read env variables")
    ]
    CONF.register_cli_opts(cli_opts)
    CONF.set_default("verbose", True)
    CONF(sys.argv[1:])

    logging.setup("kloudbuster")

    # Read the configuration file
    config_scale = configure.Configuration.from_file(default_cfg_file).configure()
    if CONF.config:
        alt_config = configure.Configuration.from_file(CONF.config).configure()
        config_scale = config_scale.merge(alt_config)

    # Retrieve the credentials
    cred = credentials.Credentials(CONF.tested_rc, CONF.passwd_tested, CONF.no_env)
    if CONF.testing_rc and CONF.testing_rc != CONF.tested_rc:
        cred_testing = credentials.Credentials(CONF.testing_rc,
                                               CONF.passwd_testing,
                                               CONF.no_env)
        single_cloud = False
    else:
        # Use the same openrc file for both cases
        cred_testing = cred
        single_cloud = True

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and
    # deletion
    kloudbuster = KloudBuster(cred, cred_testing)
    kloudbuster.run()
