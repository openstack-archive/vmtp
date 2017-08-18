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
from keystoneauth1.identity import v2
from keystoneauth1.identity import v3
from keystoneauth1 import session
import os
import re

from log import LOG

class Credentials(object):

    def get_credentials(self):
        dct = {}
        dct['username'] = self.rc_username
        dct['password'] = self.rc_password
        dct['auth_url'] = self.rc_auth_url
        if self.rc_identity_api_version == 3:
            dct['project_name'] = self.rc_project_name
            dct['project_domain_name'] = self.rc_project_domain_name
            dct['user_domain_name'] = self.rc_user_domain_name
        else:
            dct['tenant_name'] = self.rc_tenant_name
        return dct

    def get_session(self):
        dct = {
            'username': self.rc_username,
            'password': self.rc_password,
            'auth_url': self.rc_auth_url
        }

        if self.rc_identity_api_version == 3:
            dct.update({
                'project_name': self.rc_project_name,
                'project_domain_name': self.rc_project_domain_name,
                'user_domain_name': self.rc_user_domain_name
            })
            auth = v3.Password(**dct)
        else:
            dct.update({
                'tenant_name': self.rc_tenant_name
            })
            auth = v2.Password(**dct)
        return session.Session(auth=auth, verify=self.rc_cacert)

    #
    # Read a openrc file and take care of the password
    # The 2 args are passed from the command line and can be None
    #
    def __init__(self, openrc_file, pwd, no_env):
        self.rc_password = None
        self.rc_username = None
        self.rc_tenant_name = None
        self.rc_auth_url = None
        self.rc_cacert = None
        self.rc_region_name = None
        self.rc_project_name = None
        self.rc_project_domain_name = None
        self.rc_user_domain_name = None
        self.rc_identity_api_version = 2
        success = True

        if openrc_file:
            if os.path.exists(openrc_file):
                export_re = re.compile('export OS_([A-Z_]*)="?(.*)')
                for line in open(openrc_file):
                    mstr = export_re.match(line.strip())
                    if mstr:
                        # get rif of posible trailing double quote
                        # the first one was removed by the re
                        name, value = mstr.group(1), mstr.group(2)
                        if value.endswith('"'):
                            value = value[:-1]
                        # get rid of password assignment
                        # echo "Please enter your OpenStack Password: "
                        # read -sr OS_PASSWORD_INPUT
                        # export OS_PASSWORD=$OS_PASSWORD_INPUT
                        if value.startswith('$'):
                            continue
                        # Check if api version is provided
                        # Default is keystone v2
                        if name == 'IDENTITY_API_VERSION':
                            self.rc_identity_api_version = int(value)

                        # now match against wanted variable names
                        elif name == 'USERNAME':
                            self.rc_username = value
                        elif name == 'AUTH_URL':
                            self.rc_auth_url = value
                        elif name == 'TENANT_NAME':
                            self.rc_tenant_name = value
                        elif name == "CACERT":
                            self.rc_cacert = value
                        elif name == "REGION_NAME":
                            self.rc_region_name = value
                        elif name == "PASSWORD" and not pwd:
                            pwd = value
                        elif name == "USER_DOMAIN_NAME":
                            self.rc_user_domain_name = value
                        elif name == "PROJECT_NAME":
                            self.rc_project_name = value
                        elif name == "PROJECT_DOMAIN_NAME":
                            self.rc_project_domain_name = value
            else:
                LOG.error('Error: rc file does not exist %s' % (openrc_file))
                success = False
        elif not no_env:
            # no openrc file passed - we assume the variables have been
            # sourced by the calling shell
            # just check that they are present
            if 'OS_IDENTITY_API_VERSION' in os.environ:
                self.rc_identity_api_version = int(os.environ['OS_IDENTITY_API_VERSION'])

            if self.rc_identity_api_version == 2:
                for varname in ['OS_USERNAME', 'OS_AUTH_URL', 'OS_TENANT_NAME']:
                    if varname not in os.environ:
                        LOG.warning('%s is missing', varname)
                        success = False
                if success:
                    self.rc_username = os.environ['OS_USERNAME']
                    self.rc_auth_url = os.environ['OS_AUTH_URL']
                    self.rc_tenant_name = os.environ['OS_TENANT_NAME']

                if 'OS_REGION_NAME' in os.environ:
                    self.rc_region_name = os.environ['OS_REGION_NAME']

            elif self.rc_identity_api_version == 3:
                for varname in ['OS_USERNAME', 'OS_AUTH_URL', 'OS_PROJECT_NAME',
                                'OS_PROJECT_DOMAIN_NAME', 'OS_USER_DOMAIN_NAME']:
                    if varname not in os.environ:
                        LOG.warning('%s is missing', varname)
                        success = False
                if success:
                    self.rc_username = os.environ['OS_USERNAME']
                    self.rc_auth_url = os.environ['OS_AUTH_URL']
                    self.rc_project_name = os.environ['OS_PROJECT_NAME']
                    self.rc_project_domain_name = os.environ['OS_PROJECT_DOMAIN_NAME']
                    self.rc_user_domain_name = os.environ['OS_USER_DOMAIN_NAME']

            if 'OS_CACERT' in os.environ:
                self.rc_cacert = os.environ['OS_CACERT']

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
