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

import base_compute
import base_network
from glanceclient.v2 import client as glanceclient
from kb_config import KBConfig
from kb_runner import KBRunner
from kb_scheduler import KBScheduler
from keystoneclient.v2_0 import client as keystoneclient
import log as logging
from novaclient.exceptions import ClientException
from oslo_config import cfg
from tabulate import tabulate
import tenant

import sshutils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

__version__ = '1.0.0'
__required_agent_version__ = '1.0.0'


class KBVMCreationException(Exception):
    pass


def create_keystone_client(admin_creds):
    """
    Return the keystone client and auth URL given a credential
    """
    creds = admin_creds.get_credentials()
    return (keystoneclient.Client(**creds), creds['auth_url'])

def check_and_upload_images(cred, cred_testing, server_img_name, client_img_name):
    keystone_list = [create_keystone_client(cred)[0], create_keystone_client(cred_testing)[0]]
    keystone_dict = dict(zip(['Server kloud', 'Client kloud'], keystone_list))
    img_name_dict = dict(zip(['Server kloud', 'Client kloud'], [server_img_name, client_img_name]))

    for kloud, keystone in keystone_dict.items():
        img_found = False
        glance_endpoint = keystone.service_catalog.url_for(
            service_type='image', endpoint_type='publicURL')
        glance_client = glanceclient.Client(glance_endpoint, token=keystone.auth_token)
        for img in glance_client.images.list():
            if img['name'] == img_name_dict[kloud]:
                img_found = True
                break
        if img.visibility != 'public' and CONF.tenants_list:
            LOG.error("Image must be public when running in reusing mode.")
            sys.exit(1)

        if not img_found:
            # Trying upload images
            LOG.info("Image is not found in %s, trying to upload..." % (kloud))
            if not os.path.exists('dib/kloudbuster.qcow2'):
                LOG.error("Image file dib/kloudbuster.qcow2 is not present, please refer "
                          "to dib/README.rst for how to build image for KloudBuster.")
                return False
            with open('dib/kloudbuster.qcow2') as fimage:
                image = glance_client.images.create(name=img_name_dict[kloud],
                                                    disk_format="qcow2",
                                                    container_format="bare",
                                                    visibility='public')
                glance_client.images.upload(image['id'], fimage)

    return True

class Kloud(object):
    def __init__(self, scale_cfg, admin_creds, reusing_tenants, testing_side=False):
        self.cred = admin_creds
        self.tenant_list = []
        self.testing_side = testing_side
        self.scale_cfg = scale_cfg
        self.reusing_tenants = reusing_tenants
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

    def create_resources(self, tenant_quota):
        if self.reusing_tenants:
            for tenant_info in self.reusing_tenants:
                tenant_name = tenant_info['name']
                user_list = tenant_info['user']
                tenant_instance = tenant.Tenant(tenant_name, self, tenant_quota,
                                                reusing_users=user_list)
                self.tenant_list.append(tenant_instance)
        else:
            for tenant_count in xrange(self.scale_cfg['number_tenants']):
                tenant_name = self.prefix + "-T" + str(tenant_count)
                tenant_instance = tenant.Tenant(tenant_name, self, tenant_quota)
                self.tenant_list.append(tenant_instance)

        for tenant_instance in self.tenant_list:
            tenant_instance.create_resources()

        if not self.reusing_tenants:
            # Create flavors for servers, clients, and kb-proxy nodes
            nova_client = self.tenant_list[0].user_list[0].nova_client
            flavor_manager = base_compute.Flavor(nova_client)
            flavor_dict = self.scale_cfg.flavor
            if self.testing_side:
                flavor_manager.create_flavor('kb.client', override=True, **flavor_dict)
                flavor_manager.create_flavor('kb.proxy', override=True, ram=2048, vcpus=1, disk=20)
            else:
                flavor_manager.create_flavor('kb.server', override=True, **flavor_dict)

    def delete_resources(self):
        # Deleting flavors created by KloudBuster
        try:
            nova_client = self.tenant_list[0].user_list[0].nova_client
        except Exception:
            # NOVA Client is not yet initialized, so skip cleaning up...
            return

        if not self.reusing_tenants:
            flavor_manager = base_compute.Flavor(nova_client)
            if self.testing_side:
                flavor_manager.delete_flavor('kb.client')
                flavor_manager.delete_flavor('kb.proxy')
            else:
                flavor_manager.delete_flavor('kb.server')

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
            raise KBVMCreationException()

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
    def __init__(self, server_cred, client_cred, server_cfg, client_cfg, topology, tenants_list):
        # List of tenant objects to keep track of all tenants
        self.server_cfg = server_cfg
        self.client_cfg = client_cfg
        if topology and tenants_list:
            self.topology = None
            LOG.warn("REUSING MODE: Topology configs will be ignored.")
        else:
            self.topology = topology
        if tenants_list:
            self.tenants_list = tenants_list
            LOG.warn("REUSING MODE: The quota will not adjust automatically.")
            LOG.warn("REUSING MODE: The flavor configs will be ignored, and m1.small is used.")
        else:
            self.tenants_list = {'server': None, 'client': None}
        # TODO(check on same auth_url instead)
        if server_cred == client_cred:
            self.single_cloud = True
        else:
            self.single_cloud = False
        self.kloud = Kloud(server_cfg, server_cred, self.tenants_list['server'])
        self.testing_kloud = Kloud(client_cfg, client_cred,
                                   self.tenants_list['client'],
                                   testing_side=True)
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
            KBScheduler.setup_vm_placement(role, svr_list, self.topology,
                                           self.kloud.placement_az, "Round-robin")
            for ins in svr_list:
                ins.user_data['role'] = 'Server'
                ins.boot_info['flavor_type'] = 'm1.small' if self.tenants_list else 'kb.server'
                ins.boot_info['user_data'] = str(ins.user_data)
        elif role == "Client":
            client_list = self.testing_kloud.get_all_instances()
            svr_list = self.kloud.get_all_instances()
            KBScheduler.setup_vm_mappings(client_list, svr_list, "1:1")
            KBScheduler.setup_vm_placement(role, client_list, self.topology,
                                           self.testing_kloud.placement_az, "Round-robin")
            for idx, ins in enumerate(client_list):
                ins.user_data['role'] = 'Client'
                ins.user_data['vm_name'] = ins.vm_name
                ins.user_data['redis_server'] = self.kb_proxy.fixed_ip
                ins.user_data['redis_server_port'] = 6379
                ins.user_data['target_subnet_ip'] = svr_list[idx].subnet_ip
                ins.user_data['target_shared_interface_ip'] = svr_list[idx].shared_interface_ip
                ins.user_data['http_tool'] = ins.config['http_tool']
                ins.user_data['http_tool_configs'] = ins.config['http_tool_configs']
                ins.boot_info['flavor_type'] = 'm1.small' if self.tenants_list else 'kb.client'
                ins.boot_info['user_data'] = str(ins.user_data)

    def run(self):
        """
        The runner for KloudBuster Tests
        Executes tests serially
        Support concurrency in fututure
        """
        kbrunner = None
        vm_creation_concurrency = self.client_cfg.vm_creation_concurrency
        try:
            tenant_quota = self.calc_tenant_quota()
            self.kloud.create_resources(tenant_quota['server'])
            self.testing_kloud.create_resources(tenant_quota['client'])

            # Start the runner and ready for the incoming redis messages
            client_list = self.testing_kloud.get_all_instances()
            server_list = self.kloud.get_all_instances()

            # Setting up the KloudBuster Proxy node
            self.kb_proxy = client_list[-1]
            client_list.pop()

            self.kb_proxy.vm_name = 'KB-PROXY'
            self.kb_proxy.user_data['role'] = 'KB-PROXY'
            self.kb_proxy.boot_info['flavor_type'] = 'm1.small' if self.tenants_list else 'kb.proxy'
            if self.testing_kloud.placement_az:
                self.kb_proxy.boot_info['avail_zone'] = "%s:%s" %\
                    (self.testing_kloud.placement_az, self.topology.clients_rack.split()[0])
            self.kb_proxy.boot_info['user_data'] = str(self.kb_proxy.user_data)
            self.testing_kloud.create_vm(self.kb_proxy)

            kbrunner = KBRunner(client_list, self.client_cfg,
                                __required_agent_version__,
                                self.single_cloud)
            kbrunner.setup_redis(self.kb_proxy.fip_ip)

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

            # Run the runner to perform benchmarkings
            kbrunner.run()
            self.final_result = kbrunner.tool_result
            self.final_result['total_server_vms'] = len(server_list)
            self.final_result['total_client_vms'] = len(client_list)
            # self.final_result['host_stats'] = kbrunner.host_stats
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
        if kbrunner:
            kbrunner.dispose()

    def get_tenant_vm_count(self, config):
        return (config['users_per_tenant'] * config['routers_per_user'] *
                config['networks_per_router'] * config['vms_per_network'])

    def calc_neutron_quota(self):
        total_vm = self.get_tenant_vm_count(self.server_cfg)

        server_quota = {}
        server_quota['network'] = self.server_cfg['routers_per_user'] *\
            self.server_cfg['networks_per_router']
        server_quota['subnet'] = server_quota['network']
        server_quota['router'] = self.server_cfg['routers_per_user']
        if (self.server_cfg['use_floatingip']):
            # (1) Each VM has one floating IP
            # (2) Each Router has one external IP
            server_quota['floatingip'] = total_vm + server_quota['router']
            # (1) Each VM Floating IP takes up 1 port, total of $total_vm port(s)
            # (2) Each VM Fixed IP takes up 1 port, total of $total_vm port(s)
            # (3) Each Network has one router_interface (gateway), and one DHCP agent, total of
            #     server_quota['network'] * 2 port(s)
            # (4) Each Router has one external IP, takes up 1 port, total of
            #     server_quota['router'] port(s)
            server_quota['port'] = 2 * total_vm + 2 * server_quota['network'] +\
                server_quota['router']
        else:
            server_quota['floatingip'] = server_quota['router']
            server_quota['port'] = total_vm + 2 * server_quota['network'] + server_quota['router']
        server_quota['security_group'] = server_quota['network'] + 1
        server_quota['security_group_rule'] = server_quota['security_group'] * 100

        client_quota = {}
        total_vm = total_vm * self.server_cfg['number_tenants']
        client_quota['network'] = 1
        client_quota['subnet'] = 1
        client_quota['router'] = 1
        if (self.client_cfg['use_floatingip']):
            # (1) Each VM has one floating IP
            # (2) Each Router has one external IP, total of 1 router
            # (3) KB-Proxy node has one floating IP
            client_quota['floatingip'] = total_vm + 1 + 1
            # (1) Each VM Floating IP takes up 1 port, total of $total_vm port(s)
            # (2) Each VM Fixed IP takes up 1 port, total of $total_vm port(s)
            # (3) Each Network has one router_interface (gateway), and one DHCP agent, total of
            #     client_quota['network'] * 2 port(s)
            # (4) KB-Proxy node takes up 2 ports, one for fixed IP, one for floating IP
            # (5) Each Router has one external IP, takes up 1 port, total of 1 router/port
            client_quota['port'] = 2 * total_vm + 2 * client_quota['network'] + 2 + 1
        else:
            client_quota['floatingip'] = 1 + 1
            client_quota['port'] = total_vm + 2 * client_quota['network'] + 2 + 1
        if self.single_cloud:
            # Under single-cloud mode, the shared network is attached to every router in server
            # cloud, and each one takes up 1 port on client side.
            client_quota['port'] = client_quota['port'] + server_quota['router']
        client_quota['security_group'] = client_quota['network'] + 1
        client_quota['security_group_rule'] = client_quota['security_group'] * 100

        return [server_quota, client_quota]

    def calc_nova_quota(self):
        total_vm = self.get_tenant_vm_count(self.server_cfg)
        server_quota = {}
        server_quota['instances'] = total_vm
        server_quota['cores'] = total_vm * self.server_cfg['flavor']['vcpus']
        server_quota['ram'] = total_vm * self.server_cfg['flavor']['ram']

        client_quota = {}
        total_vm = total_vm * self.server_cfg['number_tenants']
        client_quota['instances'] = total_vm + 1
        client_quota['cores'] = total_vm * self.client_cfg['flavor']['vcpus'] + 1
        client_quota['ram'] = total_vm * self.client_cfg['flavor']['ram'] + 2048

        return [server_quota, client_quota]

    def calc_cinder_quota(self):
        total_vm = self.get_tenant_vm_count(self.server_cfg)
        server_quota = {}
        server_quota['gigabytes'] = total_vm * self.server_cfg['flavor']['disk']

        client_quota = {}
        total_vm = total_vm * self.server_cfg['number_tenants']
        client_quota['gigabytes'] = total_vm * self.client_cfg['flavor']['disk'] + 20

        return [server_quota, client_quota]

    def calc_tenant_quota(self):
        quota_dict = {'server': {}, 'client': {}}
        nova_quota = self.calc_nova_quota()
        neutron_quota = self.calc_neutron_quota()
        cinder_quota = self.calc_cinder_quota()
        for idx, val in enumerate(['server', 'client']):
            quota_dict[val]['nova'] = nova_quota[idx]
            quota_dict[val]['neutron'] = neutron_quota[idx]
            quota_dict[val]['cinder'] = cinder_quota[idx]

        return quota_dict

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

    cli_opts = [
        cfg.StrOpt("config",
                   short="c",
                   default=None,
                   help="Override default values with a config file"),
        cfg.StrOpt("topology",
                   short="t",
                   default=None,
                   help="Topology files for compute hosts"),
        cfg.StrOpt("tenants-list",
                   short="l",
                   default=None,
                   help="Existing tenant and user lists for reusing"),
        cfg.StrOpt("tested-rc",
                   default=None,
                   help="Tested cloud openrc credentials file"),
        cfg.StrOpt("testing-rc",
                   default=None,
                   help="Testing cloud openrc credentials file"),
        cfg.StrOpt("tested-passwd",
                   default=None,
                   help="Tested cloud password"),
        cfg.StrOpt("testing-passwd",
                   default=None,
                   help="Testing cloud password"),
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

    kb_config = KBConfig()
    kb_config.init_with_cli()

    image_check = check_and_upload_images(
        kb_config.cred_tested,
        kb_config.cred_testing,
        kb_config.server_cfg.image_name,
        kb_config.client_cfg.image_name)
    if not image_check:
        sys.exit(1)

    # The KloudBuster class is just a wrapper class
    # levarages tenant and user class for resource creations and deletion
    kloudbuster = KloudBuster(
        kb_config.cred_tested, kb_config.cred_testing,
        kb_config.server_cfg, kb_config.client_cfg,
        kb_config.topo_cfg, kb_config.tenants_list)
    kloudbuster.run()

    if CONF.json:
        '''Save results in JSON format file.'''
        LOG.info('Saving results in json file: ' + CONF.json + "...")
        with open(CONF.json, 'w') as jfp:
            json.dump(kloudbuster.final_result, jfp, indent=4, sort_keys=True)
