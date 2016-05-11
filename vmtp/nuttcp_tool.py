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

from perf_tool import PerfTool
import sshutils

class NuttcpTool(PerfTool):

    def __init__(self, instance):
        PerfTool.__init__(self, 'nuttcp-7.3.2', instance)

    def get_server_launch_cmd(self):
        '''Return the commands to launch the server side.'''
        if self.instance.config.ipv6_mode:
            return [self.dest_path + ' -P5002 -S --single-threaded -6 &']
        else:
            return [self.dest_path + ' -P5002 -S --single-threaded &']

    def run_client(self, target_ip, target_instance,
                   mss=None, bandwidth=0, bidirectional=False):
        '''Run the test
        :return:  list containing one or more dictionary results
        '''
        res_list = []
        if bidirectional:
            reverse_dir_list = [False, True]
        else:
            reverse_dir_list = [False]

        # Get list of protocols and packet sizes to measure
        (proto_list, proto_pkt_sizes) = self.get_proto_profile()
        for proto, pkt_size_list in zip(proto_list, proto_pkt_sizes):
            for pkt_size in pkt_size_list:
                for reverse_dir in reverse_dir_list:
                    # nuttcp does not support reverse dir for UDP...
                    if reverse_dir and proto != "TCP":
                        continue
                    if proto != "TCP":
                        self.instance.display('Measuring %s Throughput (packet size=%d)...',
                                              proto, pkt_size)
                        loop_count = 1
                    else:
                        # For accuracy purpose, TCP throughput will be measured 3 times
                        self.instance.display('Measuring TCP Throughput (packet size=%d)...',
                                              pkt_size)
                        loop_count = self.instance.config.tcp_tp_loop_count
                    for _ in xrange(loop_count):
                        res = self.run_client_dir(target_ip, mss,
                                                  reverse_dir=reverse_dir,
                                                  bandwidth_kbps=bandwidth,
                                                  protocol=proto,
                                                  length=pkt_size)
                        res_list.extend(res)

        # For UDP reverse direction we need to start the server on self.instance
        # and run the client on target_instance
        if bidirectional:
            for proto in proto_list:
                if proto == 'TCP':
                    continue
                # Start the server on the client (this tool instance)
                self.instance.display('Start ' + proto + ' server for reverse dir')
                if self.start_server():
                    # Start the client on the target instance
                    target_instance.display('Starting ' + proto + ' client for reverse dir')

                    for pkt_size in self.instance.config.udp_pkt_sizes:
                        self.instance.display('Measuring %s Throughput packet size=%d'
                                              ' (reverse direction)...',
                                              proto, pkt_size)
                        res = target_instance.tp_tool.run_client_dir(self.instance.internal_ip,
                                                                     mss,
                                                                     bandwidth_kbps=bandwidth,
                                                                     protocol=proto,
                                                                     length=pkt_size)
                        res[0]['direction'] = 'reverse'
                        res_list.extend(res)
                else:
                    self.instance.display('Failed to start ' + proto + ' server for reverse dir')
        return res_list

    def run_client_dir(self, target_ip,
                       mss,
                       reverse_dir=False,
                       bandwidth_kbps=0,
                       protocol='TCP',
                       length=0,
                       no_cpu_timed=0):
        '''Run client in one direction
        :param reverse_dir: True if reverse the direction (tcp only for now)
        :param bandwidth_kbps: transmit rate limit in Kbps
        :param protocol: (TCP|UDP|Multicast)
        :param length: length of network write|read buf (default 1K|8K/udp, 64K/tcp)
                       for udp is the packet size
        :param no_cpu_timed: if non zero will disable cpu collection and override
                       the time with the provided value - used mainly for udp
                       to find quickly the optimal throughput using short
                       tests at various throughput values
        :return: a list of 1 dictionary with the results (see parse_results())
        '''
        # run client using the default TCP window size (tcp window
        # scaling is normally enabled by default so setting explicit window
        # size is not going to help achieve better results)
        opts = ''
        multicast = protocol == 'Multicast'
        tcp = protocol == 'TCP'
        udp = protocol == 'UDP'
        if mss:
            opts += "-M" + str(mss)
        if reverse_dir:
            opts += " -F -r"
        if length:
            opts += " -l" + str(length)
        if self.instance.config.ipv6_mode:
            opts += " -6 "
        if multicast:
            opts += " -m32 -o -j -g" + self.instance.config.multicast_addr
        if not tcp:
            opts += " -u"
            # for UDP if the bandwidth is not provided we need to calculate
            # the optimal bandwidth
            if not bandwidth_kbps:
                udp_res = self.find_bdw(length, target_ip, protocol)
                if 'error' in udp_res:
                    return [udp_res]
                if not self.instance.gmond_svr:
                    # if we do not collect CPU we miught as well return
                    # the results found through iteration
                    return [udp_res]
                bandwidth_kbps = udp_res['throughput_kbps']
        if bandwidth_kbps:
            opts += " -R%sK" % (bandwidth_kbps)

        if no_cpu_timed:
            duration_sec = no_cpu_timed
        else:
            duration_sec = self.instance.get_cmd_duration()
        # use data port 5001 and control port 5002
        # must be enabled in the VM security group
        cmd = "%s -T%d %s -p5001 -P5002 -fparse %s" % (self.dest_path,
                                                       duration_sec,
                                                       opts,
                                                       target_ip)
        self.instance.buginf(cmd)
        try:
            if no_cpu_timed:
                # force the timeout value with 20 second extra for the command to
                # complete and do not collect CPU
                cpu_load = None
                cmd_out = self.instance.exec_command(cmd, duration_sec + 20)
            else:
                (cmd_out, cpu_load) = self.instance.exec_with_cpu(cmd)
        except sshutils.SSHError as exc:
            # Timout or any SSH error
            self.instance.display('SSH Error:' + str(exc))
            return [self.parse_error(protocol, str(exc))]

        if udp or multicast:
            # UDP output:
            # megabytes=1.1924 real_seconds=10.01 rate_Mbps=0.9997 tx_cpu=99 rx_cpu=0
            #      drop=0 pkt=1221 data_loss=0.00000
            re_udp = r'rate_Mbps=([\d\.]*) tx_cpu=\d* rx_cpu=\d* drop=(\-*\d*) pkt=(\d*)'
            if multicast:
                re_udp += r' data_loss=[\d\.]* msmaxjitter=([\d\.]*) msavgOWD=([\-\d\.]*)'
            match = re.search(re_udp, cmd_out)
            if match:
                rate_mbps = float(match.group(1))
                drop = float(match.group(2))
                pkt = int(match.group(3))
                jitter = None

                if multicast:
                    jitter = float(match.group(4))

                # Workaround for a bug of nuttcp that sometimes it will return a
                # negative number for drop.
                if drop < 0:
                    drop = 0

                return [self.parse_results(protocol,
                                           int(rate_mbps * 1024),
                                           lossrate=round(drop * 100 / pkt, 2),
                                           reverse_dir=reverse_dir,
                                           msg_size=length,
                                           cpu_load=cpu_load,
                                           jitter=jitter)]
        else:
            # TCP output:
            # megabytes=1083.4252 real_seconds=10.04 rate_Mbps=905.5953 tx_cpu=3 rx_cpu=19
            #      retrans=0 rtt_ms=0.55
            re_tcp = r'rate_Mbps=([\d\.]*) tx_cpu=\d* rx_cpu=\d* retrans=(\d*) rtt_ms=([\d\.]*)'
            match = re.search(re_tcp, cmd_out)
            if match:
                rate_mbps = float(match.group(1))
                retrans = int(match.group(2))
                rtt_ms = float(match.group(3))
                return [self.parse_results(protocol,
                                           int(rate_mbps * 1024),
                                           retrans=retrans,
                                           rtt_ms=rtt_ms,
                                           reverse_dir=reverse_dir,
                                           msg_size=length,
                                           cpu_load=cpu_load)]
        return [self.parse_error(protocol, 'Could not parse: %s' % (cmd_out))]
