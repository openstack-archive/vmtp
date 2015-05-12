#!/bin/sh

KB_DNS_SERVER=172.29.74.154
KB_EXTERNAL_NET='ext-net'
KB_IMAGE_VERSION=7
KB_UBUNTU_IMAGE='http://172.29.172.152/downloads/scale_image/ubuntu-14.04-server-cloudimg-amd64-disk1.img'

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
glance image-list | grep "\bUbuntu Server 14.04\b"
if [ $? -ne 0 ]; then
    glance image-create --name="Ubuntu Server 14.04" --disk-format=qcow2 --container-format=bare --is-public True --copy-from $KB_UBUNTU_IMAGE
fi
KB_NET_ID=`neutron net-list | grep 'kb_net' | cut -d'|' -f2 | xargs`
KB_FLOATING_IP_ID=`neutron floatingip-create $KB_EXTERNAL_NET | grep '\bid\b' | cut -d'|' -f3 | xargs`
KB_FLOATING_IP=`neutron floatingip-list | grep $KB_FLOATING_IP_ID | cut -d'|' -f4 | xargs`
nova boot kb_scale_instance --flavor m1.small --image "Ubuntu Server 14.04" --key-name kb_image_key --security-group kb_secgroup --nic net-id=$KB_NET_ID --poll
KB_INSTANCE_IP=`nova list | grep 'kb_scale_instance' | cut -d'=' -f2 | sed 's/\s*|//g'`
KB_PORT_ID=`neutron port-list | grep $KB_INSTANCE_IP | cut -d'|' -f2 | xargs`
neutron floatingip-associate $KB_FLOATING_IP_ID $KB_PORT_ID

# Running scripts to build image
while true; do
    ssh ubuntu@$KB_FLOATING_IP -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i /var/tmp/kb_image_key echo "Connected"
    if [ $? -eq 0 ]; then break; fi
    sleep 5
done
scp -o StrictHostKeyChecking=no -i /var/tmp/kb_image_key scripts ubuntu@$KB_FLOATING_IP:/var/tmp/scripts
ssh -o StrictHostKeyChecking=no -i /var/tmp/kb_image_key ubuntu@$KB_FLOATING_IP bash /var/tmp/scripts

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
glance image-download "$KB_SNAPSHOT_IMG_NAME" --file $KB_SNAPSHOT_IMG_FILENAME

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
