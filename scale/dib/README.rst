====================================
KLOUDBUSTER IMAGE BUILD INSTRUCTIONS
====================================

There are 2 ways to build the kloudbuster image:
* using Vagrant (recommended to build the image on Mac)
* using the build-image.sh script (recommended to build the image on Linux)

Build on Mac OSX
================

Pre-Requisites
--------------
* must have access to the Internet (to allow download of packages)
* must install Vagrant (https://www.vagrantup.com/downloads.html)
* must install VirtualBox (https://www.virtualbox.org/wiki/Downloads)

Instructions
------------

* Open a shell window
* cd to the scale/dib directory (where this README.rst file resides)
* run vagrant: "vagrant up"

The build should take around 5-7 minutes (may vary depending on the speed of your Internet connection) and you should see the kloudbuster.qcow2 image appear in the current directory.

After the image is built, simply discard the vagrant VM: "vagrant destroy"


Build on Linux
==============

Pre-Requisites
--------------
* must have access to the Internet (to allow download of packages)
* must install git
* must install qemu-utils

Instructions
------------

* clone the kloudbuster git repository somewhere
* git clone -b kloudbuster git://github.com/stackforge/vmtp.git
* cd vmtp/scale/dib
* ./build-image.sh

The build should take around 5-7 minutes (may vary depending on the speed of your Internet connection) and you should see the kloudbuster.qcow2 image appear in the current directory.

After the image is built, move the image in a safe location and delete the vmtp directory.



