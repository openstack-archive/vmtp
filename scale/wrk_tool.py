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

    def __init__(self, instance, cfg_http_tool):
        PerfTool.__init__(self, instance, cfg_http_tool)

    def cmd_run_client(self, target_url, threads, connections,
                       rate_limit=0, timeout=5, connetion_type='Keep-alive'):
        '''
        Return the command for running the benchmarking tool
        '''
        duration_sec = self.instance.config.http_tool_configs.duration
        if not rate_limit:
            rate_limit = 65535
        cmd = '%s -t%d -c%d -R%d -d%ds --timeout %ds --latency -s kb.lua %s' % \
            (self.dest_path, threads, connections, rate_limit,
             duration_sec, timeout, target_url)
        LOG.kbdebug("[%s] %s" % (self.instance.vm_name, cmd))
        return cmd

    def cmd_parser_run_client(self, status, stdout, stderr):
        if status:
            return self.parse_error(stderr)

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
            http_total_req = int(re.search(total_req_str, stdout).group(1))

            re_str = r'Requests/sec:\s+(\d+\.\d+)'
            http_rps = float(re.search(re_str, stdout).group(1))

            re_str = r'Transfer/sec:\s+(\d+\.\d+.B)'
            http_tp_kbytes = re.search(re_str, stdout).group(1)
            # Uniform in unit MB
            ex_unit = 'KMG'.find(http_tp_kbytes[-2])
            if ex_unit == -1:
                raise ValueError
            val = float(http_tp_kbytes[0:-2])
            http_tp_kbytes = float(val * (1024 ** (ex_unit)))

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

            re_str = r'__START_KLOUDBUSTER_DATA__\n(((.*)\n)*)__END_KLOUDBUSTER_DATA__'
            latency_stats = re.search(re_str, stdout).group(1).split()
            latency_stats = [(float(x.split(',')[0]), int(x.split(',')[1])) for x in latency_stats]
        except Exception:
            return self.parse_error('Could not parse: %s' % (stdout))

        return self.parse_results(http_total_req=http_total_req,
                                  http_rps=http_rps,
                                  http_tp_kbytes=http_tp_kbytes,
                                  http_sock_err=http_sock_err,
                                  http_err=http_err,
                                  latency_stats=latency_stats)

    @staticmethod
    def consolidate_results(results):
        all_res = {'tool': 'wrk'}
        total_count = len(results)
        if not total_count:
            return all_res

        for key in ['http_rps', 'http_total_req', 'http_sock_err', 'http_throughput_kbytes']:
            all_res[key] = 0
            for item in results:
                if (key in item['results']):
                    all_res[key] += item['results'][key]
            all_res[key] = int(all_res[key])

        if 'latency_stats' in results[0]['results']:
            all_res['latency_stats'] = []
            first_result = results[0]['results']['latency_stats']
            latency_counts = len(first_result)

        for i in range(latency_counts):
            latency_avg = 0
            for item in results:
                latency_avg += item['results']['latency_stats'][i][1]
            latency_avg = int(latency_avg / total_count)
            latency_tup = (first_result[i][0], latency_avg)
            all_res['latency_stats'].append(latency_tup)

        return all_res
