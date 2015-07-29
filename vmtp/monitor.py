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


'''
Module for parsing statistical output from Ganglia (gmond) server
The module opens a socket connection to collect statistical data.
It parses the raw data in xml format.

The data from ganglia/gmond is in a heirarchical xml format as below:
<CLUSTER>
   <HOST..>
     <METRIC ../>
     <METRIC ../>
     :
   </HOST>
   :
   <HOST..>
     <METRIC ../>
     <METRIC ../>
   </HOST>
</CLUSTER>

## Usage:
Using the module is simple.

1. instantiate the Monitor with the gmond server ip and port to poll.

    gmon = Monitor("172.22.191.151", 8649)

2. Start the monitoring thread
    gmon.start_monitoring_thread(frequency, count)

     < run tests/tasks>

    gmon.stop_monitoring_thread()

3. Collecting stats:
    cpu_metric = gmon.build_cpu_metric()

    Returns a dictionary object with all the cpu stats for each
    node


'''

import datetime
import re
import socket
import subprocess
from threading import Thread
import time

from lxml import etree

class MonitorExecutor(Thread):
    '''
    Thread handler class to asynchronously collect stats
    '''
    THREAD_STOPPED = 0
    THREAD_RUNNING = 1

    def __init__(self, gmond_svr, gmond_port, freq=5, count=5):
        super(MonitorExecutor, self).__init__()
        self.gmond_svr_ip = gmond_svr
        self.gmond_port = gmond_port

        self.freq = freq
        self.count = count

        self.force_stop = False
        self.thread_status = MonitorExecutor.THREAD_STOPPED

        # This dictionary always holds the latest metric.
        self.gmond_parsed_tree_list = []


    def run(self):
        '''
        The thread runnable method.
        The function will periodically poll the gmond server and
        collect the metrics.
        '''
        self.thread_status = MonitorExecutor.THREAD_RUNNING

        count = self.count
        while count > 0:
            if self.force_stop:
                self.thread_status = MonitorExecutor.THREAD_STOPPED
                return

            self.parse_gmond_xml_data()
            count -= 1
            time.sleep(self.freq)
        self.thread_status = MonitorExecutor.THREAD_STOPPED


    def set_force_stop(self):
        '''
        Setting the force stop flag to stop the thread. By default
        the thread stops after the specific count/iterations is reached
        '''
        self.force_stop = True

    def parse_gmond_xml_data(self):
        '''
        Parse gmond data (V2)
        Retrieve the ganglia stats from the aggregation node
        :return: None in case of error or a dictionary containing the stats
        '''
        gmond_parsed_tree = {}
        raw_data = self.retrieve_stats_raw()

        if raw_data is None or len(raw_data) == 0:
            print "Failed to retrieve stats from server"
            return

        xtree = etree.XML(raw_data)
        ############################################
        # Populate cluster information.
        ############################################
        for elem in xtree.iter('CLUSTER'):
            gmond_parsed_tree['CLUSTER-NAME'] = str(elem.get('NAME'))
            gmond_parsed_tree['LOCALTIME'] = str(elem.get('LOCALTIME'))
            gmond_parsed_tree['URL'] = str(elem.get('URL'))

            host_list = []
            for helem in elem.iterchildren():
                host = {}
                host['NAME'] = str(helem.get('NAME'))
                host['IP'] = str(helem.get('IP'))
                host['REPORTED'] = str(helem.get('REPORTED'))
                host['TN'] = str(helem.get('TN'))
                host['TMAX'] = str(helem.get('TMAX'))
                host['DMAX'] = str(helem.get('DMAX'))
                host['LOCATION'] = str(helem.get('LOCATION'))
                host['GMOND_STARTED'] = str(helem.get('GMOND_STARTED'))

                mlist = []
                for metric in helem.iterchildren():
                    mdic = {}
                    mdic['NAME'] = str(metric.get('NAME'))
                    mdic['VAL'] = str(metric.get('VAL'))
                    mlist.append(mdic)

                host['metrics'] = mlist
                host_list.append(host)

            gmond_parsed_tree['hosts'] = host_list
            stat_dt = datetime.datetime.now()
            gmond_parsed_tree['dt'] = stat_dt
        self.gmond_parsed_tree_list.append(gmond_parsed_tree)


    def retrieve_stats_raw(self):
        '''
        Retrieve stats from the gmond process.
        '''
        soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        soc.settimeout(10)
        try:
            soc.connect((self.gmond_svr_ip, self.gmond_port))
        except socket.error as exp:
            print "Connection failure host: %s [%s]" % (self.gmond_svr_ip, exp)
            return None

        data = ""
        while True:
            try:
                rbytes = soc.recv(4096)
            except socket.error as exp:
                print "Read failed for host: ", str(exp)
                return None

            if len(rbytes) == 0:
                break
            data += rbytes

        soc.close()
        return data


class Monitor(object):
    gmond_svr_ip = None
    gmond_port = None
    gmond_parsed_tree = {}

    def __init__(self, gmond_svr, gmond_port=8649):
        '''
        The constructor simply sets the values of the gmond server and port.
        '''
        self.gmond_svr_ip = gmond_svr
        self.gmond_port = gmond_port
        # List of all stats.
        self.gmond_parsed_tree_list = []
        # series for all cpu loads
        self.cpu_res = {}

        self.mon_thread = None

    def start_monitoring_thread(self, freq=10, count=10):
        '''
        Start the monitoring thread.
        '''
        self.mon_thread = MonitorExecutor(self.gmond_svr_ip,
                                          self.gmond_port, freq, count)
        self.mon_thread.start()


    def stop_monitoring_thread(self):
        self.mon_thread.set_force_stop()
        self.gmond_parsed_tree_list = self.mon_thread.gmond_parsed_tree_list


    def strip_raw_telnet_output(self, raw_data):
        '''
        When using the retrieve_stats_raw_telent api, the raw data
        has some additional text along with the xml data. We need to
        strip that before we can invoke pass it through the lxml parser.
        '''
        data = ""
        xml_flag = False
        for line in raw_data.splitlines():
            if re.match(r".*<?xml version.*", line):
                xml_flag = True
            if xml_flag:
                data += line + "\n"

        return data


    def retrieve_stats_raw_telnet(self):
        '''
        This way of retrieval is to create a subprocess and execute
        the telnet command on the port to retrieve the xml raw data.
        '''
        cmd = "telnet " + self.gmond_svr_ip + " " + str(self.gmond_port)
        print "cmd: ", cmd
        port = str(self.gmond_port)

        proc = subprocess.Popen(["telnet", self.gmond_svr_ip, port],
                                stdout=subprocess.PIPE)
        (output, _) = proc.communicate()

        newout = self.strip_raw_telnet_output(output)
        return newout


    def get_host_list(self, gmond_parsed_tree):
        '''
        Function returns all the hosts {} as a list.
        '''
        return gmond_parsed_tree['hosts']


    def get_metric_value(self, parsed_node, host_name, name):
        '''
        The function returns the value of a specific metric, given
        the host name and the metric name to collect.
        '''
        for host in parsed_node['hosts']:
            if host['NAME'] == host_name:
                for metric in host['metrics']:
                    if metric['NAME'] == name:
                        return metric['VAL']

        return 0

    def get_aggregate_cpu_usage(self, parsed_node, host_name):
        '''
        The function returns the aggregate CPU usage for a specific host.
        eqation: [user cpu + system cpu * no of cpu /100]
        '''
        cpu_user = float(self.get_metric_value(parsed_node, host_name, "cpu_user"))
        cpu_system = float(self.get_metric_value(parsed_node, host_name, "cpu_system"))
        cpu_num = int(self.get_metric_value(parsed_node, host_name, "cpu_num"))

        return (cpu_user + cpu_system) * cpu_num / 100


    def build_cpu_metrics(self):
        '''Add a new set of cpu metrics to the results dictionary self.cpu_res
        The result dest dictionary should look like this:
                 key = host IP, value = list of cpu load where the
                 the first value is the baseline value followed by 1 or more
                 values collected during the test
        {
        '10.0.0.1': [ 0.03, 1.23, 1.20 ],
        '10.0.0.2': [ 0.10, 1.98, 2.72 ]
        }
        After another xml is decoded:
        {
        '10.0.0.1': [ 0.03, 1.23, 1.20, 1.41 ],
        '10.0.0.2': [ 0.10, 1.98, 2.72, 2.04 ]
        }
        Each value in the list is the cpu load calculated as
        (cpu_user + cpu_system) * num_cpu / 100
        The load_five metric cannot be used as it is the average for last 5'
        '''
        cpu_res = {}
        for parsed_node in self.gmond_parsed_tree_list:
            for host in self.get_host_list(parsed_node):
                host_ip = host['IP']
                cpu_num = 0
                cpu_user = 0.0
                cpu_system = 0.0

                cpu_user = float(self.get_metric_value(parsed_node, host['NAME'], "cpu_user"))
                cpu_system = float(self.get_metric_value(parsed_node, host['NAME'], "cpu_system"))
                cpu_num = int(self.get_metric_value(parsed_node, host['NAME'], "cpu_num"))
                cpu_load = round(((cpu_user + cpu_system) * cpu_num) / 100, 2)
                try:
                    cpu_res[host_ip].append(cpu_load)
                except KeyError:
                    cpu_res[host_ip] = [cpu_load]

        return cpu_res

    def get_formatted_datetime(self, parsed_node):
        '''
        Returns the data in formated string. This is the
        time when the last stat was collected.
        '''
        now = parsed_node['dt']
        fmt_dt = "[" + str(now.hour) + ":" + str(now.minute) + \
                 ":" + str(now.second) + "]"
        return fmt_dt


    def get_formatted_host_row(self, host_list):
        '''
         Returns the hosts in formated order (for printing purposes)
        '''
        row_str = "".ljust(10)
        for host in host_list:
            row_str += host['NAME'].ljust(15)
        return row_str

    def get_formatted_metric_row(self, parsed_node, metric, justval):
        '''
        Returns a specific metric for all hosts in the same row
        in formated string (for printing)
        '''
        host_list = self.get_host_list(parsed_node)

        row_str = metric.ljust(len(metric) + 2)
        for host in host_list:
            val = self.get_metric_value(parsed_node, host['NAME'], metric)
            row_str += str(val).ljust(justval)
        return row_str


    def dump_cpu_stats(self):
        '''
        Print the CPU stats
        '''
        hl_len = 80
        print "-" * hl_len
        print "CPU Statistics: ",

        for parsed_node in self.gmond_parsed_tree_list:
            hosts = self.get_host_list(parsed_node)

            print self.get_formatted_datetime(parsed_node)
            print self.get_formatted_host_row(hosts)
            print "-" * hl_len
            print self.get_formatted_metric_row(parsed_node, "cpu_user", 18)
            print self.get_formatted_metric_row(parsed_node, "cpu_system", 18)

            print "Aggregate ",
            for host in hosts:
                print str(self.get_aggregate_cpu_usage(parsed_node,
                                                       host['NAME'])).ljust(16),
            print "\n"

    def dump_gmond_parsed_tree(self):
        '''
        Display the full tree parsed from the gmond server stats.
        '''
        hl_len = 60

        for parsed_node in self.gmond_parsed_tree_list:
            print "%-20s (%s) URL: %s " % \
                  (parsed_node['CLUSTER-NAME'],
                   parsed_node['LOCALTIME'],
                   parsed_node['URL'])
            print "-" * hl_len

            row_str = " ".ljust(9)
            for host in parsed_node['hosts']:
                row_str += host['NAME'].ljust(15)
            row_str += "\n"
            print row_str
            print "-" * hl_len
            metric_count = len(parsed_node['hosts'][0]['metrics'])
            for count in range(0, metric_count):
                row_str = ""
                host = parsed_node['hosts'][0]
                row_str += parsed_node['hosts'][0]['metrics'][count]['NAME'].ljust(18)
                for host in parsed_node['hosts']:
                    val = str(self.get_metric_value(parsed_node, host['NAME'],
                                                    host['metrics'][count]['NAME']))
                    row_str += val.ljust(12)

                row_str += str(parsed_node['hosts'][0]).ljust(5)

                print row_str


##################################################
# Only invoke the module directly for test purposes. Should be
# invoked from pns script.
##################################################
def main():
    print "main: monitor"
    gmon = Monitor("172.22.191.151", 8649)
    gmon.start_monitoring_thread(freq=5, count=20)
    print "wait for 15 seconds"
    time.sleep(20)
    print "Now force the thread to stop"
    gmon.stop_monitoring_thread()
    gmon.dump_cpu_stats()

    cpu_metric = gmon.build_cpu_metrics()
    print "cpu_metric: ", cpu_metric


if __name__ == "__main__":
    main()
