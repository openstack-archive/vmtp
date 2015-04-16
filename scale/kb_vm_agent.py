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

class KB_VM_Agent(object):

    def __init__(self, host, port=6379):
        self.redis_obj = redis.StrictRedis(host=host, port=port)
        self.pubsub = self.redis_obj.pubsub(ignore_subscribe_messages=True)
        self.hello_thread = None
        self.stop_hello = threading.Event()
        # Assumption:
        # Here we assume the vm_name is the same as the host name, which is
        # true if the VM is spawned by Kloud Buster.
        self.vm_name = socket.gethostname().lower()
        self.orches_chan_name = self.vm_name.lower() + "_orches"
        self.report_chan_name = self.vm_name.lower() + "_report"

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

    def exec_command(self, cmd):
        # Execute the command, and returns the outputs
        cmds = ['bash', '-c']
        cmds.append(cmd)
        p = subprocess.Popen(cmds, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        (stdout, stderr) = p.communicate()

        return (p.returncode, stdout, stderr)

    def report(self, result):
        self.redis_obj.publish(self.report_chan_name, result)

    def process_cmd(self, cmd_data):
        cmd_res_tuple = self.exec_command(cmd_data['cmd'])
        cmd_res_dict = dict(zip(("status", "stdout", "stderr"), cmd_res_tuple))
        cmd_res_dict['parser_cb'] = cmd_data['parser_cb']
        self.report(cmd_res_dict)

    def send_hello(self):
        # Sending "hello" message to master node every 2 seconds
        while not self.stop_hello.is_set():
            self.report("hello")
            time.sleep(2)

    def work(self):
        for item in self.pubsub.listen():
            if item['type'] != 'message':
                continue
            if item['data'] == 'iamhere':
                # When a "iamhere" packet is received, means the master node
                # acknowledged the current VM. So stopped sending more
                # "hello" packet to the master node.
                # Unfortunately, there is no thread.stop() in Python 2.x
                self.stop_hello.set()
                continue
            # Convert the string representation of dict to real dict obj
            cmd_data = eval(item['data'])
            self.process_cmd(cmd_data)

if __name__ == "__main__":

    if (len(sys.argv) <= 1):
        print("ERROR: Expecting the redis server address.")
        sys.exit(1)

    redis_server, redis_server_port = sys.argv[1].split(':', 1)
    agent = KB_VM_Agent(redis_server, redis_server_port)
    agent.setup_channels()
    agent.hello_thread = threading.Thread(target=agent.send_hello)
    agent.hello_thread.daemon = True
    agent.hello_thread.start()
    agent.work()
