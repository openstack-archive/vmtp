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
import time
class BaseCompute(object):
    """
    The Base class for nova compute resources
    1. Creates virtual machines with specific configs
    """


    def __init__(self, nova_client, user_name):
        self.novaclient = nova_client
        self.user_name = user_name
        self.instance = None
        self.fip = None
        self.fip_ip = None
        self.subnet_ip = None
        self.fixed_ip = None
        self.ssh_ip = None
        # Shared interface ip for tested and testing cloud
        self.shared_interface_ip = None


    # Create a server instance with associated
    # security group, keypair with a provided public key
    def create_server(self, vmname, image_name, flavor_type, keyname,
                      nic, sec_group, public_key_file,
                      avail_zone=None, user_data=None,
                      config_drive=None,
                      retry_count=100):
        """
        Create a VM instance given following parameters
        1. VM Name
        2. Image Name
        3. Flavor name
        4. key pair name
        5. Security group instance
        6. Optional parameters: availability zone, user data, config drive
        """

        # Get the image id and flavor id from their logical names
        image = self.find_image(image_name)
        flavor_type = self.find_flavor(flavor_type)

        # Also attach the created security group for the test
        instance = self.novaclient.servers.create(name=vmname,
                                                  image=image,
                                                  flavor=flavor_type,
                                                  key_name=keyname,
                                                  nics=nic,
                                                  availability_zone=avail_zone,
                                                  userdata=user_data,
                                                  config_drive=config_drive,
                                                  security_groups=[sec_group.id])
        flag_exist = self.find_server(vmname, retry_count)
        if flag_exist:
            self.instance = instance


    # Returns True if server is present false if not.
    # Retry for a few seconds since after VM creation sometimes
    # it takes a while to show up
    def find_server(self, vmname, retry_count):
        for _ in range(retry_count):
            servers_list = self.get_server_list()
            for server in servers_list:
                if server.name == vmname and server.status == "ACTIVE":
                    return True
            time.sleep(2)
        print "[%s] VM not found, after %d attempts" % (vmname, retry_count)
        return False

    def get_server_list(self):
        servers_list = self.novaclient.servers.list()
        return servers_list


    def delete_server(self):
        # First delete the instance
        if self.instance:
            self.novaclient.servers.delete(self.instance)
            self.instance = None

    def find_image(self, image_name):
        """
        Given a image name return the image id
        """
        try:
            image = self.novaclient.images.find(name=image_name)
            return image
        except Exception:
            return None


    def find_flavor(self, flavor_type):
        """
        Given a named flavor return the flavor
        """
        flavor = self.novaclient.flavors.find(name=flavor_type)
        return flavor


class SecGroup(object):


    def __init__(self, novaclient):
        self.secgroup = None
        self.secgroup_name = None
        self.novaclient = novaclient


    def create_secgroup_with_rules(self, group_name):
        group = self.novaclient.security_groups.create(name=group_name,
                                                       description="Test sec group")
        # Allow ping traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="icmp",
                                                    from_port=-1,
                                                    to_port=-1)
        # Allow SSH traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="tcp",
                                                    from_port=22,
                                                    to_port=22)
        # Allow HTTP traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="tcp",
                                                    from_port=80,
                                                    to_port=80)
        self.secgroup = group
        self.secgroup_name = group_name


    def delete_secgroup(self):
        """
        Delete the security group
        Sometimes this maybe in use if instance is just deleted
        Add a retry mechanism
        """
        print "Deleting secgroup %s" % (self.secgroup)
        for retry_count in range(10):
            try:
                self.novaclient.security_groups.delete(self.secgroup)
                break
            except Exception:
                print "Security group %s in use retry count:%d" % (self.secgroup_name, retry_count)
                time.sleep(4)


class KeyPair(object):


    def __init__(self, novaclient):
        self.keypair = None
        self.keypair_name = None
        self.novaclient = novaclient


    def add_public_key(self, name, public_key_file=None):
        """
        Add the KloudBuster public key to openstack
        """
        public_key = None
        try:
            with open(os.path.expanduser(public_key_file)) as pkf:
                public_key = pkf.read()
        except IOError as exc:
            print 'ERROR: Cannot open public key file %s: %s' % \
                  (public_key_file, exc)
        print 'Adding public key %s' % (name)
        keypair = self.novaclient.keypairs.create(name, public_key)
        self.keypair = keypair
        self.keypair_name = name


    def remove_public_key(self):
        """
        Remove the keypair created by KloudBuster
        """
        self.novaclient.keypairs.delete(self.keypair)
