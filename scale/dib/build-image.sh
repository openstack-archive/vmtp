#!/bin/bash

#
# A shell script to build the kloudbuster image using diskinage-builder
#
# The following packages must be installed prior to using this script:
# sudo apt-get -y install git
# sudo apt-get -y install qemu-utils

# install diskimage-builder
git clone git://github.com/openstack/diskimage-builder.git
git clone git://github.com/openstack/dib-utils.git

# Add diskimage-builder and dib-utils bin to the path
export PATH=$PATH:`pwd`/diskimage-builder/bin:`pwd`/dib-utils/bin

# Add the kloudbuster elements directory to the DIB elements path
export ELEMENTS_PATH=`pwd`/elements

time disk-image-create -o kloudbuster ubuntu kloudbuster

ls -l kloudbuster.qcow2

# cleanup
rm -rf diskimage-builder dib-utils

