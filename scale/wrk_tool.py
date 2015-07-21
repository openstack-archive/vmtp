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

import json

from perf_tool import PerfTool

from hdrh.histogram import HdrHistogram
import log as logging

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
        cmd = '%s -t%d -c%d -R%d -d%ds --timeout %ds -D2 -j %s' % \
            (self.dest_path, threads, connections, rate_limit,
             duration_sec, timeout, target_url)
        LOG.kbdebug("[%s] %s" % (self.instance.vm_name, cmd))
        return cmd

    def cmd_parser_run_client(self, status, stdout, stderr):
        if status:
            return self.parse_error(stderr)

        # Sample Output:
        # {
        # "seq": 1,
        # "latency": {
        #     "min": 509440, "max": 798720,
        #     "counters": [
        #         8, [1990, 1, 2027, 1],
        #         9, [1032, 1, 1058, 1, 1085, 1, 1093, 1, 1110, 1, 1111, 1,
        #         1128, 1, 1129, 1, 1146, 1, 1147, 1, 1148, 1, 1165, 1, 1166, 1, 1169, 1,
        #         1172, 1, 1182, 1, 1184, 1, 1187, 1, 1191, 1, 1201, 1, 1203, 1, 1206, 1,
        #         1209, 1, 1219, 1, 1221, 1, 1223, 1, 1235, 1, 1237, 1, 1239, 1, 1242, 1,
        #         1255, 1, 1257, 1, 1260, 1, 1276, 1, 1282, 1, 1286, 1, 1294, 1, 1308, 1,
        #         1312, 1, 1320, 1, 1330, 1, 1334, 1, 1346, 1, 1349, 1, 1352, 1, 1364, 1,
        #         1374, 1, 1383, 1, 1401, 1, 1427, 1, 1452, 1, 1479, 1, 1497, 1, 1523, 1,
        #         1541, 1, 1560, 1]
        #     ]
        # },
        # "errors": {"read": 1},
        # "total_req": 58, "rps": 28.97, "rx_bps": "1.48MB"
        # }

        try:
            result = json.loads(stdout)
            http_total_req = int(result['total_req'])
            http_rps = float(result['rps'])
            http_tp_kbytes = result['rx_bps']
            # Uniform in unit MB
            ex_unit = 'KMG'.find(http_tp_kbytes[-2])
            if ex_unit == -1:
                raise ValueError
            val = float(http_tp_kbytes[0:-2])
            http_tp_kbytes = float(val * (1024 ** (ex_unit)))

            if 'errors' in result:
                errs = []
                for key in ['connect', 'read', 'write', 'timeout', 'http_error']:
                    if key in result['errors']:
                        errs.append(int(result['errors'][key]))
                    else:
                        errs.append(0)
                http_sock_err = errs[0] + errs[1] + errs[2]
                http_sock_timeout = errs[3]
                http_err = errs[4]
            else:
                http_sock_err = 0
                http_sock_timeout = 0
                http_err = 0

            latency_stats = result['latency']
        except Exception:
            return self.parse_error('Could not parse: "%s"' % (stdout))

        return self.parse_results(http_total_req=http_total_req,
                                  http_rps=http_rps,
                                  http_tp_kbytes=http_tp_kbytes,
                                  http_sock_err=http_sock_err,
                                  http_sock_timeout=http_sock_timeout,
                                  http_err=http_err,
                                  latency_stats=latency_stats)

    @staticmethod
    def consolidate_results(results):
        all_res = {'tool': 'wrk2'}
        total_count = len(results)
        if not total_count:
            return all_res

        for key in ['http_rps', 'http_total_req', 'http_sock_err',
                    'http_sock_timeout', 'http_throughput_kbytes']:
            all_res[key] = 0
            for item in results:
                if (key in item['results']):
                    all_res[key] += item['results'][key]
            all_res[key] = int(all_res[key])


        if 'latency_stats' in results[0]['results']:
            # for item in results:
            #     print item['results']['latency_stats']
            all_res['latency_stats'] = []
            histogram = HdrHistogram(1, 3600 * 1000 * 1000, 2)
            for item in results:
                histogram.add_bucket_counts(item['results']['latency_stats'])
            perc_list = [50, 75, 90, 99, 99.9, 99.99, 99.999]
            latency_dict = histogram.get_percentile_to_value_dict(perc_list)
            for key, value in latency_dict.iteritems():
                all_res['latency_stats'].append([key, value])
            all_res['latency_stats'].sort()

        return all_res

    @staticmethod
    def consolidate_samples(results, vm_count):
        all_res = WrkTool.consolidate_results(results)
        total_count = len(results) / vm_count
        if not total_count:
            return all_res

        all_res['http_rps'] = all_res['http_rps'] / total_count
        all_res['http_throughput_kbytes'] = all_res['http_throughput_kbytes'] / total_count
        return all_res
