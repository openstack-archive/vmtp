# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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
#

import argparse
import datetime
import hashlib
import json
import os
import pprint
import re
import sys
import traceback

import compute
import credentials
import iperf_tool
import network
import nuttcp_tool
import pns_mongo
import sshutils

import configure
from glanceclient.v2 import client as glanceclient
from keystoneclient.v2_0 import client as keystoneclient
from neutronclient.v2_0 import client as neutronclient
from novaclient.client import Client
from novaclient.exceptions import ClientException

__version__ = '2.1.0'

from perf_instance import PerfInstance as PerfInstance

def get_vmtp_absolute_path_for_file(file_name):
    '''
    Return the filename in absolute path for any file
    passed as relative path to the vmtp directory
    '''
    if os.path.isabs(__file__):
        abs_file_path = os.path.join(__file__.split("vmtp.py")[0],
                                     file_name)
    else:
        abs_file = os.path.abspath(__file__)
        abs_file_path = os.path.join(abs_file.split("vmtp.py")[0],
                                     file_name)

    return abs_file_path


def normalize_paths(cfg):
    '''
    Normalize the various paths to config files, tools, ssh priv and pub key
    files.
    If a relative path is entered:
    - the key pair file names are relative to the current directory
    - the perftool path is relative to vmtp itself
    '''
    if cfg.public_key_file:
        cfg.public_key_file = os.path.abspath(os.path.expanduser(cfg.public_key_file))
    if cfg.private_key_file:
        cfg.private_key_file = os.path.expanduser(os.path.expanduser(cfg.private_key_file))
    if cfg.perf_tool_path:
        cfg.perf_tool_path = get_vmtp_absolute_path_for_file(cfg.perf_tool_path)

class FlowPrinter(object):

    def __init__(self):
        self.flow_num = 0

    def print_desc(self, desc):
        self.flow_num += 1
        print "=" * 60
        print('Flow %d: %s' % (self.flow_num, desc))

class ResultsCollector(object):

    def __init__(self):
        self.results = {'flows': []}
        self.results['date'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.results['args'] = ' '.join(sys.argv)
        self.results['version'] = __version__
        self.ppr = pprint.PrettyPrinter(indent=4, width=100)

    def add_property(self, name, value):
        self.results[name] = value

    def add_properties(self, properties):
        self.results.update(properties)

    def add_flow_result(self, flow_res):
        self.results['flows'].append(flow_res)
        self.ppr.pprint(flow_res)

    def display(self):
        self.ppr.pprint(self.results)

    def pprint(self, res):
        self.ppr.pprint(res)

    def get_controller_info(self, cfg, net):
        if cfg.ctrl_host_access:
            print 'Fetching OpenStack deployment details...'
            sshcon = sshutils.SSH(cfg.ctrl_host_access,
                                  connect_retry_count=cfg.ssh_retry_count)
            if sshcon is not None:
                self.results['distro'] = sshcon.get_host_os_version()
                self.results['openstack_version'] = sshcon.check_openstack_version()
                self.results['cpu_info'] = sshcon.get_cpu_info()
                if net and 'l2agent_type' in self.results and \
                   'encapsulation' in self.results:
                    self.results['nic_name'] = sshcon.get_nic_name(
                        self.results['l2agent_type'], self.results['encapsulation'],
                        net.internal_iface_dict)
                    self.results['l2agent_version'] = sshcon.get_l2agent_version(
                        self.results['l2agent_type'])
                else:
                    self.results['nic_name'] = "Unknown"
            else:
                print 'ERROR: Cannot connect to the controller node.'

    def get_result(self, key):
        if keystoneclient in self.results:
            return self.results[key]
        return None

    def mask_credentials(self):
        arguments = self.results['args']
        if not arguments:
            return

        arg_list = ['-p', '--host', '--external-host', '--controller-node']
        for keyword in arg_list:
            pattern = keyword + r'\s+[^\s]+'
            string = keyword + ' <MASKED>'
            arguments = re.sub(pattern, string, arguments)

        self.results['args'] = arguments

    def generate_runid(self):
        key = self.results['args'] + self.results['date'] + self.results['version']
        self.results['run_id'] = hashlib.md5(key).hexdigest()[:7]

    def save(self, cfg):
        '''Save results in json format file.'''
        print('Saving results in json file: ' + cfg.json_file + "...")
        with open(cfg.json_file, 'w') as jfp:
            json.dump(self.results, jfp, indent=4, sort_keys=True)

    def save_to_db(self, cfg):
        '''Save results to MongoDB database.'''
        print "Saving results to MongoDB database..."
        post_id = pns_mongo.\
            pns_add_test_result_to_mongod(cfg.vmtp_mongod_ip,
                                          cfg.vmtp_mongod_port,
                                          cfg.vmtp_db,
                                          cfg.vmtp_collection,
                                          self.results)
        if post_id is None:
            print "ERROR: Failed to add result to DB"

class VmtpException(Exception):
    pass

class VmtpTest(object):
    def __init__(self):
        '''
            1. Authenticate nova and neutron with keystone
            2. Create new client objects for neutron and nova
            3. Find external network
            4. Find or create router for external network
            5. Find or create internal mgmt and data networks
            6. Add internal mgmt network to router
            7. Import public key for ssh
            8. Create 2 VM instances on internal networks
            9. Create floating ips for VMs
            10. Associate floating ip with VMs
        '''
        self.server = None
        self.client = None
        self.net = None
        self.comp = None
        self.ping_status = None
        self.client_az_list = None
        self.sec_group = None
        self.image_instance = None
        self.flavor_type = None

    # Create an instance on a particular availability zone
    def create_instance(self, inst, az, int_net):
        self.assert_true(inst.create(self.image_instance,
                                     self.flavor_type,
                                     instance_access,
                                     int_net,
                                     az,
                                     int_net['name'],
                                     self.sec_group))

    def assert_true(self, cond):
        if not cond:
            raise VmtpException('Assert failure')

    def setup(self):
        # If we need to reuse existing vms just return without setup
        if not config.reuse_existing_vm:
            creds = cred.get_credentials()
            creds_nova = cred.get_nova_credentials_v2()
            # Create the nova and neutron instances
            nova_client = Client(**creds_nova)
            neutron = neutronclient.Client(**creds)

            self.comp = compute.Compute(nova_client, config)

            # Add the appropriate public key to openstack
            self.comp.init_key_pair(config.public_key_name, instance_access)

            self.image_instance = self.comp.find_image(config.image_name)
            if self.image_instance is None:
                if config.vm_image_url is not None:
                    print '%s: image for VM not found, uploading it ...' \
                        % (config.image_name)
                    keystone = keystoneclient.Client(**creds)
                    glance_endpoint = keystone.service_catalog.url_for(
                        service_type='image', endpoint_type='publicURL')
                    glance_client = glanceclient.Client(
                        glance_endpoint, token=keystone.auth_token)
                    self.comp.upload_image_via_url(
                        glance_client, config.image_name, config.vm_image_url)
                    self.image_instance = self.comp.find_image(config.image_name)
                else:
                    # Exit the pogram
                    print '%s: image to launch VM not found. ABORTING.' \
                        % (config.image_name)
                    sys.exit(1)

            self.assert_true(self.image_instance)
            print 'Found image %s to launch VM, will continue' % (config.image_name)
            self.flavor_type = self.comp.find_flavor(config.flavor_type)
            self.net = network.Network(neutron, config)

            rescol.add_property('l2agent_type', self.net.l2agent_type)
            print "OpenStack agent: " + self.net.l2agent_type
            try:
                network_type = self.net.vm_int_net[0]['provider:network_type']
                print "OpenStack network type: " + network_type
                rescol.add_property('encapsulation', network_type)
            except KeyError as exp:
                network_type = 'Unknown'
                print "Provider network type not found: ", str(exp)

        # Create a new security group for the test
        self.sec_group = self.comp.security_group_create()
        if not self.sec_group:
            raise VmtpException("Security group creation failed")
        if config.reuse_existing_vm:
            self.server.internal_ip = config.vm_server_internal_ip
            self.client.internal_ip = config.vm_client_internal_ip
            if config.vm_server_external_ip:
                self.server.ssh_access.host = config.vm_server_external_ip
            else:
                self.server.ssh_access.host = config.vm_server_internal_ip
            if config.vm_client_external_ip:
                self.client.ssh_access.host = config.vm_client_external_ip
            else:
                self.client.ssh_access.host = config.vm_client_internal_ip
            return

        # this is the standard way of running the test
        # NICs to be used for the VM
        if config.reuse_network_name:
            # VM needs to connect to existing management and new data network
            # Reset the management network name
            config.internal_network_name[0] = config.reuse_network_name
        else:
            # Make sure we have an external network and an external router
            self.assert_true(self.net.ext_net)
            self.assert_true(self.net.ext_router)
            self.assert_true(self.net.vm_int_net)

        # Get hosts for the availability zone to use
        # avail_list = self.comp.list_hypervisor(config.availability_zone)
        avail_list = self.comp.get_az_host_list()
        if not avail_list:
            sys.exit(5)

        # compute the list of client vm placements to run
        # the first host is always where the server runs
        server_az = avail_list[0]
        if len(avail_list) > 1:
            # 2 hosts are known
            if config.inter_node_only:
                # in this case we do not want the client to run on the same host
                # as the server
                avail_list.pop(0)
        self.client_az_list = avail_list

        self.server = PerfInstance(config.vm_name_server,
                                   config,
                                   self.comp,
                                   self.net,
                                   server=True)
        self.server.display('Creating server VM...')
        self.create_instance(self.server, server_az,
                             self.net.vm_int_net[0])

    # Test throughput for the case of the external host
    def ext_host_tp_test(self):
        client = PerfInstance('Host-' + config.ext_host.host + '-Client', config)
        if not client.setup_ssh(config.ext_host):
            client.display('SSH to ext host failed, check IP or make sure public key is configured')
        else:
            client.buginf('SSH connected')
            client.create()
            fpr.print_desc('External-VM (upload/download)')
            res = client.run_client('External-VM',
                                    self.server.ssh_access.host,
                                    self.server,
                                    bandwidth=config.vm_bandwidth,
                                    bidirectional=True)
            if res:
                rescol.add_flow_result(res)
            client.dispose()

    def add_location(self, label):
        '''Add a note to a label to specify same node or differemt node.'''
        # We can only tell if there is a host part in the az
        # e.g. 'nova:GG34-7'
        if ':' in self.client.az:
            if self.client.az == self.server.az:
                return label + ' (intra-node)'
            else:
                return label + ' (inter-node)'
        return label

    def create_flow_client(self, client_az, int_net):
        self.client = PerfInstance(config.vm_name_client, config,
                                   self.comp,
                                   self.net)
        self.create_instance(self.client, client_az, int_net)

    def measure_flow(self, label, target_ip):
        label = self.add_location(label)
        fpr.print_desc(label)

        # results for this flow as a dict
        perf_output = self.client.run_client(label, target_ip,
                                             self.server,
                                             bandwidth=config.vm_bandwidth,
                                             az_to=self.server.az)
        if opts.stop_on_error:
            # check if there is any error in the results
            results_list = perf_output['results']
            for res_dict in results_list:
                if 'error' in res_dict:
                    print('Stopping execution on error, cleanup all VMs/networks manually')
                    rescol.pprint(perf_output)
                    sys.exit(2)

        rescol.add_flow_result(perf_output)

    def measure_vm_flows(self):
        # scenarios need to be tested for both inter and intra node
        # 1. VM to VM on same data network
        # 2. VM to VM on seperate networks fixed-fixed
        # 3. VM to VM on seperate networks floating-floating

        # we should have 1 or 2 AZ to use (intra and inter-node)
        for client_az in self.client_az_list:
            self.create_flow_client(client_az, self.net.vm_int_net[0])
            self.measure_flow("VM to VM same network fixed IP",
                              self.server.internal_ip)
            self.client.dispose()
            self.client = None
            if not config.reuse_network_name:
                # Different network
                self.create_flow_client(client_az, self.net.vm_int_net[1])

                self.measure_flow("VM to VM different network fixed IP",
                                  self.server.internal_ip)
                if not config.ipv6_mode:
                    self.measure_flow("VM to VM different network floating IP",
                                      self.server.ssh_access.host)

                self.client.dispose()
                self.client = None

        # If external network is specified run that case
        if config.ext_host:
            self.ext_host_tp_test()

    def teardown(self):
        '''
            Clean up the floating ip and VMs
        '''
        print '---- Cleanup ----'
        if self.server:
            self.server.dispose()
        if self.client:
            self.client.dispose()
        if not config.reuse_existing_vm and self.net:
            self.net.dispose()
        # Remove the public key
        if self.comp:
            self.comp.remove_public_key(config.public_key_name)
        # Finally remove the security group
        try:
            if self.comp:
                self.comp.security_group_delete(self.sec_group)
        except ClientException:
            # May throw novaclient.exceptions.BadRequest if in use
            print('Security group in use: not deleted')

    def run(self):
        error_flag = False

        try:
            self.setup()
            self.measure_vm_flows()
        except KeyboardInterrupt:
            traceback.format_exc()
        except (VmtpException, sshutils.SSHError, ClientException, Exception):
            print 'print_exc:'
            traceback.print_exc()
            error_flag = True

        if opts.stop_on_error and error_flag:
            print('Stopping execution on error, cleanup all VMs/networks manually')
            sys.exit(2)
        else:
            self.teardown()

def test_native_tp(nhosts, ifname):
    fpr.print_desc('Native Host to Host throughput')
    server_host = nhosts[0]
    server = PerfInstance('Host-' + server_host.host + '-Server', config, server=True)

    if not server.setup_ssh(server_host):
        server.display('SSH failed, check IP or make sure public key is configured')
    else:
        server.display('SSH connected')
        server.create()
        # if inter-node-only requested we avoid running the client on the
        # same node as the server - but only if there is at least another
        # IP provided
        if config.inter_node_only and len(nhosts) > 1:
            # remove the first element of the list
            nhosts.pop(0)
        # IP address clients should connect to, check if the user
        # has passed a server listen interface name
        if ifname:
            # use the IP address configured on given interface
            server_ip = server.get_interface_ip(ifname)
            if not server_ip:
                print('Error: cannot get IP address for interface ' + ifname)
            else:
                server.display('Clients will use server IP address %s (%s)' %
                               (server_ip, ifname))
        else:
            # use same as ssh IP
            server_ip = server_host.host

        if server_ip:
            # start client side, 1 per host provided
            for client_host in nhosts:
                client = PerfInstance('Host-' + client_host.host + '-Client', config)
                if not client.setup_ssh(client_host):
                    client.display('SSH failed, check IP or make sure public key is configured')
                else:
                    client.buginf('SSH connected')
                    client.create()
                    res = client.run_client('Native host-host',
                                            server_ip,
                                            server,
                                            bandwidth=config.vm_bandwidth)
                    rescol.add_flow_result(res)
                client.dispose()
    server.dispose()

def _get_ssh_access(opt_name, opt_value):
    '''Allocate a HostSshAccess instance to the option value
    Check that a password is provided or the key pair in the config file
    is valid.
    If invalid exit with proper error message
    '''
    if not opt_value:
        return None

    host_access = sshutils.SSHAccess(opt_value)
    host_access.private_key_file = config.private_key_file
    host_access.public_key_file = config.public_key_file
    if host_access.error:
        print'Error for --' + (opt_name + ':' + host_access.error)
        sys.exit(2)
    return host_access

def _merge_config(cfg_file, source_config, required=False):
    '''
    returns the merged config or exits if the file does not exist and is required
    '''
    dest_config = source_config

    fullname = os.path.expanduser(cfg_file)
    if os.path.isfile(fullname):
        print('Loading ' + fullname + '...')
        try:
            alt_config = configure.Configuration.from_file(fullname).configure()
            dest_config = source_config.merge(alt_config)

        except configure.ConfigurationError:
            # this is in most cases when the config file passed is empty
            # configure.ConfigurationError: unconfigured
            # in case of syntax error, another exception is thrown:
            # TypeError: string indices must be integers, not str
            pass
    elif required:
        print('Error: configration file %s does not exist' % (fullname))
        sys.exit(1)
    return dest_config

def get_controller_info(ssh_access, net, res_col):
    if not ssh_access:
        return
    print 'Fetching OpenStack deployment details...'
    sshcon = sshutils.SSH(ssh_access,
                          connect_retry_count=config.ssh_retry_count)
    if sshcon is None:
        print 'ERROR: Cannot connect to the controller node'
        return
    res = {}
    res['distro'] = sshcon.get_host_os_version()
    res['openstack_version'] = sshcon.check_openstack_version()
    res['cpu_info'] = sshcon.get_cpu_info()
    if net:
        l2type = res_col.get_result('l2agent_type')
        encap = res_col.get_result('encapsulation')
        if l2type:
            if encap:
                res['nic_name'] = sshcon.get_nic_name(l2type, encap,
                                                      net.internal_iface_dict)
            res['l2agent_version'] = sshcon.get_l2agent_version(l2type)
    # print results
    res_col.pprint(res)
    res_col.add_properties(res)


if __name__ == '__main__':

    fpr = FlowPrinter()
    rescol = ResultsCollector()

    parser = argparse.ArgumentParser(description='OpenStack VM Throughput V' + __version__)

    parser.add_argument('-c', '--config', dest='config',
                        action='store',
                        help='override default values with a config file',
                        metavar='<config_file>')

    parser.add_argument('-r', '--rc', dest='rc',
                        action='store',
                        help='source OpenStack credentials from rc file',
                        metavar='<openrc_file>')

    parser.add_argument('-m', '--monitor', dest='monitor',
                        action='store',
                        help='Enable CPU monitoring (requires Ganglia)',
                        metavar='<gmond_ip>[:<port>]')

    parser.add_argument('-p', '--password', dest='pwd',
                        action='store',
                        help='OpenStack password',
                        metavar='<password>')

    parser.add_argument('-t', '--time', dest='time',
                        action='store',
                        help='throughput test duration in seconds (default 10 sec)',
                        metavar='<time>')

    parser.add_argument('--host', dest='hosts',
                        action='append',
                        help='native host throughput (password or public key required)',
                        metavar='<user>@<host_ssh_ip>[:<password>:<server-listen-if-name>]')

    parser.add_argument('--external-host', dest='ext_host',
                        action='store',
                        help='external-VM throughput (password or public key required)',
                        metavar='<user>@<host_ssh_ip>[:password>]')

    parser.add_argument('--controller-node', dest='controller_node',
                        action='store',
                        help='controller node ssh (password or public key required)',
                        metavar='<user>@<host_ssh_ip>[:<password>]')

    parser.add_argument('--mongod-server', dest='mongod_server',
                        action='store',
                        help='provide mongoDB server IP to store results',
                        metavar='<server ip>')

    parser.add_argument('--json', dest='json',
                        action='store',
                        help='store results in json format file',
                        metavar='<file>')

    parser.add_argument('--tp-tool', dest='tp_tool',
                        action='store',
                        default='nuttcp',
                        help='transport perf tool to use (default=nuttcp)',
                        metavar='<nuttcp|iperf>')

    # note there is a bug in argparse that causes an AssertionError
    # when the metavar is set to '[<az>:]<hostname>', hence had to insert a space
    parser.add_argument('--hypervisor', dest='hypervisors',
                        action='append',
                        help='hypervisor to use (1 per arg, up to 2 args)',
                        metavar='[<az>:] <hostname>')

    parser.add_argument('--inter-node-only', dest='inter_node_only',
                        default=False,
                        action='store_true',
                        help='only measure inter-node')

    parser.add_argument('--protocols', dest='protocols',
                        action='store',
                        default='TUI',
                        help='protocols T(TCP), U(UDP), I(ICMP) - default=TUI (all)',
                        metavar='<T|U|I>')

    parser.add_argument('--bandwidth', dest='vm_bandwidth',
                        action='store',
                        default=0,
                        help='the bandwidth limit for TCP/UDP flows in K/M/Gbps, '
                             'e.g. 128K/32M/5G. (default=no limit) ',
                        metavar='<bandwidth>')

    parser.add_argument('--tcpbuf', dest='tcp_pkt_sizes',
                        action='store',
                        default=0,
                        help='list of buffer length when transmitting over TCP in Bytes, '
                             'e.g. --tcpbuf 8192,65536. (default=65536)',
                        metavar='<tcp_pkt_size1,...>')

    parser.add_argument('--udpbuf', dest='udp_pkt_sizes',
                        action='store',
                        default=0,
                        help='list of buffer length when transmitting over UDP in Bytes, '
                             'e.g. --udpbuf 128,2048. (default=128,1024,8192)',
                        metavar='<udp_pkt_size1,...>')

    parser.add_argument('--no-env', dest='no_env',
                        default=False,
                        action='store_true',
                        help='do not read env variables')

    parser.add_argument('--vnic-type', dest='vnic_type',
                        default=None,
                        action='store',
                        help='binding vnic type for test VMs',
                        metavar='<direct|macvtap|normal>')

    parser.add_argument('-d', '--debug', dest='debug',
                        default=False,
                        action='store_true',
                        help='debug flag (very verbose)')

    parser.add_argument('-v', '--version', dest='version',
                        default=False,
                        action='store_true',
                        help='print version of this script and exit')

    parser.add_argument('--stop-on-error', dest='stop_on_error',
                        default=False,
                        action='store_true',
                        help='Stop and keep everything as-is on error (must cleanup manually)')

    parser.add_argument('--vm-image-url', dest='vm_image_url',
                        action='store',
                        help='URL to a Linux image in qcow2 format that can be downloaded from',
                        metavar='<url_to_image>')

    parser.add_argument('--test-description', dest='test_description',
                        action='store',
                        help='The test description to be stored in JSON or MongoDB',
                        metavar='<test_description>')


    (opts, args) = parser.parse_known_args()

    default_cfg_file = get_vmtp_absolute_path_for_file("cfg.default.yaml")

    # read the default configuration file and possibly an override config file
    # the precedence order is as follows:
    # $HOME/.vmtp.yaml if exists
    # -c <file> from command line if provided
    # cfg.default.yaml
    config = configure.Configuration.from_file(default_cfg_file).configure()
    config = _merge_config('~/.vmtp.yaml', config)

    if opts.config:
        config = _merge_config(opts.config, config, required=True)

    if opts.version:
        print('Version ' + __version__)
        sys.exit(0)

    # debug flag
    config.debug = opts.debug
    config.inter_node_only = opts.inter_node_only

    if config.public_key_file and not os.path.isfile(config.public_key_file):
        print('Warning: invalid public_key_file:' + config.public_key_file)
        config.public_key_file = None
    if config.private_key_file and not os.path.isfile(config.private_key_file):
        print('Warning: invalid private_key_file:' + config.private_key_file)
        config.private_key_file = None

    # direct: use SR-IOV ports for all the test VMs
    if opts.vnic_type not in [None, 'direct', 'macvtap', 'normal']:
        print('Invalid vnic-type: ' + opts.vnic_type)
        sys.exit(1)
    config.vnic_type = opts.vnic_type

    config.hypervisors = opts.hypervisors

    # time to run each perf test in seconds
    if opts.time:
        config.time = int(opts.time)
    else:
        config.time = 10

    if opts.json:
        config.json_file = opts.json
    else:
        config.json_file = None

    # Initialize the external host access
    config.ext_host = _get_ssh_access('external-host', opts.ext_host)

    # This is a template host access that will be used for all instances
    # (the only specific field specific to each instance is the host IP)
    # For test VM access, we never use password and always need a key pair
    instance_access = sshutils.SSHAccess()
    instance_access.username = config.ssh_vm_username
    # if the configuration does not have a
    # key pair specified, we check if the user has a personal key pair
    # if no key pair is configured or usable, a temporary key pair will be created
    if config.public_key_file and config.private_key_file:
        instance_access.public_key_file = config.public_key_file
        instance_access.private_key_file = config.private_key_file
    else:
        pub_key = os.path.expanduser('~/.ssh/id_rsa.pub')
        priv_key = os.path.expanduser('~/.ssh/id_rsa')
        if os.path.isfile(pub_key) and os.path.isfile(priv_key):
            instance_access.public_key_file = pub_key
            instance_access.private_key_file = priv_key

    if opts.debug and instance_access.public_key_file:
        print('VM public key:  ' + instance_access.public_key_file)
        print('VM private key: ' + instance_access.private_key_file)


    ###################################################
    # VM Image URL
    ###################################################
    if opts.vm_image_url:
        config.vm_image_url = opts.vm_image_url

    ###################################################
    # Test Description
    ###################################################
    if opts.test_description:
        rescol.add_property('test_description', opts.test_description)

    ###################################################
    # MongoDB Server connection info.
    ###################################################
    if opts.mongod_server:
        config.vmtp_mongod_ip = opts.mongod_server
    else:
        config.vmtp_mongod_ip = None

    if 'vmtp_mongod_port' not in config:
        # Set MongoDB default port if not set.
        config.vmtp_mongod_port = 27017

    # the bandwidth limit for VMs
    if opts.vm_bandwidth:
        opts.vm_bandwidth = opts.vm_bandwidth.upper().strip()
        ex_unit = 'KMG'.find(opts.vm_bandwidth[-1])
        try:
            if ex_unit == -1:
                raise ValueError
            val = int(opts.vm_bandwidth[0:-1])
        except ValueError:
            print 'Invalid --bandwidth parameter. A valid input must '\
                  'specify only one unit (K|M|G).'
            sys.exit(1)
        config.vm_bandwidth = int(val * (10 ** (ex_unit * 3)))

    # the pkt size for TCP and UDP
    if opts.tcp_pkt_sizes:
        try:
            config.tcp_pkt_sizes = opts.tcp_pkt_sizes.split(',')
            for i in xrange(len(config.tcp_pkt_sizes)):
                config.tcp_pkt_sizes[i] = int(config.tcp_pkt_sizes[i])
        except ValueError:
            print 'Invalid --tcpbuf parameter. A valid input must be '\
                  'integers seperated by comma.'
            sys.exit(1)

    if opts.udp_pkt_sizes:
        try:
            config.udp_pkt_sizes = opts.udp_pkt_sizes.split(',')
            for i in xrange(len(config.udp_pkt_sizes)):
                config.udp_pkt_sizes[i] = int(config.udp_pkt_sizes[i])
        except ValueError:
            print 'Invalid --udpbuf parameter. A valid input must be '\
                  'integers seperated by comma.'
            sys.exit(1)

    #####################################################
    # Set Ganglia server ip and port if the monitoring (-m)
    # option is enabled.
    #####################################################
    config.gmond_svr_ip = None
    config.gmond_svr_port = None
    if opts.monitor:
        # Add the default gmond port if not present
        if ':' not in opts.monitor:
            opts.monitor += ':8649'

        mobj = re.match(r'(\d+\.\d+\.\d+\.\d+):(\d+)', opts.monitor)
        if mobj:
            config.gmond_svr_ip = mobj.group(1)
            config.gmond_svr_port = mobj.group(2)
            print "Ganglia monitoring enabled (%s:%s)" % \
                  (config.gmond_svr_ip, config.gmond_svr_port)
            config.time = 30

        else:
            print 'Invalid --monitor syntax: ' + opts.monitor

    ###################################################
    # Once we parse the config files, normalize
    # the paths so that all paths are absolute paths.
    ###################################################
    normalize_paths(config)

    # Check the tp-tool name
    config.protocols = opts.protocols.upper()
    if 'T' in config.protocols or 'U' in config.protocols:
        if opts.tp_tool.lower() == 'nuttcp':
            config.tp_tool = nuttcp_tool.NuttcpTool
        elif opts.tp_tool.lower() == 'iperf':
            config.tp_tool = iperf_tool.IperfTool
        else:
            print 'Invalid transport tool: ' + opts.tp_tool
            sys.exit(1)
    else:
        config.tp_tool = None

    # 3 forms
    # A list of 0 to 2 HostSshAccess elements
    if opts.hosts:
        native_hosts = []
        if_name = None
        for host in opts.hosts:
            # decode and extract the trailing if name first
            # there is an if name if there are at least 2 ':' in the argument
            # e.g. "root@1.1.1.1:secret:eth0"
            if host.count(':') >= 2:
                last_column_index = host.rfind(':')
                # can be empty
                last_arg = host[last_column_index + 1:]
                if not if_name and last_arg:
                    if_name = last_arg
                host = host[:last_column_index]
            native_hosts.append(_get_ssh_access('host', host))
        test_native_tp(native_hosts, if_name)

    cred = credentials.Credentials(opts.rc, opts.pwd, opts.no_env)

    # replace all command line arguments (after the prog name) with
    # those args that have not been parsed by this parser so that the
    # unit test parser is not bothered by local arguments
    sys.argv[1:] = args
    vmtp_net = None
    if cred.rc_auth_url:
        if opts.debug:
            print 'Using ' + cred.rc_auth_url
        rescol.add_property('auth_url', cred.rc_auth_url)
        vmtp = VmtpTest()
        vmtp.run()
        vmtp_net = vmtp.net

    # Retrieve controller information if requested
    # controller node ssh access to collect metadata for the run.
    ctrl_host_access = _get_ssh_access('controller-node', opts.controller_node)
    get_controller_info(ctrl_host_access, vmtp_net, rescol)

    # If saving the results to JSON or MongoDB, get additional details:
    if config.json_file or config.vmtp_mongod_ip:
        rescol.mask_credentials()
        rescol.generate_runid()

    if config.json_file:
        rescol.save(config)

    if config.vmtp_mongod_ip:
        rescol.save_to_db(config)
