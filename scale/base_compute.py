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

import log as logging

LOG = logging.getLogger(__name__)


class BaseCompute(object):
    """
    The Base class for nova compute resources
    1. Creates virtual machines with specific configs
    """


    def __init__(self, vm_name, network):
        self.novaclient = network.router.user.nova_client
        self.network = network
        self.vm_name = vm_name
        self.instance = None
        self.host = None
        self.fip = None
        self.fip_ip = None
        self.subnet_ip = None
        self.fixed_ip = None
        self.ssh_ip = None
        # Shared interface ip for tested and testing cloud
        self.shared_interface_ip = None


    # Create a server instance with associated
    # security group, keypair with a provided public key
    def create_server(self, image_name, flavor_type, keyname,
                      nic, sec_group, avail_zone=None, user_data=None,
                      config_drive=None, retry_count=100):
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
        instance = self.novaclient.servers.create(name=self.vm_name,
                                                  image=image,
                                                  flavor=flavor_type,
                                                  key_name=keyname,
                                                  nics=nic,
                                                  availability_zone=avail_zone,
                                                  userdata=user_data,
                                                  config_drive=config_drive,
                                                  security_groups=[sec_group.id])

        if not instance:
            return None
        # Verify that the instance gets into the ACTIVE state
        for _ in range(retry_count):
            instance = self.novaclient.servers.get(instance.id)
            if instance.status == 'ACTIVE':
                self.instance = instance
                if 'OS-EXT-SRV-ATTR:hypervisor_hostname' in instance.__dict__:
                    self.host = instance.__dict__['OS-EXT-SRV-ATTR:hypervisor_hostname']
                else:
                    self.host = "Unknown"
                return instance
            if instance.status == 'ERROR':
                LOG.error('Instance creation error:' + instance.fault['message'])
                break
            #   print "[%s] VM status=%s, retrying %s of %s..." \
            #         % (vmname, instance.status, (retry_attempt + 1), retry_count)
            time.sleep(2)

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
        # Allow Redis traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="tcp",
                                                    from_port=6379,
                                                    to_port=6379)
        # Allow Nuttcp traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="tcp",
                                                    from_port=5001,
                                                    to_port=5002)
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="udp",
                                                    from_port=5001,
                                                    to_port=5001)
        self.secgroup = group
        self.secgroup_name = group_name


    def delete_secgroup(self):
        """
        Delete the security group
        Sometimes this maybe in use if instance is just deleted
        Add a retry mechanism
        """
        for _ in range(10):
            try:
                self.novaclient.security_groups.delete(self.secgroup)
                break
            except Exception:
                time.sleep(2)


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
            LOG.error("Cannot open public key file %s: %s" % (public_key_file,
                                                              exc))
        LOG.info("Adding public key %s" % name)
        keypair = self.novaclient.keypairs.create(name, public_key)
        self.keypair = keypair
        self.keypair_name = name


    def remove_public_key(self):
        """
        Remove the keypair created by KloudBuster
        """
        self.novaclient.keypairs.delete(self.keypair)


class Flavor(object):

    def __init__(self, novaclient):
        self.novaclient = novaclient

    def list(self):
        return self.novaclient.flavors.list()

    def create_flavor(self, name, ram, vcpus, disk, override=False):
        # Creating flavors
        if override:
            self.delete_flavor(name)
        return self.novaclient.flavors.create(name=name, ram=ram, vcpus=vcpus, disk=disk)

    def delete_flavor(self, name):
        try:
            flavor = self.novaclient.flavors.find(name=name)
            flavor.delete()
        except Exception:
            pass

class NovaQuota(object):

    def __init__(self, novaclient, tenant_id):
        self.novaclient = novaclient
        self.tenant_id = tenant_id

    def get(self):
        return self.novaclient.quotas.get(self.tenant_id).__dict__

    def update_quota(self, **kwargs):
        self.novaclient.quotas.update(self.tenant_id, **kwargs)

class CinderQuota(object):

    def __init__(self, cinderclient, tenant_id):
        self.cinderclient = cinderclient
        self.tenant_id = tenant_id

    def get(self):
        return self.cinderclient.quotas.get(self.tenant_id).__dict__

    def update_quota(self, **kwargs):
        self.cinderclient.quotas.update(self.tenant_id, **kwargs)
