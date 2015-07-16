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

from distutils.version import LooseVersion
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

class KBProxyConnectionException(Exception):
    pass

class KBRunner(object):
    """
    Control the testing VMs on the testing cloud
    """

    def __init__(self, client_list, config, required_agent_version, single_cloud=True):
        self.client_dict = dict(zip([x.vm_name for x in client_list], client_list))
        self.config = config
        self.single_cloud = single_cloud
        self.result = {}
        self.host_stats = {}
        self.tool_result = {}
        self.required_agent_version = str(required_agent_version)
        self.agent_version = None

        # Redis
        self.redis_obj = None
        self.pubsub = None
        self.orches_chan_name = "kloudbuster_orches"
        self.report_chan_name = "kloudbuster_report"

    def setup_redis(self, redis_server, redis_server_port=6379, timeout=120):
        LOG.info("Setting up the redis connections...")
        connection_pool = redis.ConnectionPool(
            host=redis_server, port=redis_server_port, db=0)

        self.redis_obj = redis.StrictRedis(connection_pool=connection_pool,
                                           socket_connect_timeout=1,
                                           socket_timeout=1)
        success = False
        retry_count = max(timeout / self.config.polling_interval, 1)
        # Check for connections to redis server
        for retry in xrange(retry_count):
            try:
                self.redis_obj.get("test")
                success = True
            except (redis.exceptions.ConnectionError):
                LOG.info("Connecting to redis server... Retry #%d/%d", retry, retry_count)
                time.sleep(self.config.polling_interval)
                continue
            break
        if not success:
            LOG.error("Error: Cannot connect to the Redis server")
            raise KBProxyConnectionException()

        # Subscribe to message channel
        self.pubsub = self.redis_obj.pubsub(ignore_subscribe_messages=True)
        self.pubsub.subscribe(self.report_chan_name)

    def dispose(self):
        if self.pubsub:
            self.pubsub.unsubscribe()
            self.pubsub.close()

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
        samples = []
        http_tool = self.client_dict.values()[0].http_tool

        while (retry < retry_count and len(clist)):
            time.sleep(polling_interval)
            sample_count = 0
            while True:
                msg = self.pubsub.get_message()
                if not msg:
                    # No new message, commands are in executing
                    break

                LOG.kbdebug(msg)
                payload = eval(msg['data'])
                vm_name = payload['sender-id']
                instance = self.client_dict[vm_name]
                cmd = payload['cmd']
                if cmd == 'READY':
                    # If a READY packet is received, the corresponding VM is up
                    # running. We mark the flag for that VM, and skip all READY
                    # messages received afterwards.
                    if instance.up_flag:
                        continue
                    else:
                        clist[vm_name].up_flag = True
                        clist.pop(vm_name)
                        cnt_succ = cnt_succ + 1
                        self.agent_version = payload['data']
                elif cmd == 'REPORT':
                    sample_count = sample_count + 1
                    # Parse the results from HTTP Tools
                    instance = self.client_dict[vm_name]
                    self.result[vm_name] = instance.http_client_parser(**payload['data'])
                    samples.append(self.result[vm_name])
                elif cmd == 'DONE':
                    self.result[vm_name] = payload['data']
                    clist.pop(vm_name)
                    if self.result[vm_name]['status']:
                        # Command returned with non-zero status, command failed
                        LOG.error("[%s] %s", vm_name, self.result[vm_name]['stderr'])
                        cnt_failed = cnt_failed + 1
                    else:
                        # Command returned with zero, command succeed
                        cnt_succ = cnt_succ + 1
                elif cmd == 'DEBUG':
                    LOG.info('[%s] %s' + (vm_name, payload['data']))
                else:
                    LOG.error('[%s] received invalid command: %s' + (vm_name, cmd))

            log_msg = "%d Succeed, %d Failed, %d Pending... Retry #%d" %\
                      (cnt_succ, cnt_failed, len(clist), retry)
            if sample_count != 0:
                log_msg += " (%d sample(s) received)" % sample_count
            LOG.info(log_msg)

            if sample_count != 0:
                print http_tool.consolidate_samples(samples, len(self.client_dict))
                samples = []
            retry = retry + 1

        return (cnt_succ, cnt_failed, len(clist))

    def wait_for_vm_up(self, timeout=300):
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBVMUpException()
        self.send_cmd('ACK', None, None)

    def setup_static_route(self, timeout=30):
        func = {'cmd': 'setup_static_route'}
        self.send_cmd('EXEC', 'http', func)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBSetStaticRouteException()

    def check_http_service(self, timeout=30):
        func = {'cmd': 'check_http_service'}
        self.send_cmd('EXEC', 'http', func)
        cnt_succ = self.polling_vms(timeout)[0]
        if cnt_succ != len(self.client_dict):
            raise KBHTTPServerUpException()

    def run_http_test(self):
        func = {'cmd': 'run_http_test'}
        self.send_cmd('EXEC', 'http', func)
        # Give additional 30 seconds for everybody to report results
        timeout = self.config.http_tool_configs.duration + 30
        cnt_pending = self.polling_vms(timeout)[2]
        if cnt_pending != 0:
            LOG.warn("Testing VMs are not returning results within grace period, "
                     "summary shown below may not be accurate!")

        # Parse the results from HTTP Tools
        for key, instance in self.client_dict.items():
            self.result[key] = instance.http_client_parser(**self.result[key])

    def gen_host_stats(self):
        for vm in self.result.keys():
            phy_host = self.client_dict[vm].host
            if phy_host not in self.host_stats:
                self.host_stats[phy_host] = []
            self.host_stats[phy_host].append(self.result[vm])

        http_tool = self.client_dict.values()[0].http_tool
        for phy_host in self.host_stats:
            self.host_stats[phy_host] = http_tool.consolidate_results(self.host_stats[phy_host])

    def run(self):
        try:
            LOG.info("Waiting for agents on VMs to come up...")
            self.wait_for_vm_up()
            if not self.agent_version:
                self.agent_version = "0.0"
            if (LooseVersion(self.agent_version) < LooseVersion(self.required_agent_version)):
                LOG.error("The VM image you are running is too old (%s), the minimum version "
                          "required is %s.x. Please build the image from latest repository." %
                          (self.agent_version, self.required_agent_version))
                return
            if self.single_cloud:
                LOG.info("Setting up static route to reach tested cloud...")
                self.setup_static_route()

            LOG.info("Waiting for HTTP service to come up...")
            self.check_http_service()

            if self.config.prompt_before_run:
                print "Press enter to start running benchmarking tools..."
                raw_input()

            LOG.info("Running HTTP Benchmarking...")
            self.run_http_test()

            # Call the method in corresponding tools to consolidate results
            http_tool = self.client_dict.values()[0].http_tool
            LOG.kbdebug(self.result.values())
            self.tool_result = http_tool.consolidate_results(self.result.values())
            self.tool_result['http_rate_limit'] = self.config.http_tool_configs.rate_limit
            self.tool_result['total_connections'] =\
                len(self.client_dict) * self.config.http_tool_configs.connections
            self.gen_host_stats()
        except (KBSetStaticRouteException):
            LOG.error("Could not set static route.")
            return
        except (KBHTTPServerUpException):
            LOG.error("HTTP service is not up in testing cloud.")
            return
        except KBHTTPBenchException():
            LOG.error("Error in HTTP benchmarking.")
            return
