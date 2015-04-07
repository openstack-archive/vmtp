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

import threading
import traceback

import sshutils

class KBSetStaticRouteException(Exception):
    pass

class KBScheduler(object):
    """
    Control the slave nodes on the testing cloud
    """

    """
    The code below are mostly a temporary solution, which assumes all testing
    clients have their own floating IP. However, this is usually not ture for
    a real use case.

    Will replace below code. and take advantage of kafka framework
    """

    def __init__(self, kb_master=None):
        self.kb_master = kb_master
        self.client_status = {}
        self.client_result = {}

    def check_server_httpd(self, instance, retry_count=30):
        '''
        Check the target server is up running
        '''
        cmd = 'curl --head %s --connect-timeout 2' % (instance.target_url)
        for retry in range(1, retry_count):
            try:
                (status, _, _) = instance.exec_command(cmd)
            except Exception as e:
                traceback.print_exc()
                self.client_status[instance.vm_name] = "ERROR: %s" % e.message
                return
            if not status:
                return
            print "[%s] Waiting for HTTP Server to come up... Retry %d#" %\
                (instance.vm_name, retry)

    def setup_static_route(self, instance):
        svr = instance.target_server
        if not svr.fip_ip:
            rc = instance.add_static_route(svr.subnet_ip, svr.shared_interface_ip)
            if rc > 0:
                print "Failed to add static route, error code: %i." % rc
                raise KBSetStaticRouteException()
            if svr.subnet_ip not in instance.get_static_route(svr.subnet_ip):
                print "Failed to get static route for %s." % svr.subnet_ip
                raise KBSetStaticRouteException()
            if not instance.ping_check(svr.fixed_ip, 2, 80):
                print "Failed to ping server %%." % svr.fixed_ip
                raise KBSetStaticRouteException()

    def setup_testing_env(self, instance):
        try:
            instance.setup_ssh(instance.fip_ip, "ubuntu")
            self.setup_static_route(instance)
            self.check_server_httpd(instance)
        except (sshutils.SSHError):
            self.client_status[instance.vm_name] = "ERROR: Could not setup SSH Session."
            return
        except (KBSetStaticRouteException):
            self.client_status[instance.vm_name] = "ERROR: Could not set static route."
            return

    def run_test(self, instance):
        try:
            self.client_result[instance.vm_name] =\
                instance.run_http_client(threads=2, connections=5000,
                                         timeout=5, connection_type="Keep-alive")
        except Exception as e:
            traceback.print_exc()
            self.client_status[instance.vm_name] = "ERROR: %s" % e.message

    def run(self, client_list):
        # Wait for kb_master and all clients to come up
        # if not self.check_up_with_sshd(self.kb_master):
        #     raise
        thread_list = []
        error_flag = False

        print "Setting up the testing environments..."
        for cur_client in client_list:
            self.client_status[cur_client.vm_name] = "Success"
            t = threading.Thread(target=self.setup_testing_env, args=[cur_client])
            thread_list.append(t)
            t.start()
        for cur_thread in thread_list:
            cur_thread.join()
        for cur_client in client_list:
            vm_name = cur_client.vm_name
            if self.client_status[vm_name] != "Success":
                error_flag = True
            print("%s: %s" % (vm_name, self.client_status[vm_name]))
        if error_flag:
            raise

        print "TEST STARTED"

        for cur_client in client_list:
            thread_list = []
            self.client_status[cur_client.vm_name] = "Success"
            t = threading.Thread(target=self.run_test, args=[cur_client])
            thread_list.append(t)
            t.start()
        for cur_thread in thread_list:
            cur_thread.join()
        for cur_client in client_list:
            vm_name = cur_client.vm_name
            if self.client_status[vm_name] == "Success":
                print ("%s: %s" % (vm_name, self.client_result[vm_name]))
            else:
                print ("%s: %s" % (vm_name, self.client_status[vm_name]))
