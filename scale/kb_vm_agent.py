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

import socket
import subprocess
import sys
import threading
import time

import redis

class KB_Instance(object):

    # Check whether the HTTP Service is up running
    @staticmethod
    def check_http_service(target_url):
        cmd = 'while true; do\n'
        cmd += 'curl --head %s --connect-timeout 2 --silent\n' % (target_url)
        cmd += 'if [ $? -eq 0 ]; then break; fi\n'
        cmd += 'done'
        return cmd

    # Add static route
    @staticmethod
    def add_static_route(network, next_hop_ip, if_name=None):
        debug_msg = "Adding static route %s with next hop %s" % (network, next_hop_ip)
        cmd = "sudo ip route add %s via %s" % (network, next_hop_ip)
        if if_name:
            debug_msg += " and %s" % if_name
            cmd += " dev %s" % if_name
        # TODO(Logging on Agent)
        print debug_msg
        return cmd

    # Get static route
    @staticmethod
    def get_static_route(network, next_hop_ip=None, if_name=None):
        cmd = "ip route show %s" % network
        if next_hop_ip:
            cmd += " via %s" % next_hop_ip
        if if_name:
            cmd += " dev %s" % if_name
        return cmd

    # Delete static route
    @staticmethod
    def delete_static_route(network, next_hop_ip=None, if_name=None):
        debug_msg = "Deleting static route %s" % network
        cmd = "sudo ip route del %s" % network
        if next_hop_ip:
            debug_msg = " with next hop %s" % next_hop_ip
            cmd += " via %s" % next_hop_ip
        if if_name:
            if next_hop_ip:
                debug_msg = " and %s" % if_name
            else:
                debug_msg = "with next hop %s" % if_name
            cmd += " dev %s" % if_name
        # TODO(Logging on Agent)
        print debug_msg
        return cmd

    # Run the HTTP benchmarking tool
    @staticmethod
    def run_http_test(dest_path, target_url, threads, connections,
                      duration, timeout, connection_type):
        cmd = '%s -t%d -c%d -d%ds --timeout %ds --latency %s' % \
            (dest_path, threads, connections, duration, timeout, target_url)
        return cmd


class KB_VM_Agent(object):

    def __init__(self, user_data):
        host = user_data['redis_server']
        port = user_data['redis_server_port']
        self.user_data = user_data
        self.redis_obj = redis.StrictRedis(host=host, port=port)
        self.pubsub = self.redis_obj.pubsub(ignore_subscribe_messages=True)
        self.hello_thread = None
        self.stop_hello = threading.Event()
        # Assumption:
        # Here we assume the vm_name is the same as the host name (lower case),
        # which is true if the VM is spawned by Kloud Buster.
        self.vm_name = socket.gethostname().lower()
        self.orches_chan_name = "kloudbuster_orches"
        self.report_chan_name = "kloudbuster_report"
        self.last_cmd = None

    def setup_channels(self):
        # Check for connections to redis server
        while (True):
            try:
                self.redis_obj.get("test")
            except (redis.exceptions.ConnectionError):
                time.sleep(1)
                continue
            break

        # Subscribe to orchestration channel
        self.pubsub.subscribe(self.orches_chan_name)

    def report(self, cmd, client_type, data):
        message = {'cmd': cmd, 'sender-id': self.vm_name,
                   'client-type': client_type, 'data': data}
        self.redis_obj.publish(self.report_chan_name, message)

    def send_hello(self):
        # Sending "hello" message to master node every 2 seconds
        while not self.stop_hello.is_set():
            self.report('READY', None, None)
            time.sleep(2)

    def exec_command(self, cmd):
        # Execute the command, and returns the outputs
        cmds = ['bash', '-c']
        cmds.append(cmd)
        p = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout, stderr) = p.communicate()

        return (p.returncode, stdout, stderr)

    def process_cmd(self, msg):
        if msg['cmd'] == 'ACK':
            # When 'ACK' is received, means the master node
            # acknowledged the current VM. So stopped sending more
            # "hello" packet to the master node.
            # Unfortunately, there is no thread.stop() in Python 2.x
            self.stop_hello.set()
        elif msg['cmd'] == 'EXEC':
            self.last_cmd = ""
            try:
                cmd_res_tuple = eval('self.exec_' + msg['data']['cmd'] + '()')
                cmd_res_dict = dict(zip(("status", "stdout", "stderr"), cmd_res_tuple))
            except Exception as exc:
                cmd_res_dict = {
                    "status": 1,
                    "stdout": self.last_cmd,
                    "stderr": str(exc)
                }
            self.report('DONE', msg['client-type'], cmd_res_dict)
        elif msg['cmd'] == 'ABORT':
            # TODO(Add support to abort a session)
            pass

    def work(self):
        for item in self.pubsub.listen():
            if item['type'] != 'message':
                continue
            # Convert the string representation of dict to real dict obj
            msg = eval(item['data'])
            self.process_cmd(msg)

    def exec_setup_static_route(self):
        self.last_cmd = KB_Instance.get_static_route(self.user_data['target_subnet_ip'])
        result = self.exec_command(self.last_cmd)
        if (self.user_data['target_subnet_ip'] not in result[1]):
            self.last_cmd = \
                KB_Instance.add_static_route(self.user_data['target_subnet_ip'],
                                             self.user_data['target_shared_interface_ip'])
            return self.exec_command(self.last_cmd)
        else:
            return (0, '', '')

    def exec_check_http_service(self):
        self.last_cmd = KB_Instance.check_http_service(self.user_data['target_url'])
        return self.exec_command(self.last_cmd)

    def exec_run_http_test(self):
        self.last_cmd = \
            KB_Instance.run_http_test(dest_path=self.user_data['http_tool']['dest_path'],
                                      target_url=self.user_data['target_url'],
                                      **self.user_data['http_tool_configs'])
        return self.exec_command(self.last_cmd)


if __name__ == "__main__":

    try:
        f = open('/var/tmp/user-data', 'r')
        user_data = eval(f.read())
    except Exception as e:
        # TODO(Logging on Agent)
        print e.message
        sys.exit(1)

    agent = KB_VM_Agent(user_data)
    agent.setup_channels()
    agent.hello_thread = threading.Thread(target=agent.send_hello)
    agent.hello_thread.daemon = True
    agent.hello_thread.start()
    agent.work()
