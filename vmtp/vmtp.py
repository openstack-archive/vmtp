#!/usr/bin/env python
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
import logging
import os
import pprint
import re
import sys
import traceback

from __init__ import __version__
import compute
from config import config_load
from config import config_loads
import credentials
from glanceclient.v1 import client as glanceclient
import iperf_tool
from keystoneclient.v2_0 import client as keystoneclient
import network
from neutronclient.v2_0 import client as neutronclient
from novaclient.client import Client
from novaclient.exceptions import ClientException
import nuttcp_tool
from perf_instance import PerfInstance as PerfInstance
from pkg_resources import resource_string
import pns_mongo
from prettytable import PrettyTable
import sshutils

flow_num = 0
class FlowPrinter(object):
    @staticmethod
    def print_desc(desc):
        global flow_num
        flow_num = flow_num + 1
        print "=" * 60
        print('Flow %d: %s' % (flow_num, desc))

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
    def __init__(self, config, cred, rescol):
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
        self.instance_access = None
        self.rescol = rescol
        self.config = config
        self.cred = cred

    # Create an instance on a particular availability zone
    def create_instance(self, inst, az, int_net):
        self.assert_true(inst.create(self.image_instance,
                                     self.flavor_type,
                                     self.instance_access,
                                     int_net,
                                     az,
                                     int_net['name'],
                                     self.sec_group))

    def assert_true(self, cond):
        if not cond:
            raise VmtpException('Assert failure')

    def setup(self):
        # This is a template host access that will be used for all instances
        # (the only specific field specific to each instance is the host IP)
        # For test VM access, we never use password and always need a key pair
        self.instance_access = sshutils.SSHAccess()
        self.instance_access.username = self.config.ssh_vm_username
        # if the configuration does not have a
        # key pair specified, we check if the user has a personal key pair
        # if no key pair is configured or usable, a temporary key pair will be created
        if self.config.public_key_file and self.config.private_key_file:
            self.instance_access.public_key_file = self.config.public_key_file
            self.instance_access.private_key_file = self.config.private_key_file
        else:
            pub_key = os.path.expanduser('~/.ssh/id_rsa.pub')
            priv_key = os.path.expanduser('~/.ssh/id_rsa')
            if os.path.isfile(pub_key) and os.path.isfile(priv_key):
                self.instance_access.public_key_file = pub_key
                self.instance_access.private_key_file = priv_key
            else:
                print('Error: Default keypair ~/.ssh/id_rsa[.pub] is not existed. Please '
                      'either create one in your home directory, or specify your keypair '
                      'information in the config file before running VMTP.')
                sys.exit(1)

        if self.config.debug and self.instance_access.public_key_file:
            print('VM public key:  ' + self.instance_access.public_key_file)
            print('VM private key: ' + self.instance_access.private_key_file)

        # If we need to reuse existing vms just return without setup
        if not self.config.reuse_existing_vm:
            creds = self.cred.get_credentials()
            creds_nova = self.cred.get_nova_credentials_v2()
            # Create the nova and neutron instances
            nova_client = Client(**creds_nova)
            neutron = neutronclient.Client(**creds)

            self.comp = compute.Compute(nova_client, self.config)

            # Add the appropriate public key to openstack
            self.comp.init_key_pair(self.config.public_key_name, self.instance_access)

            self.image_instance = self.comp.find_image(self.config.image_name)
            if self.image_instance is None:
                if self.config.vm_image_url != "":
                    print '%s: image for VM not found, trying to upload it ...' \
                        % (self.config.image_name)
                    keystone = keystoneclient.Client(**creds)
                    glance_endpoint = keystone.service_catalog.url_for(
                        service_type='image', endpoint_type='publicURL')
                    glance_client = glanceclient.Client(
                        glance_endpoint, token=keystone.auth_token)
                    self.comp.upload_image_via_url(
                        glance_client,
                        self.config.image_name,
                        self.config.vm_image_url)
                    self.image_instance = self.comp.find_image(self.config.image_name)
                else:
                    # Exit the pogram
                    print '%s: image to launch VM not found. ABORTING.' \
                        % (self.config.image_name)
                    sys.exit(1)

            self.assert_true(self.image_instance)
            print 'Found image %s to launch VM, will continue' % (self.config.image_name)
            self.flavor_type = self.comp.find_flavor(self.config.flavor_type)
            self.net = network.Network(neutron, self.config)

            self.rescol.add_property('l2agent_type', self.net.l2agent_type)
            print "OpenStack agent: " + self.net.l2agent_type
            try:
                network_type = self.net.vm_int_net[0]['provider:network_type']
                print "OpenStack network type: " + network_type
                self.rescol.add_property('encapsulation', network_type)
            except KeyError as exp:
                network_type = 'Unknown'
                print "Provider network type not found: ", str(exp)

        # Create a new security group for the test
        self.sec_group = self.comp.security_group_create()
        if not self.sec_group:
            raise VmtpException("Security group creation failed")
        if self.config.reuse_existing_vm:
            self.server.internal_ip = self.config.vm_server_internal_ip
            self.client.internal_ip = self.config.vm_client_internal_ip
            if self.config.vm_server_external_ip:
                self.server.ssh_access.host = self.config.vm_server_external_ip
            else:
                self.server.ssh_access.host = self.config.vm_server_internal_ip
            if self.config.vm_client_external_ip:
                self.client.ssh_access.host = self.config.vm_client_external_ip
            else:
                self.client.ssh_access.host = self.config.vm_client_internal_ip
            return

        # this is the standard way of running the test
        # NICs to be used for the VM
        if self.config.reuse_network_name:
            # VM needs to connect to existing management and new data network
            # Reset the management network name
            int_net_name = list(self.config.internal_network_name)
            int_net_name[0] = self.config.reuse_network_name
            self.config.internal_network_name = int_net_name
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
            if self.config.inter_node_only:
                # in this case we do not want the client to run on the same host
                # as the server
                avail_list.pop(0)
        self.client_az_list = avail_list

        self.server = PerfInstance(self.config.vm_name_server,
                                   self.config,
                                   self.comp,
                                   self.net,
                                   server=True)
        self.server.display('Creating server VM...')
        self.create_instance(self.server, server_az,
                             self.net.vm_int_net[0])

    # Test throughput for the case of the external host
    def ext_host_tp_test(self):
        client = PerfInstance('Host-' + self.config.ext_host.host + '-Client', self.config)
        if not client.setup_ssh(self.config.ext_host):
            client.display('SSH to ext host failed, check IP or make sure public key is configured')
        else:
            client.buginf('SSH connected')
            client.create()
            FlowPrinter.print_desc('External-VM (upload/download)')
            res = client.run_client('External-VM',
                                    self.server.ssh_access.host,
                                    self.server,
                                    bandwidth=self.config.vm_bandwidth,
                                    bidirectional=True)
            if res:
                self.rescol.add_flow_result(res)
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
        self.client = PerfInstance(self.config.vm_name_client,
                                   self.config,
                                   self.comp,
                                   self.net)
        self.client.display('Creating client VM...')
        self.create_instance(self.client, client_az, int_net)

    def measure_flow(self, label, target_ip):
        label = self.add_location(label)
        FlowPrinter.print_desc(label)

        # results for this flow as a dict
        perf_output = self.client.run_client(label, target_ip,
                                             self.server,
                                             bandwidth=self.config.vm_bandwidth,
                                             az_to=self.server.az)
        if self.config.stop_on_error:
            # check if there is any error in the results
            results_list = perf_output['results']
            for res_dict in results_list:
                if 'error' in res_dict:
                    print('Stopping execution on error, cleanup all VMs/networks manually')
                    self.rescol.pprint(perf_output)
                    sys.exit(2)

        self.rescol.add_flow_result(perf_output)

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
            if not self.config.reuse_network_name:
                # Different network
                self.create_flow_client(client_az, self.net.vm_int_net[1])

                self.measure_flow("VM to VM different network fixed IP",
                                  self.server.internal_ip)
                if not self.config.ipv6_mode:
                    self.measure_flow("VM to VM different network floating IP",
                                      self.server.ssh_access.host)

                self.client.dispose()
                self.client = None

        # If external network is specified run that case
        if self.config.ext_host:
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
        if not self.config.reuse_existing_vm and self.net:
            self.net.dispose()
        # Remove the public key
        if self.comp:
            self.comp.remove_public_key(self.config.public_key_name)
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

        if self.config.stop_on_error and error_flag:
            print('Stopping execution on error, cleanup all VMs/networks manually')
            sys.exit(2)
        else:
            self.teardown()

def test_native_tp(nhosts, ifname, config):
    FlowPrinter.print_desc('Native Host to Host throughput')
    result_list = []
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
                    if client_host == server_host:
                        desc = 'Native intra-host'
                    else:
                        desc = 'Native inter-host'
                    res = client.run_client(desc,
                                            server_ip,
                                            server,
                                            bandwidth=config.vm_bandwidth)
                    result_list.append(res)
                client.dispose()
    server.dispose()

    return result_list

def get_controller_info(ssh_access, net, res_col, retry_count):
    if not ssh_access:
        return
    print 'Fetching OpenStack deployment details...'
    sshcon = sshutils.SSH(ssh_access, connect_retry_count=retry_count)
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

def gen_report_data(proto, result):
    try:
        if proto in ['TCP', 'UDP', 'ICMP']:
            result = [x for x in result if x['protocol'] == proto]
        elif proto == 'Upload':
            result = [x for x in result if ('direction' not in x) and (x['protocol'] == 'TCP')]
        elif proto == 'Download':
            result = [x for x in result if ('direction' in x) and (x['protocol'] == 'TCP')]

        retval = {}
        if proto in ['TCP', 'Upload', 'Download']:
            tcp_test_count = 0
            retval = {'tp_kbps': 0, 'rtt_ms': 0}
        elif proto == 'UDP':
            pkt_size_list = [x['pkt_size'] for x in result]
            retval = dict(zip(pkt_size_list, [{}, {}, {}]))

        for item in result:
            if proto in ['TCP', 'Upload', 'Download']:
                tcp_test_count = tcp_test_count + 1
                retval['tp_kbps'] += item['throughput_kbps']
                retval['rtt_ms'] += item['rtt_ms']
            elif proto == 'UDP':
                retval[item['pkt_size']]['tp_kbps'] = item['throughput_kbps']
                retval[item['pkt_size']]['loss_rate'] = item['loss_rate']
            elif proto == 'ICMP':
                for key in ['rtt_avg_ms', 'rtt_max_ms', 'rtt_min_ms', 'rtt_stddev']:
                    retval[key] = item[key]

        if proto in ['TCP', 'Upload', 'Download']:
            for key in retval:
                retval[key] = '{0:n}'.format(retval[key] / tcp_test_count)
    except Exception:
        retval = "ERROR! Check JSON outputs for more details."

    return retval

def print_report(results):
    # In order to parse the results with less logic, we are encoding the results as below:
    # Same Network = 0, Different Network = 1
    # Fixed IP = 0, Floating IP = 1
    # Intra-node = 0, Inter-node = 1
    SPASS = "\033[92mPASSED\033[0m"
    SFAIL = "\033[91mFAILED\033[0m"

    # Initilize a run_status[4][2][2][3] array
    run_status = [([([(["SKIPPED"] * 3) for i in range(2)]) for i in range(2)]) for i in range(4)]
    run_data = [([([([{}] * 3) for i in range(2)]) for i in range(2)]) for i in range(4)]
    flows = results['flows']
    for flow in flows:
        res = flow['results']
        if flow['desc'].find('External-VM') != -1:
            for item in res:
                if 'direction' not in item:
                    run_status[2][0][0][0] = SPASS if 'error' not in item else SFAIL
                    if run_status[2][0][0][0] == SPASS:
                        run_data[2][0][0][0] = gen_report_data('Upload', res)
                else:
                    run_status[2][0][0][1] = SPASS if 'error' not in item else SFAIL
                    if run_status[2][0][0][1] == SPASS:
                        run_data[2][0][0][1] = gen_report_data('Download', res)
            continue

        idx0 = 0 if flow['desc'].find('same network') != -1 else 1
        idx1 = 0 if flow['desc'].find('fixed IP') != -1 else 1
        idx2 = 0 if flow['desc'].find('intra-node') != -1 else 1
        if flow['desc'].find('Native') != -1:
            idx0 = 3
            idx1 = idx2 = 0
        for item in res:
            for idx3, proto in enumerate(['TCP', 'UDP', 'ICMP']):
                if (item['protocol'] == proto) and (run_status[idx0][idx1][idx2][idx3] != SFAIL):
                    if 'error' in item:
                        run_status[idx0][idx1][idx2][idx3] = SFAIL
                    else:
                        run_status[idx0][idx1][idx2][idx3] = SPASS
                        run_data[idx0][idx1][idx2][idx3] = gen_report_data(proto, res)

    table = []
    scenario = 0
    for idx0, net in enumerate(['Same Network', 'Different Network']):
        for idx1, ip in enumerate(['Fixed IP', 'Floating IP']):
            if net == 'Same Network' and ip == 'Floating IP':
                continue
            for idx2, node in enumerate(['Intra-node', 'Inter-node']):
                for idx3, proto in enumerate(['TCP', 'UDP', 'ICMP']):
                    row = [str(scenario / 3 + 1) + "." + str(idx3 + 1),
                           "%s, %s, %s, %s" % (net, ip, node, proto),
                           run_status[idx0][idx1][idx2][idx3],
                           run_data[idx0][idx1][idx2][idx3]]
                    table.append(row)
                    scenario = scenario + 1
    for idx3, proto in enumerate(['TCP', 'UDP', 'ICMP']):
        row = [str(scenario / 3 + 1) + "." + str(idx3 + 1),
               "Native Throughput, %s" % (proto),
               run_status[3][0][0][idx3], run_data[3][0][0][idx3]]
        table.append(row)
        scenario = scenario + 1
    table.append(['8.1', 'VM to Host Uploading', run_status[2][0][0][0], run_data[2][0][0][0]])
    table.append(['8.2', 'VM to Host Downloading', run_status[2][0][0][1], run_data[2][0][0][1]])

    ptable = zip(*table[1:])[2]
    cnt_passed = ptable.count(SPASS)
    cnt_failed = ptable.count(SFAIL)
    cnt_skipped = ptable.count("SKIPPED")
    cnt_valid = len(table) - 1 - cnt_skipped
    passed_rate = float(cnt_passed) / cnt_valid * 100 if cnt_valid != 0 else 0
    failed_rate = float(cnt_failed) / cnt_valid * 100 if cnt_valid != 0 else 0

    ptable = PrettyTable(['Scenario', 'Scenario Name', 'Functional Status', 'Data'])
    ptable.align = "l"
    ptable.max_width = 80
    for row in table:
        ptable.add_row(row)

    print "\nSummary of results"
    print "=================="
    print "Total Scenarios:   %d" % (len(table) - 1)
    print "Passed Scenarios:  %d [%.2f%%]" % (cnt_passed, passed_rate)
    print "Failed Scenarios:  %d [%.2f%%]" % (cnt_failed, failed_rate)
    print "Skipped Scenarios: %d" % (cnt_skipped)
    print ptable

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

def get_ssh_access(opt_name, opt_value, config):
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

def parse_opts_from_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', dest='config',
                        action='store',
                        help='override default values with a config file',
                        metavar='<config_file>')

    parser.add_argument('-sc', '--show-config', dest='show_config',
                        default=False,
                        action='store_true',
                        help='print the default config')

    parser.add_argument('-r', '--rc', dest='rc',
                        action='store',
                        help='source OpenStack credentials from rc file',
                        metavar='<openrc_file>')

    parser.add_argument('-m', '--monitor', dest='monitor',
                        action='store',
                        help='Enable CPU monitoring (requires Ganglia)',
                        metavar='<gmond_ip>[:<port>]')

    parser.add_argument('-p', '--password', dest='passwd',
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

    parser.add_argument('--reuse_network_name', dest='reuse_network_name',
                        action='store',
                        default=None,
                        help='the network to be reused for performing tests',
                        metavar='<network_name>')

    parser.add_argument('--os-dataplane-network', dest='os_dataplane_network',
                        action='store',
                        default=None,
                        help='Internal network name for OpenStack to hold data plane traffic',
                        metavar='<network_name>')

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

    return parser.parse_known_args()[0]

def merge_opts_to_configs(opts):

    default_cfg_file = resource_string(__name__, "cfg.default.yaml")
    # read the default configuration file and possibly an override config file
    # the precedence order is as follows:
    # $HOME/.vmtp.yaml if exists
    # -c <file> from command line if provided
    # cfg.default.yaml
    config = config_loads(default_cfg_file)
    local_cfg = os.path.expanduser('~/.vmtp.yaml')
    if os.path.isfile(local_cfg):
        config = config_load(local_cfg, config)

    if opts.config:
        config = config_load(opts.config, config)

    if opts.show_config:
        print default_cfg_file
        sys.exit(0)

    if opts.version:
        print(__version__)
        sys.exit(0)

    config.debug = opts.debug
    config.stop_on_error = opts.stop_on_error
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
    config.ext_host = get_ssh_access('external-host', opts.ext_host, config)

    ###################################################
    # VM Image URL
    ###################################################
    if opts.vm_image_url:
        config.vm_image_url = opts.vm_image_url

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

    if opts.reuse_network_name:
        config.reuse_network_name = opts.reuse_network_name

    if opts.os_dataplane_network:
        config.os_dataplane_network = opts.os_dataplane_network

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

    return config

def run_vmtp(opts):
    '''Run VMTP
    :param opts: Parameters that to be passed to VMTP in type argparse.Namespace(). See:
                 http://vmtp.readthedocs.org/en/latest/usage.html#running-vmtp-as-a-library
                 for examples of the usage on this API.
    :return: A dictionary which contains the results in details.
    '''

    if (sys.argv == ['']):
        # Running from a Python call
        def_opts = parse_opts_from_cli()
        for key, value in vars(def_opts).iteritems():
            if key not in opts:
                opts.__setattr__(key, value)

    config = merge_opts_to_configs(opts)
    rescol = ResultsCollector()

    # Run the native host tests if specified by user
    if opts.hosts:
        # A list of 0 to 2 HostSshAccess elements
        # remove any duplicate
        opts.hosts = list(set(opts.hosts))
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
            native_hosts.append(get_ssh_access('host', host, config))
        native_tp_results = test_native_tp(native_hosts, if_name, config)
    else:
        native_tp_results = []

    for item in native_tp_results:
        rescol.add_flow_result(item)

    # Parse the credentials of the OpenStack cloud, and run the benchmarking
    cred = credentials.Credentials(opts.rc, opts.passwd, opts.no_env)
    if cred.rc_auth_url:
        if config.debug:
            print 'Using ' + cred.rc_auth_url
        vmtp_instance = VmtpTest(config, cred, rescol)
        vmtp_instance.run()
        vmtp_net = vmtp_instance.net

        # Retrieve controller information if requested
        # controller node ssh access to collect metadata for the run.
        ctrl_host_access = get_ssh_access('controller-node', opts.controller_node, config)
        get_controller_info(ctrl_host_access,
                            vmtp_net,
                            rescol,
                            config.ssh_retry_count)

    # Print the report
    print_report(rescol.results)

    # Post-processing of the results, adding some metadata
    if cred.rc_auth_url:
        rescol.add_property('auth_url', cred.rc_auth_url)
        rescol.mask_credentials()
    rescol.generate_runid()
    if opts.test_description:
        rescol.add_property('test_description', opts.test_description)

    # Save results to a JSON file
    if config.json_file:
        rescol.save(config)

    # Save results to MongoDB
    if config.vmtp_mongod_ip:
        rescol.save_to_db(config)

    return rescol.results

def main():
    logging.basicConfig()
    opts = parse_opts_from_cli()
    run_vmtp(opts)

if __name__ == '__main__':
    main()
