#!/bin/sh
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

##############################################################################
# The DNS Server
KB_DNS_SERVER='172.29.74.154'
# External network name in Neutron
KB_EXTERNAL_NET='ext-net'
# Image Version
KB_IMAGE_VERSION='8'
# The base image used to build the snapshot
# Note: Must be a Debian-based Image
KB_BASE_IMAGE_NAME='Ubuntu Server 14.04'
# The URL for downloading the base image
KB_BASE_IMAGE_URL='https://cloud-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-disk1.img'
# Save the snapshot image to local host
KB_SAVE_SNAPSHOT_IMAGE='yes'
##############################################################################

# ==================
# Creating Resources
# ==================
KB_SNAPSHOT_IMG_NAME="Scale Image v$KB_IMAGE_VERSION"
KB_SNAPSHOT_IMG_FILENAME="scale_image_v$KB_IMAGE_VERSION.qcow2"
rm -f /var/tmp/kb_image_key /var/tmp/kb_image_key.pub
ssh-keygen -b 1024 -C "KloudBuster Image" -t rsa -f /var/tmp/kb_image_key -N ""
nova secgroup-create kb_secgroup "Temp Security Group for creating KloudBuster image"
neutron security-group-rule-create kb_secgroup --direction ingress
neutron net-create kb_net
neutron subnet-create kb_net 192.168.1.0/24 --name kb_subnet --gateway 192.168.1.1 --allocation-pool start=192.168.1.100,end=192.168.1.200 --dns-nameserver $KB_DNS_SERVER
neutron router-create kb_router
neutron router-gateway-set kb_router $KB_EXTERNAL_NET
neutron router-interface-add kb_router kb_subnet
nova keypair-add --pub-key /var/tmp/kb_image_key.pub kb_image_key
glance image-list | grep "\b$KB_BASE_IMAGE_NAME\b"
if [ $? -ne 0 ]; then
    glance image-create --name="$KB_BASE_IMAGE_NAME" --disk-format=qcow2 --container-format=bare --is-public True --copy-from $KB_BASE_IMAGE_URL
fi
KB_NET_ID=`neutron net-list | grep 'kb_net' | cut -d'|' -f2 | xargs`
KB_FLOATING_IP_ID=`neutron floatingip-create $KB_EXTERNAL_NET | grep '\bid\b' | cut -d'|' -f3 | xargs`
KB_FLOATING_IP=`neutron floatingip-list | grep $KB_FLOATING_IP_ID | cut -d'|' -f4 | xargs`
nova boot kb_scale_instance --flavor m1.small --image "$KB_BASE_IMAGE_NAME" --key-name kb_image_key --security-group kb_secgroup --nic net-id=$KB_NET_ID --poll
KB_INSTANCE_IP=`nova list | grep 'kb_scale_instance' | cut -d'=' -f2 | sed 's/\s*|//g'`
KB_PORT_ID=`neutron port-list | grep $KB_INSTANCE_IP | cut -d'|' -f2 | xargs`
neutron floatingip-associate $KB_FLOATING_IP_ID $KB_PORT_ID

# Running scripts to build image
while true; do
    ssh ubuntu@$KB_FLOATING_IP -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i /var/tmp/kb_image_key echo "Connected"
    if [ $? -eq 0 ]; then break; fi
    sleep 5
done
ssh -o StrictHostKeyChecking=no -i /var/tmp/kb_image_key ubuntu@$KB_FLOATING_IP 'bash -s' < scripts

# ===============
# Create Snapshot
# ===============
nova stop kb_scale_instance
while true; do
    sleep 1
    nova list | grep kb_scale_instance | grep SHUTOFF
    if [ $? -eq 0 ]; then
        break;
    fi
done
nova image-create --poll kb_scale_instance "$KB_SNAPSHOT_IMG_NAME"
if [ "$KB_SAVE_SNAPSHOT_IMAGE" = "yes" ]; then
    echo "Saving snapshot to $KB_SNAPSHOT_IMG_FILENAME..."
    glance image-download "$KB_SNAPSHOT_IMG_NAME" --file $KB_SNAPSHOT_IMG_FILENAME
fi

# =======
# Cleanup
# =======
nova delete kb_scale_instance
while true; do
    sleep 1
    nova list | grep kb_scale_instance
    if [ $? -ne 0 ]; then
        break;
    fi
done
neutron floatingip-delete $KB_FLOATING_IP_ID
neutron router-interface-delete kb_router kb_subnet
neutron router-gateway-clear kb_router
neutron router-delete kb_router
neutron net-delete kb_net
nova secgroup-delete kb_secgroup
nova keypair-delete kb_image_key
rm -f /var/tmp/kb_image_key /var/tmp/kb_image_key.pub
