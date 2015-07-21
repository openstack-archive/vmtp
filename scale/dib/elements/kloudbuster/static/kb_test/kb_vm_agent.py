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

import subprocess
import sys
import threading
import time

import redis

# Define the version of the KloudBuster agent.
#
# When VM is up running, the agent will send the READY message to the
# KloudBuster main program, along with its version. The main program
# will check the version to see whether the image meets the minimum
# requirements to run, and stopped with an error if not.
#
# Note: All majors are compatible regardless of minor.
__version__ = '1.0'

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
                      rate_limit, duration, timeout, connection_type,
                      report_interval):
        if not rate_limit:
            rate_limit = 65535
        cmd = '%s -t%d -c%d -R%d -d%ds -p%ds --timeout %ds -D2 -j %s' % \
              (dest_path, threads, connections, rate_limit, duration,
               report_interval, timeout, target_url)
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
        self.vm_name = user_data['vm_name']
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
            self.report('READY', None, __version__)
            time.sleep(2)

    def exec_command(self, cmd):
        # Execute the command, and returns the outputs
        cmds = ['bash', '-c']
        cmds.append(cmd)
        p = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout, stderr) = p.communicate()

        return (p.returncode, stdout, stderr)

    def exec_command_report(self, cmd):
        # Execute the command, reporting periodically, and returns the outputs
        cmd_res_dict = None
        cmds = ['bash', '-c']
        cmds.append(cmd)
        p_output = ''
        p = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        lines_iterator = iter(p.stdout.readline, b"")
        for line in lines_iterator:
            # One exception, if this is the very last report, we will send it
            # through "DONE" command, not "REPORT". So what's happening here
            # is to determine whether this is the last report.
            if cmd_res_dict:
                self.report('REPORT', 'http', cmd_res_dict)
                cmd_res_dict = None
                p_output = line
            else:
                p_output += line
                if line.strip() == "}":
                    cmd_res_dict = dict(zip(("status", "stdout", "stderr"), (0, p_output, '')))
                    continue

        stderr = p.communicate()[1]
        return (p.returncode, p_output, stderr)

    def process_cmd(self, message):
        if message['cmd'] == 'ACK':
            # When 'ACK' is received, means the master node
            # acknowledged the current VM. So stopped sending more
            # "hello" packet to the master node.
            # Unfortunately, there is no thread.stop() in Python 2.x
            self.stop_hello.set()
        elif message['cmd'] == 'EXEC':
            self.last_cmd = ""
            try:
                cmd_res_tuple = eval('self.exec_' + message['data']['cmd'] + '()')
                cmd_res_dict = dict(zip(("status", "stdout", "stderr"), cmd_res_tuple))
            except Exception as exc:
                cmd_res_dict = {
                    "status": 1,
                    "stdout": self.last_cmd,
                    "stderr": str(exc)
                }
            self.report('DONE', message['client-type'], cmd_res_dict)
        elif message['cmd'] == 'ABORT':
            # TODO(Add support to abort a session)
            pass
        else:
            # Unexpected
            # TODO(Logging on Agent)
            print 'ERROR: Unexpected command received!'
            pass

    def work(self):
        for item in self.pubsub.listen():
            if item['type'] != 'message':
                continue
            # Convert the string representation of dict to real dict obj
            message = eval(item['data'])
            self.process_cmd(message)

    def exec_setup_static_route(self):
        self.last_cmd = KB_Instance.get_static_route(self.user_data['target_subnet_ip'])
        result = self.exec_command(self.last_cmd)
        if (self.user_data['target_subnet_ip'] not in result[1]):
            self.last_cmd = KB_Instance.add_static_route(
                self.user_data['target_subnet_ip'],
                self.user_data['target_shared_interface_ip'])
            return self.exec_command(self.last_cmd)
        else:
            return (0, '', '')

    def exec_check_http_service(self):
        self.last_cmd = KB_Instance.check_http_service(self.user_data['target_url'])
        return self.exec_command(self.last_cmd)

    def exec_run_http_test(self):
        self.last_cmd = KB_Instance.run_http_test(
            dest_path=self.user_data['http_tool']['dest_path'],
            target_url=self.user_data['target_url'],
            **self.user_data['http_tool_configs'])
        return self.exec_command_report(self.last_cmd)

def exec_command(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = p.communicate()

    return p.returncode

def start_redis_server():
    cmd = ['sudo', 'service', 'redis-server', 'start']
    return exec_command(cmd)

def start_nuttcp_server():
    cmd = ['/usr/bin/nuttcp', '-P5002', '-S', '--single-threaded']
    return exec_command(cmd)

def start_nginx_server():
    cmd = ['sudo', 'service', 'nginx', 'start']
    return exec_command(cmd)

if __name__ == "__main__":
    try:
        f = open('user-data', 'r')
        user_data = eval(f.read())
    except Exception as e:
        # TODO(Logging on Agent)
        print e.message
        sys.exit(1)

    if 'role' not in user_data:
        sys.exit(1)

    if user_data['role'] == 'KB-PROXY':
        sys.exit(start_redis_server())
    if user_data['role'] == 'Server':
        rc1 = start_nuttcp_server()
        rc2 = start_nginx_server()
        sys.exit(rc1 or rc2)
    elif user_data['role'] == 'Client':
        agent = KB_VM_Agent(user_data)
        agent.setup_channels()
        agent.hello_thread = threading.Thread(target=agent.send_hello)
        agent.hello_thread.daemon = True
        agent.hello_thread.start()
        agent.work()
    else:
        sys.exit(1)
