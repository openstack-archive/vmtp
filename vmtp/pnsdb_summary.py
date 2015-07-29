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
import re
import sys

import pns_mongo
import tabulate

###########################################
# Global list of all result functions
# that are displayed as a menu/list.
###########################################
pnsdb_results_list = [
    ("Summary of all results", "show_summary_all"),
    ("Show TCP results for vlan encap", "show_tcp_summary_encap_vlan"),
    ("Show UDP results for vlan encap", "show_udp_summary_encap_vlan"),
]

network_type = [
    (0, "L2 Network"),
    (1, "L3 Network"),
    (100, "Unknown"),
]

vm_loc = [
    (0, "Intra-node"),
    (1, "Inter-node"),
]

flow_re = re.compile(r".*(same|different) network.*(fixed|floating).*"
                     "IP.*(inter|intra).*",
                     re.IGNORECASE)


def get_flow_type(flow_desc):
    vm_location = None
    nw_type = None
    fixed_ip = None

    mobj = flow_re.match(flow_desc)
    if mobj:
        if mobj.group(1) == "same":
            nw_type = network_type[0][0]
        elif mobj.group(1) == "different":
            nw_type = network_type[1][0]
        else:
            nw_type = network_type[2][0]

        if mobj.group(2) == "fixed":
            fixed_ip = True
        else:
            fixed_ip = False

        if mobj.group(3) == "inter":
            vm_location = vm_loc[1][0]
        else:
            vm_location = vm_loc[0][0]

    return(vm_location, nw_type, fixed_ip)


def get_tcp_flow_data(data):
    record_list = []
    for record in data:
        for flow in record['flows']:
            results = flow['results']
            get_flow_type(flow['desc'])
            for result in results:
                show_record = {}
                if result['protocol'] == "TCP" or result['protocol'] == "tcp":
                    show_record['throughput_kbps'] = result['throughput_kbps']
                    show_record['rtt_ms'] = result['rtt_ms']
                    show_record['pkt_size'] = result['pkt_size']
                    show_record['openstack_version'] = record['openstack_version']
                    show_record['date'] = record['date']
                    show_record['distro'] = record['distro']
                    # show_record['desc'] = flow['desc']
                    record_list.append(show_record)

    return record_list


def get_udp_flow_data(data):
    record_list = []
    for record in data:
        for flow in record['flows']:
            results = flow['results']
            get_flow_type(flow['desc'])
            for result in results:
                show_record = {}
                if result['protocol'] == "UDP" or result['protocol'] == "udp":
                    show_record['throughput_kbps'] = result['throughput_kbps']
                    show_record['loss_rate'] = result['loss_rate']
                    show_record['openstack_version'] = record['openstack_version']
                    show_record['date'] = record['date']
                    show_record['distro'] = record['distro']
                    # show_record['desc'] = flow['desc']
                    record_list.append(show_record)
    return record_list


def show_pnsdb_summary(db_server, db_port, db_name, db_collection):
    '''
    Show a summary of results.
    '''
    pattern = {}
    data = pns_mongo.pns_search_results_from_mongod(db_server,
                                                    db_port,
                                                    db_name,
                                                    db_collection,
                                                    pattern)
    record_list = get_tcp_flow_data(data)
    print tabulate.tabulate(record_list, headers="keys", tablefmt="grid")
    print data.count()

    data = pns_mongo.pns_search_results_from_mongod(db_server,
                                                    db_port,
                                                    db_name,
                                                    db_collection,
                                                    pattern)
    record_list = get_udp_flow_data(data)
    print "UDP:"
    print tabulate.tabulate(record_list, headers="keys", tablefmt="grid")


def get_results_info(results, cols, protocol=None):
    result_list = []

    for result in results:
        show_result = {}
        if protocol is not None:
            if result['protocol'] != protocol:
                continue
        for col in cols:
            if col in result.keys():
                show_result[col] = result[col]

        result_list.append(show_result)

    return result_list


def get_flow_info(flow, cols):
    flow_list = []
    show_flow = {}
    for col in cols:
        show_flow[col] = flow[col]
    (vmloc, nw_type, fixed_ip) = get_flow_type(flow['desc'])
    show_flow['nw_type'] = network_type[nw_type][1]
    show_flow['vm_loc'] = vm_loc[vmloc][1]
    if fixed_ip:
        show_flow['fixed_float'] = "Fixed IP"
    else:
        show_flow['fixed_float'] = "Floating IP"
    flow_list.append(show_flow)

    return flow_list


def get_record_info(record, cols):
    record_list = []
    show_record = {}
    for col in cols:
        show_record[col] = record[col]

    record_list.append(show_record)

    return record_list


def print_record_header(record):
    print "#" * 60
    print "RUN: %s" % (record['date'])
    cols = ['date', 'distro', 'openstack_version', 'encapsulation']
    record_list = get_record_info(record, cols)
    print tabulate.tabulate(record_list)


def print_flow_header(flow):
    cols = ['desc']
    flow_list = get_flow_info(flow, cols)
    print tabulate.tabulate(flow_list, tablefmt="simple")


def show_tcp_summary_encap_vlan(db_server, db_port, db_name, db_collection):
    pattern = {"encapsulation": "vlan"}

    data = pns_mongo.pns_search_results_from_mongod(db_server,
                                                    db_port,
                                                    db_name,
                                                    db_collection,
                                                    pattern)
    for record in data:
        print_record_header(record)
        for flow in record['flows']:
            print_flow_header(flow)
            cols = ['throughput_kbps', 'protocol', 'tool', 'rtt_ms']
            result_list = get_results_info(flow['results'], cols,
                                           protocol="TCP")
            print tabulate.tabulate(result_list,
                                    headers="keys", tablefmt="grid")

    print "\n"


def show_udp_summary_encap_vlan(db_server, db_port, db_name, db_collection):
    pattern = {"encapsulation": "vlan"}

    data = pns_mongo.pns_search_results_from_mongod(db_server,
                                                    db_port,
                                                    db_name,
                                                    db_collection,
                                                    pattern)
    for record in data:
        print_record_header(record)
        for flow in record['flows']:
            print_flow_header(flow)
            cols = ['throughput_kbps', 'protocol', 'loss_rate', 'pkt_size']
            result_list = get_results_info(flow['results'], cols,
                                           protocol="UDP")
            print tabulate.tabulate(result_list,
                                    headers="keys", tablefmt="grid")


def show_summary_all(db_server, db_port, db_name, db_collection):
    pattern = {}

    print "-" * 60
    print "Summary Data: "
    print "-" * 60

    data = pns_mongo.pns_search_results_from_mongod(db_server,
                                                    db_port,
                                                    db_name,
                                                    db_collection,
                                                    pattern)
    for record in data:
        print_record_header(record)
        for flow in record['flows']:
            print_flow_header(flow)

            # Display the results for each flow.
            cols = ['throughput_kbps', 'protocol', 'tool',
                    'rtt_ms', 'loss_rate', 'pkt_size',
                    'rtt_avg_ms']
            result_list = get_results_info(flow['results'], cols)
            print tabulate.tabulate(result_list,
                                    headers="keys", tablefmt="grid")

    print "\n"


def main():
    ####################################################################
    # parse arguments.
    # --server-ip [required]
    # --server-port [optional] [default: 27017]
    # --official [optional]
    ####################################################################
    parser = argparse.ArgumentParser(description="VMTP Results formatter")
    parser.add_argument('-s', "--server-ip", dest="server_ip",
                        action="store",
                        help="MongoDB Server IP address")
    parser.add_argument('-p', "--server-port", dest="server_port",
                        action="store",
                        help="MongoDB Server port (default 27017)")
    parser.add_argument("-o", "--official", default=False,
                        action="store_true",
                        help="Access offcial results collection")

    (opts, _) = parser.parse_known_args()

    if not opts.server_ip:
        print "Provide the pns db server ip address"
        sys.exit()

    db_server = opts.server_ip

    if not opts.server_port:
        db_port = 27017
    else:
        db_port = opts.server_port

    db_name = "pnsdb"

    if opts.official:
        print "Use db collection officialdata"
        db_collection = "officialdata"
    else:
        db_collection = "testdata"

    print "-" * 40
    print "Reports Menu:"
    print "-" * 40
    count = 0
    for option in pnsdb_results_list:
        print "%d: %s" % (count, option[0])
        count += 1
    print "\n"

    try:
        user_opt = int(raw_input("Choose a report [no] : "))
    except ValueError:
        print "Invalid option"
        sys.exit()

    globals()[pnsdb_results_list[user_opt][1]](db_server,
                                               db_port, db_name, db_collection)

if __name__ == '__main__':
    main()
