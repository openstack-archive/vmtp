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

class KBVMUpException(Exception):
    pass

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

    def polling_vms(self, timeout, polling_interval=None):
        '''
        Polling all VMs for the status of execution
        Guarantee to run once if the timeout is less than polling_interval

        If retry_func is not None, we will keep trying the command even it failed.
        '''
        if not polling_interval:
            polling_interval = self.config.polling_interval
        retry_count = max(timeout / polling_interval, 1)
        retry = cnt_succ = cnt_failed = 0
        clist = self.client_list

        while (retry < retry_count and len(clist)):
            time.sleep(polling_interval)
            for instance in clist:
                msg = instance.redis_get_message()
                if not msg:
                    # No new message, command in executing
                    continue
                elif msg[0]:
                    # Command returned with non-zero status, command failed
                    cnt_failed = cnt_failed + 1
                else:
                    # Command returned with zero, command succeed
                    cnt_succ = cnt_succ + 1
                # Current instance finished execution
                self.result[instance.vm_name] = msg
                clist = [x for x in clist if x != instance]

            LOG.info("%d Succeed, %d Failed, %d Pending... Retry #%d" %
                     (cnt_succ, cnt_failed, len(clist), retry))
            retry = retry + 1

        return (cnt_succ, cnt_failed, len(clist))

    def wait_for_vm_up(self, timeout=120):
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBVMUpException()

    def setup_static_route(self, timeout=10):
        for instance in self.client_list:
            svr = instance.target_server
            instance.add_static_route(svr.subnet_ip, svr.shared_interface_ip)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBSetStaticRouteException()

    def check_http_server_up(self, timeout=60):
        for instance in self.client_list:
            instance.check_http_service()
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBHTTPServerUpException()

    def run_http_test(self):
        for instance in self.client_list:
            instance.run_http_client(threads=2, connections=5000, timeout=5,
                                     connection_type="Keep-alive")
        # Give additional 30 seconds for everybody to report results
        timeout = self.config.exec_time + 30
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_list):
            raise KBHTTPBenchException()

    def run(self):
        LOG.info("Setting up redis connection pool...")
        # For now, the redis server is not in the scope of Kloud Buster, which has to be
        # pre-configured before executing Kloud Buster.
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

            if self.config.prompt_before_run:
                print "Press enter to start running benchmarking tools..."
                raw_input()

            LOG.info("Starting HTTP Benchmarking...")
            self.run_http_test()
            for key in self.result:
                # TODO(Consolidating the data from all VMs)
                print "[%s] %s" % (key, self.result[key][1])

        except (KBSetStaticRouteException):
            LOG.error("Could not set static route.")
            return
        except (KBHTTPServerUpException):
            LOG.error("HTTP service is not up in testing cloud.")
            return
        except KBHTTPBenchException():
            LOG.error("Error in HTTP benchmarking.")
            return
