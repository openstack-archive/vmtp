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

# A tool that can represent KloudBuster json results in
# a nicer form using HTML5, bootstrap.js and the Google Charts Javascript library
#


import argparse
import json
import os
import os.path
import sys
import webbrowser

from jinja2 import Environment
from jinja2 import FileSystemLoader

__version__ = '0.0.1'
kb_html_tpl = "./kb_tpl.jinja"

def get_formatted_num(value):
    return '{:,}'.format(value)

# table column names
col_names = ['<i class="glyphicon glyphicon-file"></i> File',
             '<i class="glyphicon glyphicon-random"></i> Connections',
             '<i class="glyphicon glyphicon-book"></i> Server VMs',
             '<i class="glyphicon glyphicon-transfer"></i> Requests',
             '<i class="glyphicon glyphicon-fire"></i> Socket errors',
             '<i class="glyphicon glyphicon-time"></i> RPS measured',
             '<i class="glyphicon glyphicon-pencil"></i> RPS requested',
             '<i class="glyphicon glyphicon-cloud-download"></i> RX throughput (Gbps)']

def get_new_latency_tuples():
    '''Returns a list of lists initializedas follows
    The latency tuples must be formatted like this:
    ['Percentile', 'fileA', 'fileB'],
    [2.0, 1, 3],
    [4.0, 27, 38],
    etc, with the first column being calculated from the percentile
    using the formula (1/(1-percentile))
    50% -> 1/0.5 = 2
    75% -> 4
    etc...
    This horizontal scaling is used to stretch the chart at the top end
    (towards 100%)
    '''
    return [
        ['Percentile'],  # add run file name
        [2],             # add run 50% latency
        [4],             # add run 75% latency
        [10],
        [100],
        [1000],
        [10000],
        [100000]         # add run 99.999% latency
    ]

class KbReport(object):
    def __init__(self, data_list, line_rate):
        self.data_list = data_list
        self.latency_tuples = get_new_latency_tuples()
        self.common_stats = []
        self.table = None
        template_loader = FileSystemLoader(searchpath=".")
        template_env = Environment(loader=template_loader)
        self.tpl = template_env.get_template(kb_html_tpl)
        self.line_rate = line_rate

    def add_latency_stats(self, run_results):
        # init a column list
        column = [run_results['filename']]
        for latency_pair in run_results['latency_stats']:
            # convert from usec to msec
            latency_ms = latency_pair[1] / 1000
            column.append(latency_ms)
        # and append that column to the latency list
        for pct_list, colval in zip(self.latency_tuples, column):
            pct_list.append(colval)

    def prepare_table(self):
        table = {}
        table['col_names'] = col_names
        # add values for each row
        rows = []
        for run_res in self.data_list:
            rps_max = run_res['http_rate_limit'] * run_res['total_client_vms']
            rx_tp = float(run_res['http_throughput_kbytes'])
            rx_tp = round(rx_tp * 8 / (1024 * 1024), 1)
            cells = [run_res['filename'],
                     get_formatted_num(run_res['total_connections']),
                     get_formatted_num(run_res['total_server_vms']),
                     get_formatted_num(run_res['http_total_req']),
                     get_formatted_num(run_res['http_sock_err'] + run_res['http_sock_timeout']),
                     get_formatted_num(run_res['http_rps']),
                     get_formatted_num(rps_max)]
            row = {'cells': cells,
                   'rx': {'value': rx_tp,
                          'max': self.line_rate,
                          'percent': (rx_tp * 100) / self.line_rate}}
            rows.append(row)
        table['rows'] = rows
        self.table = table

    def plot(self, dest_file):
        for run_results in self.data_list:
            self.add_latency_stats(run_results)

        self.prepare_table()
        kbstats = {
            'table': self.table,
            'latency_tuples': self.latency_tuples,
            'search_page': 'true' if len(self.data_list) > 10 else 'false'
        }
        with open(dest_file, 'w') as dest:
            print('Generating chart drawing code to ' + dest_file + '...')
            output = self.tpl.render(kbstats=kbstats)
            dest.write(output)

def get_display_file_name(filename):
    res = os.path.basename(filename)
    # remove extension
    res, _ = os.path.splitext(res)
    return res

def guess_line_rate(data_list):
    max_tp_kb = 0
    for data_list in data_list:
        max_tp_kb = max(max_tp_kb, data_list['http_throughput_kbytes'])
    max_tp_gb = (max_tp_kb * 8) / (1000 * 1000)
    # typical GE line rates are 10, 40 and 100
    if max_tp_gb < 10:
        return 10
    if max_tp_gb < 40:
        return 40
    return 100

def gen_chart(file_list, chart_dest, browser, line_rate):

    data_list = []
    for res_file in file_list:
        print 'processing: ' + res_file
        if not os.path.isfile(res_file):
            print('Error: No such file %s: ' + res_file)
            sys.exit(1)
        with open(res_file) as data_file:
            results = json.load(data_file)
            results['filename'] = get_display_file_name(res_file)
            data_list.append(results)
    if not line_rate:
        line_rate = guess_line_rate(data_list)
    print line_rate
    chart = KbReport(data_list, line_rate)
    print('Generating report to ' + chart_dest + '...')
    chart.plot(chart_dest)
    if browser:
        url = 'file://' + os.path.abspath(chart_dest)
        webbrowser.open(url, new=2)

def get_absolute_path_for_file(file_name):
    '''
    Return the filename in absolute path for any file
    passed as relateive path.
    '''
    abs_file = os.path.dirname(os.path.abspath(__file__))
    return abs_file + '/' + file_name

if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='KloudBuster Chart Generator V' + __version__)

    parser.add_argument('-c', '--chart', dest='chart',
                        action='store',
                        help='create and save chart in html file',
                        metavar='<file>')

    parser.add_argument('-b', '--browser', dest='browser',
                        action='store_true',
                        default=False,
                        help='display (-c) chart in the browser')

    parser.add_argument('-v', '--version', dest='version',
                        default=False,
                        action='store_true',
                        help='print version of this script and exit')

    parser.add_argument('-l', '--line-rate', dest='line_rate',
                        action='store',
                        default=0,
                        type=int,
                        help='line rate in Gbps (default=10)',
                        metavar='<rate-Gbps>')

    parser.add_argument(dest='files',
                        help='KloudBuster json result file', nargs="+",
                        metavar='<file>')

    opts = parser.parse_args()

    if opts.version:
        print('Version ' + __version__)
        sys.exit(0)

    gen_chart(opts.files, opts.chart, opts.browser, opts.line_rate)
