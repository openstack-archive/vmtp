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

import json
from multiprocessing.pool import ThreadPool
import os
import sys
import threading
import traceback

import base_network
import configure
from kb_scheduler import KBScheduler
from keystoneclient.v2_0 import client as keystoneclient
import log as logging
from novaclient.exceptions import ClientException
from oslo_config import cfg
from tabulate import tabulate
import tenant

import credentials
import sshutils

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

def create_keystone_client(admin_creds):
    """
    Return the keystone client and auth URL given a credential
    """
    creds = admin_creds.get_credentials()
    return (keystoneclient.Client(**creds), creds['auth_url'])

class Kloud(object):
    def __init__(self, scale_cfg, admin_creds, testing_side=False):
        self.cred = admin_creds
        self.tenant_list = []
        self.testing_side = testing_side
        self.scale_cfg = scale_cfg
        self.keystone, self.auth_url = create_keystone_client(self.cred)
        if testing_side:
            self.prefix = 'KBc'
            self.name = 'Client Kloud'
        else:
            self.prefix = 'KBs'
            self.name = 'Server Kloud'
        LOG.info("Creating kloud: " + self.prefix)
        # if this cloud is sharing a network then all tenants must hook up to
        # it and on deletion that shared network must NOT be deleted
        # as it will be deleted by the owner

        # pre-compute the placement az to use for all VMs
        self.placement_az = None
        if scale_cfg['availability_zone']:
            self.placement_az = scale_cfg['availability_zone']
        LOG.info('%s Availability Zone: %s' % (self.name, self.placement_az))

    def create_resources(self):
        for tenant_count in xrange(self.scale_cfg['number_tenants']):
            tenant_name = self.prefix + "-T" + str(tenant_count)
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

    def get_all_instances(self, include_kb_proxy=False):
        all_instances = []
        for tnt in self.tenant_list:
            all_instances.extend(tnt.get_all_instances())
        if (not include_kb_proxy) and all_instances[-1].vm_name == 'KB-PROXY':
            all_instances.pop()

        return all_instances

    def attach_to_shared_net(self, shared_net):
        # If a shared network exists create a port on this
        # network and attach to router interface
        for tnt in self.tenant_list:
            for usr in tnt.user_list:
                for rtr in usr.router_list:
                    rtr.shared_network = shared_net
                    rtr.attach_router_interface(shared_net, use_port=True)
                    for net in rtr.network_list:
                        for ins in net.instance_list:
                            ins.shared_interface_ip = rtr.shared_interface_ip

    def get_az(self):
        '''Placement algorithm for all VMs created in this kloud
        Return None if placement to be provided by the nova scheduler
        Else return an availability zone to use (e.g. "nova")
        or a compute host to use (e.g. "nova:tme123")
        '''
        return self.placement_az

    def create_vm(self, instance):
        LOG.info("Creating Instance: " + instance.vm_name)
        instance.create_server(**instance.boot_info)
        if not instance.instance:
            return

        instance.fixed_ip = instance.instance.networks.values()[0][0]
        if (instance.vm_name == "KB-PROXY") and (not instance.config['use_floatingip']):
            neutron_client = instance.network.router.user.neutron_client
            external_network = base_network.find_external_network(neutron_client)
            instance.fip = base_network.create_floating_ip(neutron_client, external_network)
            instance.fip_ip = instance.fip['floatingip']['floating_ip_address']

        if instance.fip:
            # Associate the floating ip with this instance
            instance.instance.add_floating_ip(instance.fip_ip)
            instance.ssh_ip = instance.fip_ip
        else:
            # Store the fixed ip as ssh ip since there is no floating ip
            instance.ssh_ip = instance.fixed_ip

    def create_vms(self, vm_creation_concurrency):
        tpool = ThreadPool(processes=vm_creation_concurrency)
        tpool.map(self.create_vm, self.get_all_instances())


class KloudBuster(object):
    """
    Creates resources on the cloud for loading up the cloud
    1. Tenants
    2. Users per tenant
    3. Routers per user
    4. Networks per router
    5. Instances per network
    """
    def __init__(self, server_cred, client_cred, server_cfg, client_cfg):
        # List of tenant objects to keep track of all tenants
        self.tenant_list = []
        self.tenant = None
        self.tenant_list_testing = []
        self.tenant_testing = None
        self.server_cfg = server_cfg
        self.client_cfg = client_cfg
        # TODO(check on same auth_url instead)
        if server_cred == client_cred:
            self.single_cloud = True
        else:
            self.single_cloud = False
        self.kloud = Kloud(server_cfg, server_cred)
        self.testing_kloud = Kloud(client_cfg, client_cred, testing_side=True)
        self.kb_proxy = None
        self.final_result = None
        self.server_vm_create_thread = None
        self.client_vm_create_thread = None

    def print_provision_info(self):
        """
        Function that iterates and prints all VM info
        for tested and testing cloud
        """
        table = [["VM Name", "Host", "Internal IP", "Floating IP", "Subnet", "Shared Interface IP"]]
        client_list = self.kloud.get_all_instances()
        for instance in client_list:
            row = [instance.vm_name, instance.host, instance.fixed_ip,
                   instance.fip_ip, instance.subnet_ip, instance.shared_interface_ip]
            table.append(row)
        LOG.info('Provision Details (Tested Kloud)\n' +
                 tabulate(table, headers="firstrow", tablefmt="psql"))

        table = [["VM Name", "Host", "Internal IP", "Floating IP", "Subnet"]]
        client_list = self.testing_kloud.get_all_instances(include_kb_proxy=True)
        for instance in client_list:
            row = [instance.vm_name, instance.host, instance.fixed_ip,
                   instance.fip_ip, instance.subnet_ip]
            table.append(row)
        LOG.info('Provision Details (Testing Kloud)\n' +
                 tabulate(table, headers="firstrow", tablefmt="psql"))

    def gen_user_data(self, role):
        LOG.info("Preparing metadata for VMs... (%s)" % role)
        if role == "Server":
            svr_list = self.kloud.get_all_instances()
            for ins in svr_list:
                ins.user_data['role'] = "Server"
                ins.boot_info['user_data'] = str(ins.user_data)
        elif role == "Client":
            # We supposed to have a mapping framework/algorithm to mapping clients to servers.
            # e.g. 1:1 mapping, 1:n mapping, n:1 mapping, etc.
            # Here we are using N*1:1
            client_list = self.testing_kloud.get_all_instances()
            svr_list = self.kloud.get_all_instances()

            for idx, ins in enumerate(client_list):
                ins.target_url = "http://%s/index.html" %\
                    (svr_list[idx].fip_ip or svr_list[idx].fixed_ip)
                ins.user_data['role'] = "Client"
                ins.user_data['redis_server'] = self.kb_proxy.fixed_ip
                ins.user_data['redis_server_port'] = 6379
                ins.user_data['target_subnet_ip'] = svr_list[idx].subnet_ip
                ins.user_data['target_shared_interface_ip'] = svr_list[idx].shared_interface_ip
                ins.user_data['target_url'] = ins.target_url
                ins.user_data['http_tool'] = ins.config['http_tool']
                ins.user_data['http_tool_configs'] = ins.config['http_tool_configs']
                ins.boot_info['user_data'] = str(ins.user_data)

    def run(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """
        kbscheduler = None
        vm_creation_concurrency = self.client_cfg.vm_creation_concurrency
        try:
            self.kloud.create_resources()
            self.testing_kloud.create_resources()

            # Start the scheduler and ready for the incoming redis messages
            client_list = self.testing_kloud.get_all_instances()
            server_list = self.kloud.get_all_instances()

            # Setting up the KloudBuster Proxy node
            self.kb_proxy = client_list[-1]
            client_list.pop()

            self.kb_proxy.vm_name = "KB-PROXY"
            self.kb_proxy.user_data['role'] = 'KB-PROXY'
            self.kb_proxy.boot_info['flavor_type'] = 'm1.small'
            self.kb_proxy.boot_info['user_data'] = str(self.kb_proxy.user_data)
            self.testing_kloud.create_vm(self.kb_proxy)

            kbscheduler = KBScheduler(client_list, self.client_cfg, self.single_cloud)
            kbscheduler.setup_redis(self.kb_proxy.fip_ip)

            if self.single_cloud:
                # Find the shared network if the cloud used to testing is same
                # Attach the router in tested kloud to the shared network
                shared_net = self.testing_kloud.get_first_network()
                self.kloud.attach_to_shared_net(shared_net)

            # Create VMs in both tested and testing kloud concurrently
            self.client_vm_create_thread = threading.Thread(target=self.testing_kloud.create_vms,
                                                            args=[vm_creation_concurrency])
            self.server_vm_create_thread = threading.Thread(target=self.kloud.create_vms,
                                                            args=[vm_creation_concurrency])
            self.client_vm_create_thread.daemon = True
            self.server_vm_create_thread.daemon = True
            if self.single_cloud:
                self.gen_user_data("Server")
                self.server_vm_create_thread.start()
                self.server_vm_create_thread.join()
                self.gen_user_data("Client")
                self.client_vm_create_thread.start()
                self.client_vm_create_thread.join()
            else:
                self.gen_user_data("Server")
                self.gen_user_data("Client")
                self.server_vm_create_thread.start()
                self.client_vm_create_thread.start()
                self.server_vm_create_thread.join()
                self.client_vm_create_thread.join()

            # Function that print all the provisioning info
            self.print_provision_info()

            # Run the scheduler to perform benchmarkings
            kbscheduler.run()
            self.final_result = kbscheduler.tool_result
            self.final_result['total_server_vms'] = len(server_list)
            self.final_result['total_client_vms'] = len(client_list)
            LOG.info(self.final_result)
        except KeyboardInterrupt:
            traceback.format_exc()
        except (sshutils.SSHError, ClientException, Exception):
            traceback.print_exc()

        # Cleanup: start with tested side first
        # then testing side last (order is important because of the shared network)
        if self.server_cfg['cleanup_resources']:
            try:
                self.kloud.delete_resources()
            except Exception:
                traceback.print_exc()
        if self.client_cfg['cleanup_resources']:
            try:
                self.testing_kloud.delete_resources()
            except Exception:
                traceback.print_exc()
        if kbscheduler:
            kbscheduler.dispose()

def get_total_vm_count(config):
    return (config['number_tenants'] * config['users_per_tenant'] *
            config['routers_per_user'] * config['networks_per_router'] *
            config['vms_per_network'])

# Some hardcoded client side options we do not want users to change
hardcoded_client_cfg = {
    # Number of tenants to be created on the cloud
    'number_tenants': 1,

    # Number of Users to be created inside the tenant
    'users_per_tenant': 1,

    # Number of routers to be created within the context of each User
    # For now support only 1 router per user
    'routers_per_user': 1,

    # Number of networks to be created within the context of each Router
    # Assumes 1 subnet per network
    'networks_per_router': 1,

    # Number of VM instances to be created within the context of each Network
    'vms_per_network': 1,

    # Number of security groups per network
    'secgroups_per_network': 1
}

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
        cfg.StrOpt("json",
                   default=None,
                   help='store results in JSON format file'),
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
    else:
        # Use the same openrc file for both cases
        cred_testing = cred

    # Initialize the key pair name
    if config_scale['public_key_file']:
        # verify the public key file exists
        if not os.path.exists(config_scale['public_key_file']):
            LOG.error('Error: Invalid public key file: ' + config_scale['public_key_file'])
            sys.exit(1)
    else:
        # pick the user's public key if there is one
        pub_key = os.path.expanduser('~/.ssh/id_rsa.pub')
        if os.path.isfile(pub_key):
            config_scale['public_key_file'] = pub_key
            LOG.info('Using %s as public key for all VMs' % (pub_key))

    # A bit of config dict surgery, extract out the client and server side
    # and transplant the remaining (common part) into the client and server dict
    server_side_cfg = config_scale.pop('server')
    client_side_cfg = config_scale.pop('client')
    server_side_cfg.update(config_scale)
    client_side_cfg.update(config_scale)

    # Hardcode a few client side options
    client_side_cfg.update(hardcoded_client_cfg)

    # Adjust the VMs per network on the client side to match the total
    # VMs on the server side (1:1)
    # There is an additional VM in client kloud as a proxy node
    client_side_cfg['vms_per_network'] = get_total_vm_count(server_side_cfg) + 1

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and
    # deletion
    kloudbuster = KloudBuster(cred, cred_testing, server_side_cfg, client_side_cfg)
    kloudbuster.run()

    if CONF.json:
        '''Save results in JSON format file.'''
        LOG.info('Saving results in json file: ' + CONF.json + "...")
        with open(CONF.json, 'w') as jfp:
            json.dump(kloudbuster.final_result, jfp, indent=4, sort_keys=True)
