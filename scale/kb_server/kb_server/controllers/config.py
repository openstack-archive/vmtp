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

from credentials import Credentials

from configure import Configuration
from kb_config import KBConfig
from pecan import expose
from pecan import response

class ConfigController(object):

    def __init__(self):
        self.kb_config = KBConfig()
        self.status = 'READY'
        self.def_config = self.kb_config.config_scale

    @expose(generic=True)
    def default_config(self):
        return str(self.def_config)

    @expose(generic=True)
    def running_config(self):
        return str(self.kb_config.config_scale)

    @running_config.when(method='POST')
    def running_config_POST(self, args):
        try:
            # Expectation:
            # {
            #  'credentials': {'tested_rc': '<STRING>', 'passwd_tested': '<STRING>',
            #                  'testing_rc': '<STRING>', 'passwd_testing': '<STRING>'},
            #  'kb_cfg': {<USER_OVERRIDED_CONFIGS>},
            #  'topo_cfg': {<TOPOLOGY_CONFIGS>}
            #  'tenants_cfg': {<TENANT_AND_USER_LISTS_FOR_REUSING>}
            # }
            user_config = eval(args)

            # Parsing credentials from application input
            cred_config = user_config['credentials']
            cred_tested = Credentials(openrc_contents=cred_config['tested_rc'],
                                      pwd=cred_config['passwd_tested'])
            if ('testing_rc' in cred_config and
               cred_config['testing_rc'] != cred_config['tested_rc']):
                cred_testing = Credentials(openrc_contents=cred_config['testing_rc'],
                                           pwd=cred_config['passwd_testing'])
            else:
                # Use the same openrc file for both cases
                cred_testing = cred_tested

            # Parsing server and client configs from application input
            # Save the public key into a temporary file
            if 'public_key' in user_config['kb_cfg']:
                pubkey_filename = '/tmp/kb_public_key.pub'
                f = open(pubkey_filename, 'w')
                f.write(user_config['kb_cfg']['public_key_file'])
                f.close()
                self.kb_config.config_scale['public_key_file'] = pubkey_filename

            alt_config = Configuration.from_string(user_config['kb_cfg']).configure()
            self.kb_config.config_scale = self.kb_config.config_scale.merge(alt_config)

            # Parsing topology configs from application input
            if 'topo_cfg' in user_config:
                topo_cfg = Configuration.from_string(user_config['topo_cfg']).configure()
            else:
                topo_cfg = None

            # Parsing tenants configs from application input
            if 'tenants_list' in user_config:
                tenants_list = Configuration.from_string(user_config['tenants_list']).configure()
            else:
                tenants_list = None
        except Exception as e:
            response.status = 403
            response.text = "Error while parsing configurations: %s" % e.message
            return response.text

        self.kb_config.init_with_rest_api(cred_tested=cred_tested,
                                          cred_testing=cred_testing,
                                          topo_cfg=topo_cfg,
                                          tenants_list=tenants_list)
        return str(self.kb_config.config_scale)

    @expose(generic=True)
    def status(self):
        return "RETURN CURRENT STATUS HERE"

    @status.when(method='PUT')
    def status_PUT(self, **kw):
        # @TODO(recursively update the config dictionary with the information
        # provided by application (client))
        return str(kw)
