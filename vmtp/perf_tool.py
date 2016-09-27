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

import abc
import re
import six

from log import LOG
from pkg_resources import resource_filename

# where to copy the tool on the target, must end with slash
SCP_DEST_DIR = '/tmp/'

#
# A base class for all tools that can be associated to an instance
#
@six.add_metaclass(abc.ABCMeta)
class PerfTool(object):

    def __init__(self, name, instance):
        self.name = name
        self.instance = instance
        self.dest_path = SCP_DEST_DIR + name
        self.pid = None

    # install the tool to the instance
    # returns False if fail, True if success
    def install(self):
        self.instance.display('Installing %s...' % (self.name))
        local_path = resource_filename(__name__, 'tools/%s' % (self.name))
        return self.instance.scp(self.name, local_path, self.dest_path)

    @abc.abstractmethod
    def get_server_launch_cmd(self):
        '''To be implemented by sub-classes.'''
        return None

    def start_server(self):
        '''Launch the server side of this tool
        :return: True if success, False if error
        '''
        # check if server is already started
        if not self.pid:
            self.pid = self.instance.ssh.pidof(self.name)
        if not self.pid:
            cmd_list = self.get_server_launch_cmd()
            # Start the tool server
            self.instance.buginf('Starting %s server...' % (self.name))
            for launch_cmd in cmd_list:
                launch_out = self.instance.exec_command(launch_cmd)
            self.pid = self.instance.ssh.pidof(self.name)
        else:
            self.instance.buginf('%s server already started pid=%s' % (self.name, self.pid))
        if self.pid:
            return True
        else:
            self.instance.display('Cannot launch server %s: %s' % (self.name, launch_out))
            return False

    # Terminate pid if started
    def dispose(self):
        if self.pid:
            # Terminate the iperf server
            self.instance.buginf('Terminating %s', self.name)
            self.instance.ssh.kill_proc(self.pid)
            self.pid = None

    def parse_error(self, proto, msg):
        return {'protocol': proto, 'error': msg, 'tool': self.name}

    def parse_results(self, protocol, throughput, lossrate=None, retrans=None,
                      rtt_ms=None, reverse_dir=False,
                      msg_size=None,
                      cpu_load=None, jitter=None):
        res = {'throughput_kbps': throughput,
               'protocol': protocol,
               'tool': self.name}
        if self.instance.config.vm_bandwidth:
            res['bandwidth_limit_kbps'] = self.instance.config.vm_bandwidth
        if lossrate is not None:
            res['loss_rate'] = lossrate
        if retrans:
            res['retrans'] = retrans
        if rtt_ms:
            res['rtt_ms'] = rtt_ms
        if reverse_dir:
            res['direction'] = 'reverse'
        if msg_size:
            res['pkt_size'] = msg_size
        if cpu_load:
            res['cpu_load'] = cpu_load
        if jitter:
            res['jitter'] = jitter
        return res

    @abc.abstractmethod
    def run_client_dir(self, target_ip,
                       mss,
                       reverse_dir=False,
                       bandwidth_kbps=0,
                       protocol="TCP",
                       length=0,
                       no_cpu_timed=0):
        # must be implemented by sub classes
        return None

    def find_bdw(self, pkt_size, target_ip, protocol="UDP"):
        '''Find highest UDP bandwidth within max loss rate for given packet size
        :return: a dictionary describing the optimal bandwidth (see parse_results())
        '''
        # we use a binary search to converge to the optimal throughput
        # start with 5Gbps - mid-range between 1 and 10Gbps
        # Convergence can be *very* tricky because UDP throughput behavior
        # can vary dramatically between host runs and guest runs.
        # The packet rate limitation is going to dictate the effective
        # send rate, meaning that small packet sizes will yield the worst
        # throughput.
        # The measured throughput can be vastly smaller than the requested
        # throughput even when the loss rate is zero when the sender cannot
        # send fast enough to fill the network, in that case increasing the
        # requested rate will not make it any better
        # Examples:
        # 1. too much difference between requested/measured bw - regardless of loss rate
        #    => retry with bw mid-way between the requested bw and the measured bw
        # /tmp/nuttcp-7.3.2 -T2  -u -l128 -R5000000K -p5001 -P5002 -fparse 192.168.1.2
        # megabytes=36.9785 real_seconds=2.00 rate_Mbps=154.8474 tx_cpu=23 rx_cpu=32
        #         drop=78149 pkt=381077 data_loss=20.50746
        # /tmp/nuttcp-7.3.2 -T2  -u -l128 -R2500001K -p5001 -P5002 -fparse 192.168.1.2
        # megabytes=47.8063 real_seconds=2.00 rate_Mbps=200.2801 tx_cpu=24 rx_cpu=34
        #         drop=0 pkt=391629 data_loss=0.00000
        # 2. measured and requested bw are very close :
        #   if loss_rate is too low
        #     increase bw mid-way between requested and last max bw
        #   if loss rate is too high
        #     decrease bw mid-way between the measured bw and the last min bw
        #   else stop iteration (converged)
        # /tmp/nuttcp-7.3.2 -T2  -u -l8192 -R859376K -p5001 -P5002 -fparse 192.168.1.2
        # megabytes=204.8906 real_seconds=2.00 rate_Mbps=859.2992 tx_cpu=99 rx_cpu=10
        #           drop=0 pkt=26226 data_loss=0.00000

        min_kbps = 1
        max_kbps = 10000000
        kbps = 5000000
        min_loss_rate = self.instance.config.udp_loss_rate_range[0]
        max_loss_rate = self.instance.config.udp_loss_rate_range[1]
        # stop if the remaining range to cover is less than 5%
        while (min_kbps * 100 / max_kbps) < 95:
            res_list = self.run_client_dir(target_ip, 0, bandwidth_kbps=kbps,
                                           protocol=protocol, length=pkt_size,
                                           no_cpu_timed=1)
            # always pick the first element in the returned list of dict(s)
            # should normally only have 1 element
            res = res_list[0]
            if 'error' in res:
                return res
            loss_rate = res['loss_rate']
            measured_kbps = res['throughput_kbps']
            self.instance.buginf('pkt-size=%d throughput=%d<%d/%d<%d Kbps loss-rate=%d' %
                                 (pkt_size, min_kbps, measured_kbps, kbps, max_kbps, loss_rate))
            # expected rate must be at least 80% of the requested rate
            if (measured_kbps * 100 / kbps) < 80:
                # the measured bw is too far away from the requested bw
                # take half the distance or 3x the measured bw whichever is lowest
                kbps = measured_kbps + (kbps - measured_kbps) / 2
                if measured_kbps:
                    kbps = min(kbps, measured_kbps * 3)
                max_kbps = kbps
                continue
            # The measured bw is within striking distance from the requested bw
            # increase bw if loss rate is too small
            if loss_rate < min_loss_rate:
                # undershot
                if measured_kbps > min_kbps:
                    min_kbps = measured_kbps
                else:
                    # to make forward progress we need to increase min_kbps
                    # and try a higher bw since the loss rate is too low
                    min_kbps = int((max_kbps + min_kbps) / 2)

                kbps = int((max_kbps + min_kbps) / 2)
                LOG.debug('   undershot, min=%d kbps=%d max=%d', min_kbps, kbps, max_kbps)
            elif loss_rate > max_loss_rate:
                # overshot
                max_kbps = kbps
                if measured_kbps < kbps:
                    kbps = measured_kbps
                else:
                    kbps = int((max_kbps + min_kbps) / 2)
                LOG.debug('   overshot, min=%d kbps=%d max=%d', min_kbps, kbps, max_kbps)
            else:
                # converged within loss rate bracket
                break
        return res

    def get_proto_profile(self):
        '''Return a tuple containing the list of protocols (tcp/udp) and
        list of packet sizes (udp only)
        '''
        # start with TCP (protocol="TCP") then UDP
        proto_list = []
        proto_pkt_sizes = []
        if 'T' in self.instance.config.protocols:
            proto_list.append('TCP')
            proto_pkt_sizes.append(self.instance.config.tcp_pkt_sizes)
        if 'U' in self.instance.config.protocols:
            proto_list.append('UDP')
            proto_pkt_sizes.append(self.instance.config.udp_pkt_sizes)
        if 'M' in self.instance.config.protocols:
            proto_list.append('Multicast')
            proto_pkt_sizes.append(self.instance.config.udp_pkt_sizes)
        return (proto_list, proto_pkt_sizes)

class PingTool(PerfTool):
    '''
    A class to run ping and get loss rate and round trip time
    '''

    def __init__(self, instance):
        PerfTool.__init__(self, 'ping', instance)

    def _run_client(self, target_ip, ping_count, size=32):
        '''Perform the ping operation
        :return: a dict containing the results stats

        Example of output:
            10 packets transmitted, 10 packets received, 0.0% packet loss
            round-trip min/avg/max/stddev = 55.855/66.074/103.915/13.407 ms
        or
            5 packets transmitted, 5 received, 0% packet loss, time 3998ms
            rtt min/avg/max/mdev = 0.455/0.528/0.596/0.057 ms
        '''
        if self.instance.config.ipv6_mode:
            ping_cmd = "ping6"
        else:
            ping_cmd = "ping"
        cmd = "%s -c %d -s %d %s" % (ping_cmd, ping_count, size, target_ip)
        cmd_out = self.instance.exec_command(cmd)
        if not cmd_out:
            res = {'packet_size': size,
                   'error': 'ping failed'}
            return res
        match = re.search(r'(\d*) packets transmitted, (\d*) ',
                          cmd_out)
        if match:
            tx_packets = match.group(1)
            rx_packets = match.group(2)
        else:
            tx_packets = 0
            rx_packets = 0
        match = re.search(r'min/avg/max/[a-z]* = ([\d\.]*)/([\d\.]*)/([\d\.]*)/([\d\.]*)',
                          cmd_out)
        if match:
            rtt_min = match.group(1)
            rtt_avg = match.group(2)
            rtt_max = match.group(3)
            rtt_stddev = match.group(4)
        else:
            rtt_min = 0
            rtt_max = 0
            rtt_avg = 0
            rtt_stddev = 0
        res = {'packet_size': size,
               'tx_packets': tx_packets,
               'rx_packets': rx_packets,
               'rtt_min_ms': rtt_min,
               'rtt_max_ms': rtt_max,
               'rtt_avg_ms': rtt_avg,
               'rtt_stddev': rtt_stddev}
        return res

    def run_client(self, target_ip, ping_count=10):
        size_results = []
        res = {'protocol': 'ICMP',
               'tool': 'ping',
               'results': size_results}
        size_list = self.instance.config.icmp_pkt_sizes
        for size in size_list:
            size_results.append(self._run_client(target_ip, ping_count, size))
        return res

    def get_server_launch_cmd(self):
        # not applicable
        return None

    def run_client_dir(self, target_ip,
                       mss,
                       reverse_dir=False,
                       bandwidth_kbps=0,
                       protocol="TCP",
                       length=0,
                       no_cpu_timed=0):
        # not applicable
        return None
