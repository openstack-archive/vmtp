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

# Module for credentials in Openstack
import getpass
import os
import re

import log as logging

LOG = logging.getLogger(__name__)


class Credentials(object):

    def get_credentials(self):
        dct = {}
        dct['username'] = self.rc_username
        dct['password'] = self.rc_password
        dct['auth_url'] = self.rc_auth_url
        dct['tenant_name'] = self.rc_tenant_name
        return dct

    def get_nova_credentials(self):
        dct = {}
        dct['username'] = self.rc_username
        dct['api_key'] = self.rc_password
        dct['auth_url'] = self.rc_auth_url
        dct['project_id'] = self.rc_tenant_name
        return dct

    def get_nova_credentials_v2(self):
        dct = self.get_nova_credentials()
        dct['version'] = 2
        return dct

    def _init_with_openrc_(self, openrc_contents):
        export_re = re.compile('export OS_([A-Z_]*)="?(.*)')
        for line in openrc_contents.splitlines():
            line = line.strip()
            mstr = export_re.match(line)
            if mstr:
                # get rid of posible trailing double quote
                # the first one was removed by the re
                name = mstr.group(1)
                value = mstr.group(2)
                if value.endswith('"'):
                    value = value[:-1]
                # get rid of password assignment
                # echo "Please enter your OpenStack Password: "
                # read -sr OS_PASSWORD_INPUT
                # export OS_PASSWORD=$OS_PASSWORD_INPUT
                if value.startswith('$'):
                    continue
                # now match against wanted variable names
                if name == 'USERNAME':
                    self.rc_username = value
                elif name == 'AUTH_URL':
                    self.rc_auth_url = value
                elif name == 'TENANT_NAME':
                    self.rc_tenant_name = value

    # Read a openrc file and take care of the password
    # The 2 args are passed from the command line and can be None
    def __init__(self, openrc_file=None, openrc_contents=None, pwd=None, no_env=False):
        self.rc_password = None
        self.rc_username = None
        self.rc_tenant_name = None
        self.rc_auth_url = None
        self.openrc_contents = openrc_contents
        success = True

        if openrc_file:
            if os.path.exists(openrc_file):
                self.openrc_contents = open(openrc_file).read()
            else:
                LOG.error("rc file does not exist %s" % openrc_file)
                success = False
                return

        if self.openrc_contents:
            self._init_with_openrc_(self.openrc_contents)
        elif not no_env:
            # no openrc file passed - we assume the variables have been
            # sourced by the calling shell
            # just check that they are present
            for varname in ['OS_USERNAME', 'OS_AUTH_URL', 'OS_TENANT_NAME']:
                if varname not in os.environ:
                    LOG.warn("%s is missing" % varname)
                    success = False
            if success:
                self.rc_username = os.environ['OS_USERNAME']
                self.rc_auth_url = os.environ['OS_AUTH_URL']
                self.rc_tenant_name = os.environ['OS_TENANT_NAME']

        # always override with CLI argument if provided
        if pwd:
            self.rc_password = pwd
        # if password not know, check from env variable
        elif self.rc_auth_url and not self.rc_password and success:
            if 'OS_PASSWORD' in os.environ and not no_env:
                self.rc_password = os.environ['OS_PASSWORD']
            else:
                # interactively ask for password
                self.rc_password = getpass.getpass(
                    'Please enter your OpenStack Password: ')
        if not self.rc_password:
            self.rc_password = ""
