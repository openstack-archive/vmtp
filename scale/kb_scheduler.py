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

import time

import log as logging
import redis

LOG = logging.getLogger(__name__)

class KBSetStaticRouteException(Exception):
    pass

class KBHTTPServerUpException(Exception):
    pass

class KBHTTPBenchException(Exception):
    pass

class KBScheduler(object):
    """
    Control the testing VMs on the testing cloud
    """

    def __init__(self, client_list, config):
        self.client_list = client_list
        self.config = config
        self.result = {}
        self.redis_connection_pool = None

    def polling_vms(self, timeout):
        '''
        Polling all VMs for the status of execution
        '''
        total_vm = len(self.client_list)
        polling_interval = self.config.polling_interval
        self.result = {}
        cnt_succ = cnt_failed = cnt_exec = 0
        for retry_count in xrange(timeout / polling_interval):
            time.sleep(polling_interval)
            for instance in self.client_list:
                msg = instance.redis_get_message()
                self.result[instance.vm_name] = msg
                if not msg:
                    # No new message, command in executing
                    continue
                elif msg[0]:
                    # Command returned with non-zero status, command failed
                    cnt_failed = cnt_failed + 1
                else:
                    # Command returned with zero, command succeed
                    cnt_succ = cnt_succ + 1

            cnt_exec = total_vm - cnt_succ - cnt_failed
            LOG.info("%d Succeed, %d Failed, %d Executing... Retry %d#" %
                     (cnt_succ, cnt_failed, cnt_exec, retry_count))
            if (cnt_exec == 0):
                break

        return (cnt_succ, cnt_failed, cnt_exec)

    def wait_for_vm_up(self):
        polling_interval = self.config.polling_interval
        total_vm = len(self.client_list)
        up_count = 0
        while (up_count != total_vm):
            for instance in self.client_list:
                instance.redis_obj.publish(instance.incoming_chan_name, "hello")
            time.sleep(polling_interval)
            for instance in self.client_list:
                instance.redis_get_message()
                if instance.up_flag:
                    up_count = up_count + 1
            LOG.info("%d/%d VM(s) are up running..." % (up_count, total_vm))

    def setup_static_route(self, timeout=10):
        for instance in self.client_list:
            svr = instance.target_server
            instance.add_static_route(svr.subnet_ip, svr.shared_interface_ip)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBSetStaticRouteException()

    def check_http_server_up(self, timeout=60):
        polling_interval = self.config.polling_interval
        for retry_count in xrange(timeout / polling_interval):
            for instance in self.client_list:
                instance.check_http_service()
            cnt_succ = self.polling_vms(polling_interval)[0]
            if cnt_succ == len(self.client_list):
                return

        raise KBHTTPServerUpException()

    def run_http_test(self):
        for instance in self.client_list:
            instance.run_http_client(threads=2, connections=5000, timeout=5,
                                     connection_type="Keep-alive")
        # Give additional 30 seconds for everybody to reporting results
        timeout = self.config.time + 30
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBHTTPBenchException()

    def run(self):
        LOG.info("Setting up redis connection pool...")
        self.redis_connection_pool = redis.ConnectionPool(
            host=self.config.redis_server, port=self.config.redis_server_port, db=0)

        try:
            LOG.info("Setting up the redis connections...")
            for instance in self.client_list:
                instance.setup_redis(connection_pool=self.redis_connection_pool)

            LOG.info("Waiting for agents on VMs to come up...")
            self.wait_for_vm_up()

            LOG.info("Setting up static route to reach tested cloud...")
            self.setup_static_route()

            LOG.info("Waiting for HTTP service to come up...")
            self.check_http_server_up()

            LOG.info("Starting HTTP Benchmarking...")
            self.run_http_test()
            for key in self.result:
                print "[%s] %s" % (key, self.result[key][1])

        except (KBSetStaticRouteException):
            LOG.error("ERROR: Could not set static route.")
            return
        except (KBHTTPServerUpException):
            LOG.error("ERROR: HTTP Server is not up in testing cloud.")
            return
        except KBHTTPBenchException():
            LOG.error("ERROR: Error in HTTP benchmarking.")
            return
