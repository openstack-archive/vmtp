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

import re

import log as logging

from perf_tool import PerfTool

LOG = logging.getLogger(__name__)


class WrkTool(PerfTool):

    def __init__(self, instance):
        PerfTool.__init__(self, 'wrk-4.0.1', instance)

    def cmd_run_client(self, target_url, threads, connections,
                       timeout=5, connetion_type='Keep-alive', retry_count=10):
        '''
        Return the command for running the benchmarking tool
        '''
        duration_sec = self.instance.config.exec_time
        cmd = '%s -t%d -c%d -d%ds --timeout %ds --latency %s' % \
            (self.dest_path, threads, connections, duration_sec, timeout, target_url)
        LOG.kbdebug("[%s] %s" % (self.instance.vm_name, cmd))
        return cmd

    def cmd_parser_run_client(self, status, stdout, stderr):
        if status:
            return [self.parse_error(stderr)]
        # Sample Output:
        # Running 10s test @ http://192.168.1.1/index.html
        #   8 threads and 5000 connections
        #   Thread Stats   Avg      Stdev     Max   +/- Stdev
        #     Latency   314.97ms  280.34ms 999.98ms   74.05%
        #     Req/Sec   768.45    251.19     2.61k    74.47%
        #   Latency Distribution
        #      50%  281.43ms
        #      75%  556.37ms
        #      90%  790.04ms
        #      99%  969.79ms
        #   61420 requests in 10.10s, 2.79GB read
        #   Socket errors: connect 0, read 0, write 0, timeout 10579
        #   Non-2xx or 3xx responses: 828
        # Requests/sec:   6080.66
        # Transfer/sec:    282.53MB
        try:
            total_req_str = r'(\d+)\srequests\sin'
            http_total_req = re.search(total_req_str, stdout).group(1)

            re_str = r'Requests/sec:\s+(\d+\.\d+)'
            http_rps = re.search(re_str, stdout).group(1)

            re_str = r'Transfer/sec:\s+(\d+\.\d+.B)'
            http_rates_kbytes = re.search(re_str, stdout).group(1)
            # Uniform in unit MB
            ex_unit = 'KMG'.find(http_rates_kbytes[-2])
            if ex_unit == -1:
                raise ValueError
            val = float(http_rates_kbytes[0:-2])
            http_rates_kbytes = float(val * (1024 ** (ex_unit)))

            re_str = r'Socket errors: connect (\d+), read (\d+), write (\d+), timeout (\d+)'
            http_sock_err = re.search(re_str, stdout)
            if http_sock_err:
                v1 = int(http_sock_err.group(1))
                v2 = int(http_sock_err.group(2))
                v3 = int(http_sock_err.group(3))
                v4 = int(http_sock_err.group(4))
                http_sock_err = v1 + v2 + v3 + v4
            else:
                http_sock_err = 0

            re_str = r'Non-2xx or 3xx responses: (\d+)'
            http_err = re.search(re_str, stdout)
            if http_err:
                http_err = http_err.group(1)
            else:
                http_err = 0
        except Exception:
            return self.parse_error('Could not parse: %s' % (stdout))

        return self.parse_results(http_total_req=http_total_req,
                                  http_rps=http_rps,
                                  http_rates_kbytes=http_rates_kbytes,
                                  http_sock_err=http_sock_err,
                                  http_err=http_err)
