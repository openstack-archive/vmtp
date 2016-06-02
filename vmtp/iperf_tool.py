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

import re

from log import LOG
from perf_tool import PerfTool

# The resulting unit should be in K
MULTIPLIERS = {'K': 1,
               'M': 1.0e3,
               'G': 1.0e6}

def get_bdw_kbps(bdw, bdw_unit):
    if not bdw_unit:
        # bits/sec
        return bdw / 1000
    if bdw_unit in MULTIPLIERS:
        return int(bdw * MULTIPLIERS[bdw_unit])
    LOG.error('Error: unknown multiplier: ' + bdw_unit)
    return bdw

class IperfTool(PerfTool):

    def __init__(self, instance):
        PerfTool.__init__(self, 'iperf', instance)

    def get_server_launch_cmd(self):
        '''Return the command to launch the server side.'''
        # Need 1 server for tcp (port 5001) and 1 for udp (port 5001)
        return [self.dest_path + ' -s >/dev/null &',
                self.dest_path + ' -s -u >/dev/null &']

    def run_client(self, target_ip, target_instance,
                   mss=None, bandwidth=0, bidirectional=False):
        '''Run the test
        :return:  list containing one or more dictionary results
        '''
        res_list = []

        # Get list of protocols and packet sizes to measure
        (proto_list, proto_pkt_sizes) = self.get_proto_profile()

        for proto, pkt_size_list in zip(proto_list, proto_pkt_sizes):
            # bidirectional is not supported for udp
            # (need to find the right iperf options to make it work as there are
            # issues for the server to send back results to the client in reverse
            # direction
            if proto == 'UDP':
                bidir = False
                loop_count = 1
            else:
                # For accuracy purpose, TCP throughput will be measured multiple times
                bidir = bidirectional
                loop_count = self.instance.config.tcp_tp_loop_count
            for pkt_size in pkt_size_list:
                for _ in xrange(loop_count):
                    res = self.run_client_dir(target_ip, mss,
                                              bandwidth_kbps=bandwidth,
                                              bidirectional=bidir,
                                              protocol=proto,
                                              length=pkt_size)
                    # for bidirectional the function returns a list of 2 results
                    res_list.extend(res)
        return res_list

    def run_client_dir(self, target_ip,
                       mss,
                       bidirectional=False,
                       bandwidth_kbps=0,
                       protocol='TCP',
                       length=0,
                       no_cpu_timed=0):
        '''Run client for given protocol and packet size
        :param bandwidth_kbps: transmit rate limit in Kbps
        :param udp: if true get UDP throughput, else get TCP throughput
        :param length: length of network write|read buf (default 1K|8K/udp, 64K/tcp)
                       for udp is the packet size
        :param no_cpu_timed: if non zero will disable cpu collection and override
                       the time with the provided value - used mainly for udp
                       to find quickly the optimal throughput using short
                       tests at various throughput values
        :return: a list of dictionary with the 1 or 2 results (see parse_results())
        '''
        # run client using the default TCP window size (tcp window
        # scaling is normally enabled by default so setting explicit window
        # size is not going to help achieve better results)
        opts = ''
        udp = protocol == "UDP"
        # run iperf client using the default TCP window size (tcp window
        # scaling is normally enabled by default so setting explicit window
        # size is not going to help achieve better results)
        if mss:
            opts += " -M " + str(mss)

        if bidirectional:
            opts += " -r"

        if length:
            opts += " -l" + str(length)

        if udp:
            opts += " -u"
            # for UDP if the bandwidth is not provided we need to calculate
            # the optimal bandwidth
            if not bandwidth_kbps:
                udp_res = self.find_bdw(length, target_ip, protocol)
                if 'error' in udp_res:
                    return [udp_res]
                if not self.instance.gmond_svr:
                    # if we do not collect CPU we might as well return
                    # the results found through iteration
                    return [udp_res]
                bandwidth_kbps = udp_res['throughput_kbps']

        if bandwidth_kbps:
            opts += " -b%dK" % (bandwidth_kbps)

        if no_cpu_timed:
            duration_sec = no_cpu_timed
        else:
            duration_sec = self.instance.get_cmd_duration()

        cmd = "%s -c %s -t %d %s" % (self.dest_path,
                                     target_ip,
                                     duration_sec,
                                     opts)
        self.instance.buginf(cmd)
        if no_cpu_timed:
            # force the timeout value with 20 second extra for the command to
            # complete and do not collect CPU
            cpu_load = None
            cmd_out = self.instance.exec_command(cmd, duration_sec + 20)
        else:
            (cmd_out, cpu_load) = self.instance.exec_with_cpu(cmd)

        if udp:
            # Decode UDP output (unicast and multicast):
            #
            # [  3] local 127.0.0.1 port 54244 connected with 127.0.0.1 port 5001
            # [ ID] Interval       Transfer     Bandwidth
            # [  3]  0.0-10.0 sec  1.25 MBytes  1.05 Mbits/sec
            # [  3] Sent 893 datagrams
            # [  3] Server Report:
            # [ ID] Interval       Transfer     Bandwidth       Jitter   Lost/Total Da
            # [  3]  0.0-10.0 sec  1.25 MBytes  1.05 Mbits/sec  0.032 ms 1/894 (0.11%)
            # [  3]  0.0-15.0 sec  14060 datagrams received out-of-order
            re_udp = r'([\d\.]*)\s*([KMG]?)bits/sec\s*[\d\.]*\s*ms\s*(\d*)/\s*(\d*) '
            match = re.search(re_udp, cmd_out)
            if match:
                bdw = float(match.group(1))
                bdw_unit = match.group(2)
                drop = float(match.group(3))
                pkt = int(match.group(4))
                # iperf uses multiple of 1000 for K - not 1024
                return [self.parse_results('UDP',
                                           get_bdw_kbps(bdw, bdw_unit),
                                           lossrate=round(drop * 100 / pkt, 2),
                                           msg_size=length,
                                           cpu_load=cpu_load)]
        else:
            # TCP output:
            # [  3] local 127.0.0.1 port 57936 connected with 127.0.0.1 port 5001
            # [ ID] Interval       Transfer     Bandwidth
            # [  3]  0.0-10.0 sec  2.09 GBytes  1.79 Gbits/sec
            #
            # For bi-directional option (-r), last 3 lines:
            # [  5]  0.0-10.0 sec  36.0 GBytes  31.0 Gbits/sec
            # [  4] local 127.0.0.1 port 5002 connected with 127.0.0.1 port 39118
            # [  4]  0.0-10.0 sec  36.0 GBytes  30.9 Gbits/sec
            re_tcp = r'Bytes\s*([\d\.]*)\s*([KMG])bits/sec'
            match = re.search(re_tcp, cmd_out)
            if match:
                bdw = float(match.group(1))
                bdw_unit = match.group(2)
                res = [self.parse_results('TCP',
                                          get_bdw_kbps(bdw, bdw_unit),
                                          msg_size=length,
                                          cpu_load=cpu_load)]
                if bidirectional:
                    # decode the last row results
                    re_tcp = r'Bytes\s*([\d\.]*)\s*([KMG])bits/sec$'
                    match = re.search(re_tcp, cmd_out)
                    if match:
                        bdw = float(match.group(1))
                        bdw_unit = match.group(2)
                        # use the same cpu load since the same run
                        # does both directions
                        res.append(self.parse_results('TCP',
                                                      get_bdw_kbps(bdw, bdw_unit),
                                                      reverse_dir=True,
                                                      msg_size=length,
                                                      cpu_load=cpu_load))
                return res
        return [self.parse_error(protocol, 'Could not parse: %s' % (cmd_out))]
