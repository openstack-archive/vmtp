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
#

import abc

import log as logging

LOG = logging.getLogger(__name__)


# A base class for all tools that can be associated to an instance
class PerfTool(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self, instance, tool_cfg):
        self.name = tool_cfg.name
        self.instance = instance
        self.dest_path = tool_cfg.dest_path
        self.pid = None

    # Terminate pid if started
    def dispose(self):
        if self.pid:
            # Terminate the iperf server
            LOG.kbdebug("[%s] Terminating %s" % (self.instance.vm_name,
                                                 self.name))
            self.instance.ssh.kill_proc(self.pid)
            self.pid = None

    def parse_error(self, msg):
        return {'error': msg, 'tool': self.name}

    def parse_results(self, protocol=None, throughput=None, lossrate=None, retrans=None,
                      rtt_ms=None, reverse_dir=False, msg_size=None, cpu_load=None,
                      http_total_req=None, http_rps=None, http_tp_kbytes=None,
                      http_sock_err=None, http_sock_timeout=None, http_err=None,
                      latency_stats=None):
        res = {'tool': self.name}
        if throughput is not None:
            res['throughput_kbps'] = throughput
        if protocol is not None:
            res['protocol'] = protocol
        if 'vm_bandwidth' in self.instance.config:
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
        if http_total_req:
            res['http_total_req'] = http_total_req
        if http_rps:
            res['http_rps'] = http_rps
        if http_tp_kbytes:
            res['http_throughput_kbytes'] = http_tp_kbytes
        if http_sock_err:
            res['http_sock_err'] = http_sock_err
        if http_sock_timeout:
            res['http_sock_timeout'] = http_sock_timeout
        if http_err:
            res['http_err'] = http_err
        if latency_stats:
            res['latency_stats'] = latency_stats
        return res

    @abc.abstractmethod
    def cmd_run_client(**kwargs):
        # must be implemented by sub classes
        return None

    @abc.abstractmethod
    def cmd_parser_run_client(self, status, stdout, stderr):
        # must be implemented by sub classes
        return None

    @staticmethod
    @abc.abstractmethod
    def consolidate_results(results):
        # must be implemented by sub classes
        return None

    def find_udp_bdw(self, pkt_size, target_ip):
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
                                           udp=True, length=pkt_size,
                                           no_cpu_timed=1)
            # always pick the first element in the returned list of dict(s)
            # should normally only have 1 element
            res = res_list[0]
            if 'error' in res:
                return res
            loss_rate = res['loss_rate']
            measured_kbps = res['throughput_kbps']
            LOG.kbdebug(
                "[%s] pkt-size=%d throughput=%d<%d/%d<%d Kbps loss-rate=%d" %
                (self.instance.vm_name, pkt_size, min_kbps, measured_kbps,
                 kbps, max_kbps, loss_rate))
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
                # LOG.info("   undershot, min=%d kbps=%d max=%d" % (min_kbps,  kbps, max_kbps))
            elif loss_rate > max_loss_rate:
                # overshot
                max_kbps = kbps
                if measured_kbps < kbps:
                    kbps = measured_kbps
                else:
                    kbps = int((max_kbps + min_kbps) / 2)
                # LOG.info("   overshot, min=%d kbps=%d max=%d" % (min_kbps,  kbps, max_kbps))
            else:
                # converged within loss rate bracket
                break
        return res
