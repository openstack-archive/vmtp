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
        self.client_dict = dict(zip([x.vm_name.lower() for x in client_list], client_list))
        self.config = config
        self.result = {}

        # Redis
        self.connection_pool = None
        self.redis_obj = None
        self.pubsub = None
        self.orches_chan_name = "kloudbuster_orches"
        self.report_chan_name = "kloudbuster_report"

    def setup_redis(self):
        self.redis_obj = redis.StrictRedis(connection_pool=self.connection_pool)
        # Check for connections to redis server
        for retry in xrange(1, self.config.redis_retry_count + 1):
            try:
                self.redis_obj.get("test")
            except (redis.exceptions.ConnectionError):
                LOG.warn("Connecting to redis server... Retry #%d", retry)
                time.sleep(1)
                continue
            break
        # Subscribe to message channel
        self.pubsub = self.redis_obj.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.report_chan_name)

    def send_cmd(self, cmd, client_type, data):
        message = {'cmd': cmd, 'sender-id': 'kb-master',
                   'client-type': client_type, 'data': data}
        LOG.kbdebug(message)
        self.redis_obj.publish(self.orches_chan_name, message)

    def polling_vms(self, timeout, polling_interval=None):
        '''
        Polling all VMs for the status of execution
        Guarantee to run once if the timeout is less than polling_interval
        '''
        if not polling_interval:
            polling_interval = self.config.polling_interval
        retry_count = max(timeout / polling_interval, 1)
        retry = cnt_succ = cnt_failed = 0
        clist = self.client_dict.copy()

        while (retry < retry_count and len(clist)):
            time.sleep(polling_interval)
            while True:
                msg = self.pubsub.get_message()
                if not msg:
                    # No new message, commands are in executing
                    break

                LOG.kbdebug(msg)
                payload = eval(msg['data'])
                vm_name = payload['sender-id']
                instance = self.client_dict[vm_name]
                if payload['cmd'] == 'READY':
                    # If a READY packet is received, the corresponding VM is up
                    # running. We mark the flag for that VM, and skip all READY
                    # messages received afterwards.
                    if instance.up_flag:
                        continue
                    else:
                        self.send_cmd('ACK', None, None)
                        clist[vm_name].up_flag = True
                        clist.pop(vm_name)
                        cnt_succ = cnt_succ + 1
                elif payload['cmd'] == 'DONE':
                    self.result[vm_name] = payload['data']
                    clist.pop(vm_name)
                    if self.result[vm_name]['status']:
                        # Command returned with non-zero status, command failed
                        cnt_failed = cnt_failed + 1
                    else:
                        # Command returned with zero, command succeed
                        cnt_succ = cnt_succ + 1

            LOG.info("%d Succeed, %d Failed, %d Pending... Retry #%d" %
                     (cnt_succ, cnt_failed, len(clist), retry))
            retry = retry + 1

        return (cnt_succ, cnt_failed, len(clist))

    def wait_for_vm_up(self, timeout=120):
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBVMUpException()

    def setup_static_route(self, timeout=10):
        func = {'cmd': 'setup_static_route'}
        self.send_cmd('EXEC', 'http', func)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBSetStaticRouteException()

    def check_http_service(self, timeout=60):
        func = {'cmd': 'check_http_service'}
        self.send_cmd('EXEC', 'http', func)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBHTTPServerUpException()

    def run_http_test(self):
        func = {'cmd': 'run_http_test'}
        self.send_cmd('EXEC', 'http', func)
        # Give additional 30 seconds for everybody to report results
        timeout = self.config.http_tool_configs.duration + 3000
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBHTTPBenchException()

        # Parse the results from HTTP Tools
        for key, instance in self.client_dict.items():
            self.result[key] = instance.http_client_parser(**self.result[key])

    def run(self):
        LOG.info("Setting up redis connection pool...")
        # For now, the redis server is not in the scope of Kloud Buster, which has to be
        # pre-configured before executing Kloud Buster.
        self.connection_pool = redis.ConnectionPool(
            host=self.config.redis_server, port=self.config.redis_server_port, db=0)

        try:
            LOG.info("Setting up the redis connections...")
            self.setup_redis()

            LOG.info("Waiting for agents on VMs to come up...")
            self.wait_for_vm_up()

            LOG.info("Setting up static route to reach tested cloud...")
            self.setup_static_route()

            LOG.info("Waiting for HTTP service to come up...")
            self.check_http_service()

            if self.config.prompt_before_run:
                print "Press enter to start running benchmarking tools..."
                raw_input()

            LOG.info("Starting HTTP Benchmarking...")
            self.run_http_test()
            for val in self.result.values():
                # TODO(Consolidating the data from all VMs)
                print val

        except (KBSetStaticRouteException):
            LOG.error("Could not set static route.")
            return
        except (KBHTTPServerUpException):
            LOG.error("HTTP service is not up in testing cloud.")
            return
        except KBHTTPBenchException():
            LOG.error("Error in HTTP benchmarking.")
            return
