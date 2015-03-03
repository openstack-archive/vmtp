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
import json
import os
import pprint
import re
import socket
import stat
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

__version__ = '2.0.1'

from perf_instance import PerfInstance as PerfInstance

# Check IPv4 address syntax - not completely fool proof but will catch
# some invalid formats
def is_ipv4(address):
    try:
        socket.inet_aton(address)
    except socket.error:
        return False
    return True

def get_absolute_path_for_file(file_name):
    '''
    Return the filename in absolute path for any file
    passed as relateive path.
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
    '''
    cfg.public_key_file = get_absolute_path_for_file(cfg.public_key_file)
    cfg.private_key_file = get_absolute_path_for_file(cfg.private_key_file)
    cfg.perf_tool_path = get_absolute_path_for_file(cfg.perf_tool_path)

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

    def add_flow_result(self, flow_res):
        self.results['flows'].append(flow_res)
        self.ppr.pprint(flow_res)

    def display(self):
        self.ppr.pprint(self.results)

    def pprint(self, res):
        self.ppr.pprint(res)

    def get_controller_info(self, cfg):
        if cfg.ctrl_username and cfg.ctrl_host:
            print 'Fetching OpenStack deployment details...'
            if cfg.ctrl_password:
                sshcon = sshutils.SSH(cfg.ctrl_username,
                                      cfg.ctrl_host,
                                      password=cfg.ctrl_password)
            else:
                sshcon = sshutils.SSH(cfg.ctrl_username,
                                      cfg.ctrl_host,
                                      key_filename=cfg.private_key_file,
                                      connect_retry_count=cfg.ssh_retry_count)
            if sshcon is not None:
                self.results['distro'] = sshcon.get_host_os_version()
                self.results['openstack_version'] = sshcon.check_openstack_version()
                self.results['cpu_info'] = sshcon.get_cpu_info()
                if 'agent_type' in self.results and 'encapsulation' in self.results:
                    self.results['nic_name'] = sshcon.get_nic_name(
                        self.results['agent_type'], self.results['encapsulation'])
                else:
                    self.results['nic_name'] = "Unknown"
            else:
                print 'ERROR: Cannot connect to the controller node.'

    def save(self, cfg):
        '''Save results in json format file.'''
        print('Saving results in json file: ' + cfg.json_file + "...")
        with open(cfg.json_file, 'w') as jfp:
            json.dump(self.results, jfp, indent=4, sort_keys=True)

    def save_to_db(self, cfg):
        '''Save results to MongoDB database.'''
        print "Saving results to MongoDB database..."
        post_id = pns_mongo.\
            pns_add_test_result_to_mongod(cfg.pns_mongod_ip,
                                          cfg.pns_mongod_port,
                                          cfg.pns_db,
                                          cfg.pns_collection,
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
        self.agent_type = None

    # Create an instance on a particular availability zone
    def create_instance(self, inst, az, int_net):
        nics = [{'net-id': int_net['id']}]
        self.assert_true(inst.create(self.image_instance,
                                     self.flavor_type,
                                     config.public_key_name,
                                     nics,
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
            # Add the script public key to openstack
            self.comp.add_public_key(config.public_key_name,
                                     config.public_key_file)

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

            rescol.add_property('agent_type', self.net.agent_type)
            print "OpenStack agent: " + self.net.agent_type
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
                self.server.ssh_ip = config.vm_server_external_ip
            else:
                self.server.ssh_ip = config.vm_server_internal_ip
            if config.vm_client_external_ip:
                self.client.ssh_ip = config.vm_client_external_ip
            else:
                self.client.ssh_ip = config.vm_client_internal_ip
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
        client = PerfInstance('Host-' + ext_host_list[1] + '-Client', config)
        if not client.setup_ssh(ext_host_list[1], ext_host_list[0]):
            client.display('SSH failed, check IP or make sure public key is configured')
        else:
            client.buginf('SSH connected')
            client.create()
            fpr.print_desc('External-VM (upload/download)')
            res = client.run_client('External-VM',
                                    self.server.ssh_ip,
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
                                      self.server.ssh_ip)

                self.client.dispose()
                self.client = None

        # If external network is specified run that case
        if ext_host_list[0]:
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
        except (VmtpException, sshutils.SSHError, ClientException):
            traceback.format_exc()
            error_flag = True

        if opts.stop_on_error and error_flag:
            print('Stopping execution on error, cleanup all VMs/networks manually')
            sys.exit(2)
        else:
            self.teardown()

def test_native_tp(nhosts):
    fpr.print_desc('Native Host to Host throughput')
    server_host = nhosts[0]
    server = PerfInstance('Host-' + server_host[1] + '-Server', config, server=True)

    if not server.setup_ssh(server_host[1], server_host[0]):
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
        if len(server_host) == 3:
            # use the IP address configured on given interface
            server_ip = server.get_interface_ip(server_host[2])
            if not server_ip:
                print('Error: cannot get IP address for interface ' + server_host[2])
            else:
                server.display('Clients will use server IP address %s (%s)' %
                               (server_ip, server_host[2]))
        else:
            # use same as ssh IP
            server_ip = server_host[1]

        if server_ip:
            # start client side, 1 per host provided
            for client_host in nhosts:
                client = PerfInstance('Host-' + client_host[1] + '-Client', config)
                if not client.setup_ssh(client_host[1], client_host[0]):
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

def extract_user_host_pwd(user_host_pwd):
    '''
        splits user@host[:pwd] into a 3 element tuple
        'hugo@1.1.1.1:secret' -> ('hugo', '1.1.1.1', 'secret')
        'huggy@2.2.2.2' -> ('huggy', '2.2.2.2', None)
        None ->(None, None, None)
        Examples of fatal errors (will call exit):
        'hutch@q.1.1.1' (invalid IP)
        '@3.3.3.3' (missing username)
        'hiro@' or 'buggy' (missing host IP)
    '''
    if not user_host_pwd:
        return (None, None, None)
    match = re.search(r'^([^@]+)@([0-9\.]+):?(.*)$', user_host_pwd)
    if not match:
        print('Invalid argument: ' + user_host_pwd)
        sys.exit(3)
    if not is_ipv4(match.group(2)):
        print 'Invalid IPv4 address ' + match.group(2)
        sys.exit(4)
    return match.groups()

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
                        help='native host throughput (targets requires ssh key)',
                        metavar='<user>@<host_ssh_ip>[:<server-listen-if-name>]')

    parser.add_argument('--external-host', dest='ext_host',
                        action='store',
                        help='external-VM throughput (host requires public key if no password)',
                        metavar='<user>@<host_ssh_ip>[:password>]')

    parser.add_argument('--controller-node', dest='controller_node',
                        action='store',
                        help='controller node ssh (host requires public key if no password)',
                        metavar='<user>@<host_ssh_ip>[:<password>]')

    parser.add_argument('--mongod_server', dest='mongod_server',
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
                        metavar='nuttcp|iperf')

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
                        metavar='T|U|I')

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

    parser.add_argument('--vm_image_url', dest='vm_image_url',
                        action='store',
                        help='URL to a Linux image in qcow2 format that can be downloaded from',
                        metavar='<url_to_image>')


    (opts, args) = parser.parse_known_args()

    default_cfg_file = get_absolute_path_for_file("cfg.default.yaml")

    # read the default configuration file and possibly an override config file
    config = configure.Configuration.from_file(default_cfg_file).configure()
    if opts.config:
        alt_config = configure.Configuration.from_file(opts.config).configure()
        config = config.merge(alt_config)

    if opts.version:
        print('Version ' + __version__)
        sys.exit(0)

    # debug flag
    config.debug = opts.debug
    config.inter_node_only = opts.inter_node_only

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

    ###################################################
    # controller node ssh access to collect metadata for
    # the run.
    ###################################################
    (config.ctrl_username, config.ctrl_host, config.ctrl_password) = \
        extract_user_host_pwd(opts.controller_node)
    # Add the external host info to a list
    ext_host_list = list(extract_user_host_pwd(opts.ext_host))

    ###################################################
    # VM Image URL
    ###################################################
    if opts.vm_image_url:
        config.vm_image_url = opts.vm_image_url
    else:
        config.vm_image_url = None

    ###################################################
    # MongoDB Server connection info.
    ###################################################
    if opts.mongod_server:
        config.pns_mongod_ip = opts.mongod_server
    else:
        config.pns_mongod_ip = None

    if 'pns_mongod_port' not in config:
        # Set MongoDB default port if not set.
        config.pns_mongod_port = 27017

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

    # first chmod the local private key since git does not keep the permission
    # as this is required by ssh/scp
    os.chmod(config.private_key_file, stat.S_IRUSR | stat.S_IWUSR)

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

    # 3 forms are accepted:
    # --host 1.1.1.1
    # --host root@1.1.1.1
    # --host root@1.1.1.1:eth0
    # A list of 0 to 2 lists where each nested list is
    # a list of 1 to 3 elements. e.g.:
    # [['ubuntu','1.1.1.1'],['root', 2.2.2.2]]
    # [['ubuntu','1.1.1.1', 'eth0'],['root', 2.2.2.2]]
    # when not provided the default user is 'root'
    if opts.hosts:
        native_hosts = []
        for host in opts.hosts:
            # split on '@' first
            elem_list = host.split("@")
            if len(elem_list) == 1:
                elem_list.insert(0, 'root')
            # split out the if name if present
            # ['root':'1.1.1.1:eth0'] becomes ['root':'1.1.1.1', 'eth0']
            if ':' in elem_list[1]:
                elem_list.extend(elem_list.pop().split(':'))
            if not is_ipv4(elem_list[1]):
                print 'Invalid IPv4 address ' + elem_list[1]
                sys.exit(1)
            native_hosts.append(elem_list)
        test_native_tp(native_hosts)

    cred = credentials.Credentials(opts.rc, opts.pwd, opts.no_env)

    # replace all command line arguments (after the prog name) with
    # those args that have not been parsed by this parser so that the
    # unit test parser is not bothered by local arguments
    sys.argv[1:] = args

    if cred.rc_auth_url:
        if opts.debug:
            print 'Using ' + cred.rc_auth_url
        rescol.add_property('auth_url', cred.rc_auth_url)
        vmtp = VmtpTest()
        vmtp.run()

    # If saving the results to JSON or MongoDB, get additional details:
    if config.json_file or config.pns_mongod_ip:
        rescol.get_controller_info(config)

    if config.json_file:
        rescol.save(config)

    if config.pns_mongod_ip:
        rescol.save_to_db(config)
