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


'''Module for Openstack compute operations'''

import os
import subprocess
import time

import novaclient
import novaclient.exceptions as exceptions

class Compute(object):

    def __init__(self, nova_client, config):
        self.novaclient = nova_client
        self.config = config

    def find_image(self, image_name):
        try:
            image = self.novaclient.images.find(name=image_name)
            return image
        except novaclient.exceptions.NotFound:
            return None

    def upload_image_via_url(self, glance_client, final_image_name, image_url, retry_count=60):
        '''
        Directly uploads image to Nova via URL if image is not present
        '''

        # Here is the deal:
        # Idealy, we should better to use the python library glanceclient to perform the
        # image uploades. However, due to a limitation of the v2.0 API right now, it is
        # impossible to tell Glance to download the image from a URL directly.
        #
        # There are two steps to create the image:
        # (1) Store the binary image data into Glance;
        # (2) Store the metadata about the image into Glance;
        # PS: The order does not matter.
        #
        # The REST API allows to do two steps in one if a Location header is provided with
        # the POST request. (REF: http://developer.openstack.org/api-ref-image-v2.html)
        #
        # However the python API doesn't support a customized header in POST request.
        # So we have to do two steps in two calls.
        #
        # The good thing is: the API does support (2) perfectly, but for (1) it is only
        # accepting the data from local, not remote URL. So... Ur... Let's keep the CLI
        # version as the workaround for now.

        # # upload in glance
        # image = glance_client.images.create(
        #     name=str(final_image_name), disk_format="qcow2", container_format="bare",
        #     Location=image_url)
        # glance_client.images.add_location(image.id, image_url, image)

        # sys.exit(0)
        # for retry_attempt in range(retry_count):
        #     if image.status == "active":
        #         print 'Image: %s successfully uploaded to Nova' % (final_image_name)
        #         return 1
        #     # Sleep between retries
        #     if self.config.debug:
        #         print "Image is not yet active, retrying %s of %s... [%s]" \
        #             % ((retry_attempt + 1), retry_count, image.status)
        #     time.sleep(5)

        # upload in glance
        glance_cmd = "glance image-create --name=\"" + str(final_image_name) + \
            "\" --disk-format=qcow2" + " --container-format=bare " + \
            " --is-public True --copy-from " + image_url
        if self.config.debug:
            print "Will update image to glance via CLI: %s" % (glance_cmd)
        subprocess.check_output(glance_cmd, shell=True)

        # check for the image in glance
        glance_check_cmd = "glance image-list --name \"" + str(final_image_name) + "\""
        for retry_attempt in range(retry_count):
            result = subprocess.check_output(glance_check_cmd, shell=True)
            if "active" in result:
                print 'Image: %s successfully uploaded to Nova' % (final_image_name)
                return 1
            # Sleep between retries
            if self.config.debug:
                print "Image not yet active, retrying %s of %s..." \
                    % ((retry_attempt + 1), retry_count)
            time.sleep(2)

        print 'ERROR: Cannot upload image %s from URL: %s' % (final_image_name, image_url)
        return 0

    # Remove keypair name from openstack if exists
    def remove_public_key(self, name):
        keypair_list = self.novaclient.keypairs.list()
        for key in keypair_list:
            if key.name == name:
                self.novaclient.keypairs.delete(name)
                print 'Removed public key %s' % (name)
                break

    # Test if keypair file is present if not create it
    def create_keypair(self, name, private_key_pair_file):
        self.remove_public_key(name)
        keypair = self.novaclient.keypairs.create(name)
        # Now write the keypair to the file
        kpf = os.open(private_key_pair_file,
                      os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(kpf, 'w') as kpf:
            kpf.write(keypair.private_key)
        return keypair

    # Add an existing public key to openstack
    def add_public_key(self, name, public_key_file):
        self.remove_public_key(name)
        # extract the public key from the file
        public_key = None
        try:
            with open(os.path.expanduser(public_key_file)) as pkf:
                public_key = pkf.read()
        except IOError as exc:
            print 'ERROR: Cannot open public key file %s: %s' % \
                  (public_key_file, exc)
            return None
        print 'Adding public key %s' % (name)
        keypair = self.novaclient.keypairs.create(name, public_key)
        return keypair

    def find_network(self, label):
        net = self.novaclient.networks.find(label=label)
        return net

    # Create a server instance with name vmname
    # if exists delete and recreate
    def create_server(self, vmname, image, flavor, key_name,
                      nic, sec_group, avail_zone=None, user_data=None,
                      config_drive=None,
                      retry_count=10):

        # Also attach the created security group for the test
        instance = self.novaclient.servers.create(name=vmname,
                                                  image=image,
                                                  flavor=flavor,
                                                  key_name=key_name,
                                                  nics=nic,
                                                  availability_zone=avail_zone,
                                                  userdata=user_data,
                                                  config_drive=config_drive,
                                                  security_groups=[sec_group.id])
        flag_exist = self.find_server(vmname, retry_count)
        if flag_exist:
            return instance
        else:
            return None

    def get_server_list(self):
        servers_list = self.novaclient.servers.list()
        return servers_list

    def find_floating_ips(self):
        floating_ip = self.novaclient.floating_ips.list()
        return floating_ip

    # Return the server network for a server
    def find_server_network(self, vmname):
        servers_list = self.get_server_list()
        for server in servers_list:
            if server.name == vmname and server.status == "ACTIVE":
                return server.networks
        return None

    # Returns True if server is present false if not.
    # Retry for a few seconds since after VM creation sometimes
    # it takes a while to show up
    def find_server(self, vmname, retry_count):
        for retry_attempt in range(retry_count):
            servers_list = self.get_server_list()
            for server in servers_list:
                if server.name == vmname and server.status == "ACTIVE":
                    return True
            # Sleep between retries
            if self.config.debug:
                print "[%s] VM not yet found, retrying %s of %s..." \
                      % (vmname, (retry_attempt + 1), retry_count)
            time.sleep(2)
        print "[%s] VM not found, after %s attempts" % (vmname, retry_count)
        return False

    # Returns True if server is found and deleted/False if not,
    # retry the delete if there is a delay
    def delete_server_by_name(self, vmname):
        servers_list = self.get_server_list()
        for server in servers_list:
            if server.name == vmname:
                print 'deleting server %s' % (server)
                self.novaclient.servers.delete(server)
                return True
        return False

    def delete_server(self, server):
        self.novaclient.servers.delete(server)

    def find_flavor(self, flavor_type):
        flavor = self.novaclient.flavors.find(name=flavor_type)
        return flavor

    def normalize_az_host(self, az, host):
        if not az:
            az = self.config.availability_zone
        return az + ':' + host

    def auto_fill_az(self, host_list, host):
        '''
        no az provided, if there is a host list we can auto-fill the az
        else we use the configured az if available
        else we return an error
        '''
        if host_list:
            for hyp in host_list:
                if hyp.host_name == host:
                    return self.normalize_az_host(hyp.zone, host)
            # no match on host
            print('Error: passed host name does not exist: ' + host)
            return None
        if self.config.availability_zone:
            return self.normalize_az_host(None, host)
        print('Error: --hypervisor passed without an az and no az configured')
        return None

    def sanitize_az_host(self, host_list, az_host):
        '''
        host_list: list of hosts as retrieved from openstack (can be empty)
        az_host: either a host or a az:host string
        if a host, will check host is in the list, find the corresponding az and
                    return az:host
        if az:host is passed will check the host is in the list and az matches
        if host_list is empty, will return the configured az if there is no
                    az passed
        '''
        if ':' in az_host:
            # no host_list, return as is (no check)
            if not host_list:
                return az_host
            # if there is a host_list, extract and verify the az and host
            az_host_list = az_host.split(':')
            zone = az_host_list[0]
            host = az_host_list[1]
            for hyp in host_list:
                if hyp.host_name == host:
                    if hyp.zone == zone:
                        # matches
                        return az_host
                    # else continue - another zone with same host name?
            # no match
            print('Error: no match for availability zone and host ' + az_host)
            return None
        else:
            return self.auto_fill_az(host_list, az_host)

    #
    #   Return a list of 0, 1 or 2 az:host
    #
    #   The list is computed as follows:
    #   The list of all hosts is retrieved first from openstack
    #        if this fails, checks and az auto-fill are disabled
    #
    #   If the user provides a list of hypervisors (--hypervisor)
    #       that list is checked and returned
    #
    #   If the user provides a configured az name (config.availability_zone)
    #       up to the first 2 hosts from the list that match the az are returned
    #
    #   If the user did not configure an az name
    #       up to the first 2 hosts from the list are returned
    #   Possible return values:
    #   [ az ]
    #   [ az:hyp ]
    #   [ az1:hyp1, az2:hyp2 ]
    #   []  if an error occurred (error message printed to console)
    #
    def get_az_host_list(self):
        avail_list = []
        host_list = []

        try:
            host_list = self.novaclient.hosts.list()
        except novaclient.exceptions.Forbidden:
            print ('Warning: Operation Forbidden: could not retrieve list of hosts'
                   ' (likely no permission)')

        # the user has specified a list of 1 or 2 hypervisors to use
        if self.config.hypervisors:
            for hyp in self.config.hypervisors:
                hyp = self.sanitize_az_host(host_list, hyp)
                if hyp:
                    avail_list.append(hyp)
                else:
                    return []
                # if the user did not specify an az, insert the configured az
                if ':' not in hyp:
                    if self.config.availability_zone:
                        hyp = self.normalize_az_host(None, hyp)
                    else:
                        return []
                # pick first 2 matches at most
                if len(avail_list) == 2:
                    break
            print 'Using hypervisors:' + ', '.join(avail_list)
        else:
            for host in host_list:
                # this host must be a compute node
                if host._info['service'] != 'compute':
                    continue
                candidate = None
                if self.config.availability_zone:
                    if host.zone == self.config.availability_zone:
                        candidate = self.normalize_az_host(None, host.host_name)
                else:
                    candidate = self.normalize_az_host(host.zone, host.host_name)
                if candidate:
                    avail_list.append(candidate)
                    # pick first 2 matches at most
                    if len(avail_list) == 2:
                        break

        # if empty we insert the configured az
        if not avail_list:

            if not self.config.availability_zone:
                print('Error: availability_zone must be configured')
            elif host_list:
                print('Error: no host matching the selection for availability zone: '
                      + self.config.availability_zone)
                avail_list = []
            else:
                avail_list = [self.config.availability_zone]
        return avail_list

    # Given 2 VMs test if they are running on same Host or not
    def check_vm_placement(self, vm_instance1, vm_instance2):
        try:
            server_instance_1 = self.novaclient.servers.get(vm_instance1)
            server_instance_2 = self.novaclient.servers.get(vm_instance2)
            if server_instance_1.hostId == server_instance_2.hostId:
                return True
            else:
                return False
        except novaclient.exceptions:
            print "Exception in retrieving the hostId of servers"

    # Create a new security group with appropriate rules
    def security_group_create(self):
        # check first the security group exists
        # May throw exceptions.NoUniqueMatch or NotFound
        try:
            group = self.novaclient.security_groups.find(name=self.config.security_group_name)
            return group
        except exceptions.NotFound:
            group = self.novaclient.security_groups.create(name=self.config.security_group_name,
                                                           description="PNS Security group")
            # Once security group try to find it iteratively
            # (this check may no longer be necessary)
            for _ in range(self.config.generic_retry_count):
                group = self.novaclient.security_groups.get(group)
                if group:
                    self.security_group_add_rules(group)
                    return group
                else:
                    time.sleep(1)
            return None
        # except exceptions.NoUniqueMatch as exc:
        #    raise exc

    # Delete a security group
    def security_group_delete(self, group):
        if group:
            print "Deleting security group"
            self.novaclient.security_groups.delete(group)

    # Add rules to the security group
    def security_group_add_rules(self, group):
        # Allow ping traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="icmp",
                                                    from_port=-1,
                                                    to_port=-1)
        if self.config.ipv6_mode:
            self.novaclient.security_group_rules.create(group.id,
                                                        ip_protocol="icmp",
                                                        from_port=-1,
                                                        to_port=-1,
                                                        cidr="::/0")
        # Allow SSH traffic
        self.novaclient.security_group_rules.create(group.id,
                                                    ip_protocol="tcp",
                                                    from_port=22,
                                                    to_port=22)
        # Allow TCP/UDP traffic for perf tools like iperf/nuttcp
        # 5001: Data traffic (standard iperf data port)
        # 5002: Control traffic (non standard)
        # note that 5000/tcp is already picked by openstack keystone
        if not self.config.ipv6_mode:
            self.novaclient.security_group_rules.create(group.id,
                                                        ip_protocol="tcp",
                                                        from_port=5001,
                                                        to_port=5002)
            self.novaclient.security_group_rules.create(group.id,
                                                        ip_protocol="udp",
                                                        from_port=5001,
                                                        to_port=5001)
        else:
            # IPV6 rules addition
            self.novaclient.security_group_rules.create(group.id,
                                                        ip_protocol="tcp",
                                                        from_port=5001,
                                                        to_port=5002,
                                                        cidr="::/0")
            self.novaclient.security_group_rules.create(group.id,
                                                        ip_protocol="udp",
                                                        from_port=5001,
                                                        to_port=5001,
                                                        cidr="::/0")
