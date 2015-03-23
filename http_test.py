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

import configure

from perf_instance import PerfInstance
from wrk_tool import WrkTool

####################################################
# Only invoke the module directly for test purposes.
####################################################

config = configure.Configuration.from_file("cfg.default.yaml").configure()
config.gmond_svr_ip = None
config.gmond_svr_port = None
config.protocols = "I"
config.tp_tool = None
config.http_tool = WrkTool
config.time = 10
config.debug = True
perf_instance = PerfInstance("http_test", config)
perf_instance.setup_ssh("172.29.87.189", "ubuntu")
wrktool = WrkTool(perf_instance, "./tools")
print wrktool.run_client("http://192.168.1.1/index.html", 8, 10000)
