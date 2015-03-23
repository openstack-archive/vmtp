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

class WrkTool(PerfTool):

    def __init__(self, instance, perf_tool_path):
        PerfTool.__init__(self, 'wrk-4.0.0', perf_tool_path, instance)

    def get_server_launch_cmd(self):
        '''This requires HTTP server is running already
        '''
        return None

    def run_client(self, target_url, threads, connections,
                   timeout=5, connetion_type='New',
                   no_cpu_timed=0):
        '''Run the test
        :return:  list containing one or more dictionary results
        '''

        duration_sec = self.instance.get_cmd_duration()

        # Set the ulimit to 1024000
        cmd = 'sudo sh -c "ulimit -n 102400 && exec su $LOGNAME -c \''
        cmd += '%s -t%d -c%d -d%ds --timeout %ds --latency %s; exit\'"' % \
            (self.dest_path, threads, connections, duration_sec,
             timeout, target_url)

        self.instance.display('Measuring HTTP performance...')
        self.instance.buginf(cmd)
        try:
            if no_cpu_timed:
                # force the timeout value with 20 seconds extra for the command to
                # complete and do not collect CPU
                cpu_load = None
                cmd_out = self.instance.exec_command(cmd, duration_sec + 20)
            else:
                (cmd_out, cpu_load) = self.instance.exec_with_cpu(cmd)
        except sshutils.SSHError as exc:
            # Timout or any SSH error
            self.instance.display('SSH Error:' + str(exc))
            return [self.parse_error(str(exc))]

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
            re_str = r'Requests/sec:\s+(\d+\.\d+)'
            http_rps = re.search(re_str, cmd_out).group(1)

            re_str = r'Transfer/sec:\s+(\d+\.\d+.B)'
            http_rates = re.search(re_str, cmd_out).group(1)
            # Uniform in unit MB
            ex_unit = 'KMG'.find(http_rates[-2])
            if ex_unit == -1:
                raise ValueError
            val = float(http_rates[0:-2])
            http_rates = float(val * (1024 ** (ex_unit)))

            re_str = r'Socket errors: connect (\d+), read (\d+), write (\d+), timeout (\d+)'
            http_sock_err = re.search(re_str, cmd_out)
            if http_sock_err:
                v1 = int(http_sock_err.group(1))
                v2 = int(http_sock_err.group(2))
                v3 = int(http_sock_err.group(3))
                v4 = int(http_sock_err.group(4))
                http_sock_err = v1 + v2 + v3 + v4
            else:
                http_sock_err = 0

            re_str = r'Non-2xx or 3xx responses: (\d+)'
            http_err = re.search(re_str, cmd_out)
            if http_err:
                http_err = http_err.group(1)
            else:
                http_err = 0
        except Exception:
            return self.parse_error('Could not parse: %s' % (cmd_out))

        return self.parse_results(http_rps=http_rps,
                                  http_rates=http_rates,
                                  http_sock_err=http_sock_err,
                                  http_err=http_err)
