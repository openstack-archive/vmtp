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

from config import ConfigController
from pecan import abort
from pecan import expose

class APIController(object):
    @expose()
    def _lookup(self, primary_key, *remainder):
        if primary_key == "config":
            return ConfigController(), remainder
        else:
            abort(404)

class RootController(object):
    @expose()
    def _lookup(self, primary_key, *remainder):
        if primary_key == "api":
            return APIController(), remainder
        else:
            abort(404)
