#!/usr/bin/env python
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

# This is an example of tool that can represent VMTP json results in
# a nicer form using HTML and the Google Charts Javascript library
#


import argparse
import json
import os
import os.path
import sys
import webbrowser

__version__ = '0.0.1'

html_main_template = '''
<!DOCTYPE html>
<html>
  <head>
    <script type="text/javascript" src="https://www.google.com/jsapi"></script>
    <script type="text/javascript">
      google.load("visualization", "1.1", {packages:["bar", "table"]});
      google.setOnLoadCallback(drawChart);
      function drawChart() {
      var options;
      var data;
      var chart;
%s
      }
    </script>
  </head>
  <body>
    <table align="center">
%s
    </table>
  </body>
</html>
'''

js_options_tpl = '''
        var options = {
          chart: {
            title: 'OpenStack Data Plane Performance (Gbps)',
            subtitle: '%s',
          }
        };
'''

js_data_tpl = '''
        data = google.visualization.arrayToDataTable([
%s
        ]);
        chart = new %s(document.getElementById('vmtp-%s%d'));
        chart.draw(data, options);
'''

div_tpl = ' ' * 6 + \
          '<tr><td><div id="vmtp-%s%d" style="width:900px;height:500px;">' + \
          '</div></td></tr>\n'

# must be exact match
label_match = {
    'VM to VM same network fixed IP (inter-node)': 'L2',
    'VM to VM different network fixed IP (inter-node)': 'L3 fixed',
    'VM to VM different network floating IP (inter-node)': 'L3 floating',
    # This one is special because it is bidirectional
    'External-VM': ''
}

prop_match = {
    'cpu_info': 'CPU Info',
    'distro': 'Host Linux distribution',
    'date': 'Date',
    'nic_name': 'NIC name',
    'openstack_version': 'OpenStack release',
    'test_description': 'Description',
    'version': 'VMTP version',
    'encapsulation': 'Encapsulation',
    'l2agent_type': 'L2 agent type'
}

# what goes in the subtitle
subtitle_match = ['test_description', 'openstack_version', 'distro',
                  'encapsulation', 'l2agent_type']

class GoogleChartsBarChart(object):
    def __init__(self, results, protocols):
        self.results = results
        if protocols not in ['udp', 'tcp']:
            protocols = 'all'
        self.show_udp = protocols in ['all', 'udp']
        self.show_tcp = protocols in ['all', 'tcp']

    def _get_subtitle(self, res):
        sub = 'inter-node'
        for key in subtitle_match:
            if key in res:
                sub += ' ' + res[key].encode('ascii')
        return sub

    def _get_categories(self, flow):
        categories = ['Flow']
        # start with UDP first
        if self.show_udp:
            # iterate through all results in this flow to pick the sizes
            for flow_res in flow['results']:
                if flow_res['protocol'] == 'UDP':
                    categories.append('UDP ' + str(flow_res['pkt_size']))
        if self.show_tcp:
            categories.append('TCP')
        return categories

    def _get_flow_data(self, label, flow, reverse=False):
        data = [label]
        # start with UDP first
        if self.show_udp:
            # iterate through all results in this flow to pick the sizes
            for flow_res in flow['results']:
                reverse_flow = 'direction' in flow_res
                if reverse_flow != reverse:
                    continue
                if flow_res['protocol'] == 'UDP':
                    data.append(float(flow_res['throughput_kbps']) / (1024 * 1024))
        if self.show_tcp:
            # TCP may have multiple samples - pick the average for now
            res = []
            for flow_res in flow['results']:
                if reverse and 'direction' not in flow_res:
                    continue
                if flow_res['protocol'] == 'TCP':
                    res.append(float(flow_res['throughput_kbps']) / (1024 * 1024))
                    break
            if res:
                total_tp = 0
                for tp in res:
                    total_tp += tp
                data.append(total_tp / len(res))
        return data

    def _get_flows(self, flows):
        res = []
        for flow in flows:
            desc = flow['desc']
            if desc in label_match:
                if label_match[desc]:
                    res.append(self._get_flow_data(label_match[desc], flow))
                else:
                    # upload/download
                    res.append(self._get_flow_data('Upload', flow, reverse=False))
                    res.append(self._get_flow_data('Download', flow, reverse=True))
        return res

    def _get_js_options(self, res):
        subtitle = self._get_subtitle(res)
        return js_options_tpl % (subtitle)

    def _get_js_chart(self, chart_class, rows, chart_name, id):
        data = ''
        for row in rows:
            data += ' ' * 12 + str(row) + ',\n'
        return js_data_tpl % (data, chart_class, chart_name, id)

    def _get_js_data(self, flows, id):
        rows = [self._get_categories(flows[0])]
        rows.extend(self._get_flows(flows))
        return self._get_js_chart('google.charts.Bar', rows, 'chart', id)

    def _get_js_props(self, res, id):
        rows = [['Property', 'Value']]
        for key in prop_match:
            if key in res:
                rows.append([prop_match[key], res[key].encode('ascii', 'ignore')])
        return self._get_js_chart('google.visualization.Table', rows, 'table', id)

    def _get_js(self, res, id):
        js = ''
        js += self._get_js_options(res)
        js += self._get_js_data(res['flows'], id)
        # Add property table
        js += self._get_js_props(res, id)
        return js

    def _get_jss(self):
        js = ''
        id = 0
        for res in self.results:
            js += self._get_js(res, id)
            id += 1
        return js

    def _get_divs(self):
        divs = ''
        id = 0
        for _ in self.results:
            divs += div_tpl % ('chart', id)
            divs += div_tpl % ('table', id)
            id += 1
        return divs

    def _plot(self, dest):
        dest.write(html_main_template % (self._get_jss(), self._get_divs()))

    def plot(self, dest_file):
        with open(dest_file, 'w') as dest:
            print('Generating chart drawing code to ' + dest_file + '...')
            self._plot(dest)

def gen_chart(files, chart_dest, browser, protocols=''):
    results = []
    for ff in files:
        if not os.path.isfile(ff):
            print('Error: No such file %s: ' + ff)
            sys.exit(1)
        with open(ff) as data_file:
            res = json.load(data_file)
            results.append(res)

    chart = GoogleChartsBarChart(results, protocols.lower())
    chart.plot(chart_dest)
    if browser:
        url = 'file://' + os.path.abspath(chart_dest)
        webbrowser.open(url, new=2)

def main():
    parser = argparse.ArgumentParser(description='VMTP Chart Generator V' + __version__)

    parser.add_argument('-c', '--chart', dest='chart',
                        action='store',
                        help='create and save chart in html file',
                        metavar='<file>')

    parser.add_argument('-b', '--browser', dest='browser',
                        action='store_true',
                        default=False,
                        help='display (-c) chart in the browser')

    parser.add_argument('-p', '--protocol', dest='protocols',
                        action='store',
                        default='all',
                        help='select protocols:all, tcp, udp',
                        metavar='<all|tcp|udp>')

    parser.add_argument('-v', '--version', dest='version',
                        default=False,
                        action='store_true',
                        help='print version of this script and exit')

    parser.add_argument(dest='files',
                        help='vmtp json result file', nargs='+',
                        metavar='<file>')

    opts = parser.parse_args()

    if opts.version:
        print('Version ' + __version__)
        sys.exit(0)

    gen_chart(opts.files, opts.chart, opts.browser, opts.protocols)


if __name__ == '__main__':
    main()
