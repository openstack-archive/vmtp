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
import locale
import os
import os.path
import sys
import webbrowser
from jinja2 import FileSystemLoader
from jinja2 import Environment

__version__ = '0.0.1'
kb_html_tpl = "./kb_tpl.jinja"

def get_formatted_num(value):
    return locale.format("%d", value, grouping=True)

# List of fields to format with thousands separators
fields_to_format = ['rps_max', 'rps', 'http_sock_err', 'total_server_vm',
                    'http_total_req', 'total_connections']

def format_numbers(results):
    for key in results.keys():
        if key in fields_to_format:
            print 'format:' + key
            results[key] = get_formatted_num(results[key])

def get_progress_vars(name, cur_value, max_value):
    tpl_vars = {
        name: cur_value,
        name + "_max": max_value,
        name + "_percent": (cur_value * 100) / max_value,
        }
    return tpl_vars

class KbReport(object):
    def __init__(self, results):
        self.results = results
        template_loader = FileSystemLoader(searchpath=".")
        template_env = Environment(loader=template_loader)
        self.tpl = template_env.get_template(kb_html_tpl)

    def get_template_vars(self):
        rx_tp = float(self.results['http_throughput_kbytes'])
        rx_tp = round(rx_tp * 8 / (1024 * 1024), 1)
        tpl_vars = get_progress_vars('rx', rx_tp, 10)
        self.results.update(tpl_vars)

        rps = self.results['http_rps']
        rps_max = self.results['http_rate_limit'] * self.results['total_client_vms']
        tpl_vars = get_progress_vars('rps', rps, rps_max)
        self.results.update(tpl_vars)

        # tweak the latency percentile information so that the X value
        # maps to the modified log scale
        # The X value to use is 1/(1 - percentile)
        latency_list = self.results['latency_stats']
        mod_latency_list = []
        for latency_pair in latency_list:
            x_value = round(100 / (100 - latency_pair[0]), 1)
            # conert from usec to msec
            latency_ms = latency_pair[1] / 1000
            mod_latency_list.append([x_value, latency_ms])
        self.results['latency_stats'] = mod_latency_list
        return self.results

    def plot(self, dest_file):
        with open(dest_file, 'w') as dest:
            print('Generating chart drawing code to ' + dest_file + '...')
            tpl_vars = self.get_template_vars()
            format_numbers(tpl_vars)
            output = self.tpl.render(tpl_vars)
            dest.write(output)

def gen_chart(res_file, chart_dest, browser):
    if not os.path.isfile(res_file):
        print('Error: No such file %s: ' + res_file)
        sys.exit(1)
    with open(res_file) as data_file:
        results = json.load(data_file)
        chart = KbReport(results)
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

    parser.add_argument(dest='file',
                        help='KloudBuster json result file',
                        metavar='<file>')

    opts = parser.parse_args()

    if opts.version:
        print('Version ' + __version__)
        sys.exit(0)

    locale.setlocale(locale.LC_ALL, 'en_US')
    gen_chart(opts.file, opts.chart, opts.browser)
