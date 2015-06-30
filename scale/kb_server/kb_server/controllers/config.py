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

import os
import sys
kb_main_path = os.path.split(os.path.abspath(__file__))[0] + "/../../.."
sys.path.append(kb_main_path)

from kb_config import KBConfig
from pecan import expose

class ConfigController(object):

    def __init__(self):
        self.kb_config = KBConfig()
        self.cur_config = None

    @expose(generic=True)
    def default_config(self):
        def_config = self.kb_config.config_scale
        return str(def_config)

    @expose(generic=True)
    def current_config(self):
        return str(self.cur_config)

    @expose(generic=True)
    def status(self):
        return "RETURN CURRENT STATUS HERE"

    @status.when(method='PUT')
    def status_PUT(self, **kw):
        # @TODO(recursively update the config dictionary with the information
        # provided by application (client))
        return str(kw)
