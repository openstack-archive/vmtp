===============================
VMTP
===============================

What is VMTP
============
VMTP is a data path performance tool for OpenStack clouds.

Features
--------

VMTP is a python application that will automatically perform ping connectivity, ping round trip time measurement (latency) and TCP/UDP throughput measurement for the following flows on any OpenStack deployment:
* VM to VM same network (private fixed IP)
* VM to VM different network same tenant (intra-tenant L3 fixed IP)
* VM to VM different network and tenant (floating IP inter-tenant L3)

Optionally, when an external Linux host is available:
* External host/VM download and upload throughput/latency (L3/floating IP)

Optionally, when SSH login to any Linux host (native or virtual) is available:
* Host to host throughput (intra-node and inter-node)

Optionally, VMTP can extract automatically CPU usage from all native hosts in the cloud during the throughput tests, provided the Ganglia monitoring service (gmond) is installed and enabled on those hosts.

For VM-related flows, VMTP will automatically create the necessary OpenStack resources (router, networks, subnets, key pairs, security groups, test VMs), perform the throughput measurements then cleanup all related resources before exiting.

In the case involving pre-existing native or virtual hosts, VMTP will SSH to the targeted hosts to perform measurements.

Pre-requisite
-------------

* For VM related performance measurements:
    * Access to the cloud Horizon Dashboard
    * 1 working external network pre-configured on the cloud (VMTP will pick the first one found)
    * At least 2 floating IP if an external router is configured or 3 floating IP if there is no external router configured
    * 1 Linux image available in OpenStack (any distribution)
    * A configuration file that is properly set for the cloud to test (see "Configuration File" section below)

* For native/external host throughput:
    * A public key must be installed on the target hosts (see ssh password-less access below)
      
* For pre-existing native host throughputs:
    * Firewalls must be configured to allow TCP/UDP ports 5001 and TCP port 5002

* Docker is installed if using the VMTP Docker image

Sample Results Output
---------------------

VMTP will display the results to stdout with the following data:

* Session general information (date, auth_url, OpenStack encaps, VMTP version...)
* List of results per flow, for each flow:

    * flow name
    * to and from IP addresses
    * to and from availability zones (if VM)
    * results:
        * TCP
            * packet size
            * throughput value
            * number of retransmissions
            * round trip time in ms
            * CPU usage (if enabled), for each host in the openstack cluster:
                * baseline (before test starts)
                * 1 or more readings during test
        * UDP
            * for each packet size
                * throughput value
                * loss rate
                * CPU usage (if enabled)
        * ICMP
            * average, min, max and stddev round trip time in ms

Detailed results can also be stored in a file in JSON format using the --json command line argument.


Installation
============

For people who wants to do development for VMTP, it is recommended to set up the develop environments as below. However, for people who just wants to run the tool, or without root access, please refer to the "How to Run VMTP Tool" section and use VMTP Docker Image instead.

Here is an example for Ubuntu developers, and similar packages can be found and installed on RPM-based distro as well.

.. code-block:: none
    $ sudo apt-get install python-dev python-virtualenv git git-review libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev
    $ virtualenv vmtpenv
    $ source vmtpenv/bin/activate
    $ git clone git://git.openstack.org/stackforge/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ python vmtp.py -h


How to Run VMTP Tool
====================


VMTP Docker Image
-----------------

In its Docker image form, VMTP is located under the /vmtp directory in the container and can either take arguments from the host shell, or can be executed from inside the Docker image shell.

To run VMTP directly from the host shell (may require "sudo" up front if not root)

.. code-block:: none   
    docker run <vmtp-docker-image-name> python /vmtp/vmtp.py <args>

To run VMTP from the Docker image shell:

.. code-block:: none
    docker run <vmtp-docker-image-name> /bin/bash
    cd /vmtp.py
    python vmtp.py <args>

(then type exit to exit and terminate the container instance)


Docker Shared Volume to Share Files with the Container
------------------------------------------------------

VMTP can accept files as input (e.g. configuration and openrc file) and can generate json results into a file.

It is possible to use the VMTP Docker image with files persisted on the host by using Docker shared volumes.

For example, one can decide to mount the current host directory as /vmtp/shared in the container in read-write mode.

To get a copy of the VMTP default configuration file from the container:

.. code-block:: none
    docker run -v $PWD:/vmtp/shared:rw <docker-vmtp-image-name>  cp /vmtp/cfg.default.yaml /vmtp/shared/mycfg.yaml

Assume you have edited the configuration file "mycfg.yaml" and retrieved an openrc file "admin-openrc.sh" from Horizon on the local directory and would like to get results back in the "res.json" file, you can export the current directory ($PWD), map it to /vmtp/shared in the container in read/write mode, then run the script in the container by using files from the shared directory:

.. code-block:: none
    docker run -v $PWD:/vmtp/shared:rw -t <docker-vmtp-image-name> python /vmtp/vmtp.py -c shared/mycfg.yaml -r shared/admin-openrc.sh -p admin --json shared/res.json
    cat res.json


Print VMTP Usage
----------------
```
usage: vmtp.py [-h] [-c <config_file>] [-r <openrc_file>]
               [-m <gmond_ip>[:<port>]] [-p <password>] [-t <time>]
               [--host <user>@<host_ssh_ip>[:<server-listen-if-name>]]
               [--external-host <user>@<ext_host_ssh_ip>]
               [--access_info {host:<hostip>, user:<user>, password:<pass>}]
               [--mongod_server <server ip>] [--json <file>]
               [--tp-tool nuttcp|iperf] [--hypervisor name]
               [--inter-node-only] [--protocols T|U|I]
               [--bandwidth <bandwidth>] [--tcpbuf <tcp_pkt_size1,...>]
               [--udpbuf <udp_pkt_size1,...>] [--no-env] [-d] [-v]
               [--stop-on-error]

OpenStack VM Throughput V2.0.0

optional arguments:
  -h, --help            show this help message and exit
  -c <config_file>, --config <config_file>
                        override default values with a config file
  -r <openrc_file>, --rc <openrc_file>
                        source OpenStack credentials from rc file
  -m <gmond_ip>[:<port>], --monitor <gmond_ip>[:<port>]
                        Enable CPU monitoring (requires Ganglia)
  -p <password>, --password <password>
                        OpenStack password
  -t <time>, --time <time>
                        throughput test duration in seconds (default 10 sec)
  --host <user>@<host_ssh_ip>[:<server-listen-if-name>]
                        native host throughput (targets requires ssh key)
  --external-host <user>@<ext_host_ssh_ip>
                        external-VM throughput (target requires ssh key)
  --access_info {host:<hostip>, user:<user>, password:<pass>}
                        access info for control host
  --mongod_server <server ip>
                        provide mongoDB server IP to store results
  --json <file>         store results in json format file
  --tp-tool nuttcp|iperf
                        transport perf tool to use (default=nuttcp)
  --hypervisor name     hypervisor to use in the avail zone (1 per arg, up to
                        2 args)
  --inter-node-only     only measure inter-node
  --protocols T|U|I     protocols T(TCP), U(UDP), I(ICMP) - default=TUI (all)
  --bandwidth <bandwidth>
                        the bandwidth limit for TCP/UDP flows in K/M/Gbps,
                        e.g. 128K/32M/5G. (default=no limit)
  --tcpbuf <tcp_pkt_size1,...>
                        list of buffer length when transmitting over TCP in
                        Bytes, e.g. --tcpbuf 8192,65536. (default=65536)
  --udpbuf <udp_pkt_size1,...>
                        list of buffer length when transmitting over UDP in
                        Bytes, e.g. --udpbuf 128,2048. (default=128,1024,8192)
  --no-env              do not read env variables
  -d, --debug           debug flag (very verbose)
  -v, --version         print version of this script and exit
  --stop-on-error       Stop and keep everything as-is on error (must cleanup
                        manually)

```


Configuration File
^^^^^^^^^^^^^^^^^^

VMTP configuration files follow the yaml syntax and contain variables used by VMTP to run and collect performance data.
The default configuration is stored in the cfg.default.yaml file.
Default values should be overwritten for any cloud under test by defining new variable values in a new configuration file that follows the same format.
Variables that are not defined in the new configuration file will retain their default values.

Parameters that you are most certainly required to change are:

* The VM image name to use to run the performance tools, you will need to specify any standard Linux image (Ubuntu 12.04, 14.04, Fedora, RHEL7, CentOS...) - if needed you will need to upload an image to OpenStack manually prior to running VMTP
* VM SSH user name to use (specific to the image)
* The flavor name to use (often specific to each cloud)
* Name of the availability zone to use for running the performance test VMs (also specific to each cloud)

Check the content of cfg.default.yaml file as it contains the list of configuration variables and instructions on how to set them.

Create one configuration file for your specific cloud and use the -c option to pass that file name to VMTP.

**Note:** the configuration file is not needed if the VMTP only runs the native host throughput option (--host)


OpenStack openrc file
^^^^^^^^^^^^^^^^^^^^^

VMTP requires downloading an "openrc" file from the OpenStack Dashboard (Project|Acces&Security!Api Access|Download OpenStack RC File)
This file should then be passed to VMTP using the -r option or should be sourced prior to invoking VMTP.

**Note:** the openrc file is not needed if VMTP only runs the native host throughput option (--host)


Bandwidth limit for TCP/UDP flow measurements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Specify a value in --bandwidth will limit the bandwidth when performing throughput tests.

The default behavior for both TCP/UDP are unlimited. For TCP, we are leveraging on the protocol itself to get the best performance; while for UDP, we are doing a binary search to find the optimal bandwidth.

This is useful when running vmtp on production clouds. The test tool will use up all the bandwidth that may be needed by any other live VMs if we don't set any bandwidth limit. This feature will help to prevent impacting other VMs while running the test tool.


Host Selection in Availability Zone
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The --hypervisor argument can be used to specify explicitly where to run the test VM in the configured availability zone.

This can be handy for example when exact VM placement can impact the data path performance (for example rack based placement when the availability zone spans across multiple racks).

The first --hypervisor argument specifies on which host to run the test server VM. The second --hypervisor argument (in the command line) specifies on which host to run the test client VMs.

The value of the argument must match the hypervisor host name as known by OpenStack (or as displayed using "nova hypervisor-list")

Example of usage is given below.


Examples of running VMTP on an OpenStack Cloud
----------------------------------------------

Preparation
^^^^^^^^^^^

Download the openrc file from OpenStack Dashboard, and saved it to your local file system. (In Horizon dashboard: Project|Acces&Security!Api Access|Download OpenStack RC File)

If executing a VMTP Docker image "docker run" (or "sudo docker run") must be placed in front of these commands unless you run a shell script directly from inside the container.

*Example 1: Typical Run*
Run VMTP on an OpenStack cloud with the default configuration file, use "admin-openrc.sh" as the rc file, and "admin" as the password.

.. code-block:: none
    python vmtp.py -r admin-openrc.sh -p admin

This will generate 6 standard sets of performance data:
(1) VM to VM same network (intra-node, private fixed IP)
(2) VM to VM different network (intra-node, L3 fixed IP)
(3) VM to VM different network and tenant (intra-node, floating IP)
(4) VM to VM same network (inter-node, private fixed IP)
(5) VM to VM different network (inter-node, L3 fixed IP)
(6) VM to VM different network and tenant (inter-node, floating IP)

By default, the performance data of all three protocols (TCP/UDP/ICMP) will be measured for each scenario mentioned above. However, it can be overridden by providing --protocols. E.g.

.. code-block:: none
    python vmtp.py -r admin-openrc.sh -p admin --protocols IT

This will tell VMTP to only collect ICMP and TCP measurements.

*Example 2: Cloud upload/download performance measurement*
Run VMTP on an OpenStack cloud with a specified configuration file (mycfg.yaml), and saved the result to a JSON file:

.. code-block:: none
    python vmtp.py -c mycfg.yaml -r admin-openrc.sh -p admin --external_host localadmin@172.29.87.29 --json res.json

This run will generate 8 sets of performance data, the standard 6 sets mentioned above, plus two sets of upload/download performance data for both TCP and UDP.

**Note:** In order to perform the upload/download performance test, an external server must be specified and configured with SSH password-less access. See below for more info.

*Example 3: Specify which availability zone to spawn VMs*
Run VMTP on an OpenStack cloud, spawn the test server VM on tme212, and the test client VM on tme210. Do the inter-node measurement only.

.. code-block:: none
    python vmtp.py -r admin-openrc.sh -p lab --inter-node-only --json vxlan_offload.json --hypervisor tme212 --hypervisor tme210

*Example 4: Collect native host performance data*
Run VMTP to get native host throughput between 172.29.87.29 and 172.29.87.30 using the localadmin ssh username and run each tcp/udp test session for 120 seconds (instead of the default 10 seconds):

.. code-block:: none
    python vmtp.py --host localadmin@172.29.87.29 --host localadmin@172.29.87.30 --time 120

**Note:** This command requires each host to have the VMTP public key (ssh/id_rsa.pub) inserted into the ssh/authorized_keys file in the username home directory, i.e. SSH password-less access. See below for more info.

*Example 5: Measurement on pre-existing VMs*
It is possible to run VMTP between pre-existing VMs that are accessible through SSH (using floating IP).

The first IP passed (--host) is always the one running the server side. Optionally a server side listening interface name can be passed if clients should connect using a particular server IP. For example, to measure throughput between 2 hosts using the network attached to the server interface "eth5":

.. code-block:: none
    python vmtp.py --host localadmin@172.29.87.29:eth5 --host localadmin@172.29.87.30

**Note:** Prior to running, the VMTP public key must be installed on each VM.

Setups
======

Public Cloud
------------

Public clouds are special because they may not expose all OpenStack APIs and may not allow all types of operations. Some public clouds have limitations in the way virtual networks can be used or require the use of a specific external router. Running VMTP against a public cloud will require a specific configuration file that takes into account those specificities.

Refer to the provided public cloud sample configuration files for more information.

SSH password-less Access
------------------------

For host throughput (--host), VMTP expects the target hosts to be pre-provisioned with a public key in order to allow password-less SSH.

Test VMs are created through OpenStack by VMTP with the appropriate public key to allow password-less ssh. By default, VMTP uses a default VMTP public key located in ssh/id_rsa.pub, simply append the content of that file into the .ssh/authorized_keys file under the host login home directory).

**Note:** This default VMTP public key should only be used for transient test VMs and **MUST NOT** be used to provision native hosts since the corresponding private key is open to anybody! To use alternate key pairs, the 'private_key_file' variable in the configuration file must be overridden to point to the file containing the private key to use to connect with SSH.


Implementations
===============

TCP Throughput Measurement
--------------------------

The TCP throughput reported is measured using the default message size of the test tool (64KB with nuttcp). The TCP MSS (maximum segment size) used is the one suggested by the TCP-IP stack (which is dependent on the MTU).

UDP Throughput Measurement
--------------------------
UDP throughput is tricky because of limitations of the performance tools used, limitations of the Linux kernel used and criteria for finding the throughput to report.

The default setting is to find the "optimal" throughput with packet loss rate within the 2%..5% range. This is achieved by successive iterations at different throughput values.

In some cases, it is not possible to converge with a loss rate within that range and trying to do so may require too many iterations. The algorithm used is empiric and tries to achieve a result within a reasonable and bounded number of iterations. In most cases the optimal throughput is found in less than 30 seconds for any given flow.

**Note:** UDP measurements are only available with nuttcp (not available with iperf).


Caveats and Known Issues
========================

* UDP throughput is not available if iperf is selected (the iperf UDP reported results are not reliable enough for iterating)
* If VMTP hangs for native hosts throughputs, check firewall rules on the hosts to allow TCP/UDP ports 5001 and TCP port 5002


Links
=====

* Documentation: http://docs.openstack.org/developer/vmtp
* Source: http://git.openstack.org/cgit/stackforge/vmtp
* Bugs: http://bugs.launchpad.net/vmtp

