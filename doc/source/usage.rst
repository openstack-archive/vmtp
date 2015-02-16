=====
Usage
=====

VMTP Docker Image
-----------------

In its Docker image form, VMTP is located under the /vmtp directory in the container and can either take arguments from the host shell, or can be executed from inside the Docker image shell.

To run VMTP directly from the host shell (may require "sudo" up front if not root)::

    docker run <vmtp-docker-image-name> python /vmtp/vmtp.py <args>

To run VMTP from the Docker image shell::

    docker run <vmtp-docker-image-name> /bin/bash
    cd /vmtp.py
    python vmtp.py <args>

(then type exit to exit and terminate the container instance)


Docker Shared Volume to Share Files with the Container
------------------------------------------------------

VMTP can accept files as input (e.g. configuration and openrc file) and can generate json results into a file.

It is possible to use the VMTP Docker image with files persisted on the host by using Docker shared volumes.

For example, one can decide to mount the current host directory as /vmtp/shared in the container in read-write mode.

To get a copy of the VMTP default configuration file from the container::

    docker run -v $PWD:/vmtp/shared:rw <docker-vmtp-image-name>  cp /vmtp/cfg.default.yaml /vmtp/shared/mycfg.yaml

Assume you have edited the configuration file "mycfg.yaml" and retrieved an openrc file "admin-openrc.sh" from Horizon on the local directory and would like to get results back in the "res.json" file, you can export the current directory ($PWD), map it to /vmtp/shared in the container in read/write mode, then run the script in the container by using files from the shared directory::

    docker run -v $PWD:/vmtp/shared:rw -t <docker-vmtp-image-name> python /vmtp/vmtp.py -c shared/mycfg.yaml -r shared/admin-openrc.sh -p admin --json shared/res.json
    cat res.json


VMTP Usage
----------

.. code::

    usage: vmtp.py [-h] [-c <config_file>] [-r <openrc_file>]
                   [-m <gmond_ip>[:<port>]] [-p <password>] [-t <time>]
                   [--host <user>@<host_ssh_ip>[:<server-listen-if-name>]]
                   [--external-host <user>@<host_ssh_ip>[:password>]]
                   [--controller-node <user>@<host_ssh_ip>[:<password>]]
                   [--mongod_server <server ip>] [--json <file>]
                   [--tp-tool nuttcp|iperf] [--hypervisor [<az>:] <hostname>]
                   [--inter-node-only] [--protocols T|U|I]
                   [--bandwidth <bandwidth>] [--tcpbuf <tcp_pkt_size1,...>]
                   [--udpbuf <udp_pkt_size1,...>] [--no-env] [-d] [-v]
                   [--stop-on-error] [--vm_image_url <url_to_image>]

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
      --external-host <user>@<host_ssh_ip>[:password>]
                            external-VM throughput (host requires public key if no
                            password)
      --controller-node <user>@<host_ssh_ip>[:<password>]
                            controller node ssh (host requires public key if no
                            password)
      --mongod_server <server ip>
                            provide mongoDB server IP to store results
      --json <file>         store results in json format file
      --tp-tool nuttcp|iperf
                            transport perf tool to use (default=nuttcp)
      --hypervisor [<az>:] <hostname>
                            hypervisor to use (1 per arg, up to 2 args)
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
      --vm_image_url <url_to_image>
                            URL to a Linux image in qcow2 format that can be
                            downloaded from


Configuration File
^^^^^^^^^^^^^^^^^^

VMTP configuration files follow the yaml syntax and contain variables used by VMTP to run and collect performance data.

The default configuration is stored in the cfg.default.yaml file.

Default values should be overwritten for any cloud under test by defining new variable values in a new configuration file that follows the same format. Variables that are not defined in the new configuration file will retain their default values.

Parameters that you are most certainly required to change are:

* The VM image name to use to run the performance tools, you will need to specify any standard Linux image (Ubuntu 12.04, 14.04, Fedora, RHEL7, CentOS...) - if needed you will need to upload an image to OpenStack manually prior to running VMTP
* VM SSH user name to use (specific to the image)
* The flavor name to use (often specific to each cloud)
* Name of the availability zone to use for running the performance test VMs (also specific to each cloud)

Check the content of cfg.default.yaml file as it contains the list of configuration variables and instructions on how to set them.

Create one configuration file for your specific cloud and use the *-c* option to pass that file name to VMTP.

**Note:** the configuration file is not needed if the VMTP only runs the native host throughput option (*--host*)


OpenStack openrc File
^^^^^^^^^^^^^^^^^^^^^

VMTP requires downloading an "openrc" file from the OpenStack Dashboard (Project|Acces&Security!Api Access|Download OpenStack RC File)

This file should then be passed to VMTP using the *-r* option or should be sourced prior to invoking VMTP.

**Note:** the openrc file is not needed if VMTP only runs the native host throughput option (*--host*)


Access Info for Controller Node
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, VMTP is not able to get the Linux distro nor the OpenStack version of the cloud deployment. However, by providing the credentials of the controller node, VMTP will try to fetch these information, and output them along in the JSON file or to the MongoDB server.


Bandwidth Limit for TCP/UDP Flow Measurements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Specify a value in *--bandwidth* will limit the bandwidth when performing throughput tests.

The default behavior for both TCP/UDP are unlimited. For TCP, we are leveraging on the protocol itself to get the best performance; while for UDP, we are doing a binary search to find the optimal bandwidth.

This is useful when running vmtp on production clouds. The test tool will use up all the bandwidth that may be needed by any other live VMs if we don't set any bandwidth limit. This feature will help to prevent impacting other VMs while running the test tool.


Host Selection and Availability Zone
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

VMTP requires 1 physical host to perform intra-node tests and 2 hosts to perform inter-node tests.
There are multiple ways to specify the placement of test VMs to VMTP. By default, VMTP will pick the first 2 compute hosts it can find, regardless of the availability zone.

It is possible to limit the host selection to a specific availability zone by specifying its name in the yaml configuration file ('availability_name' parameter).

The *--hypervisor* argument can also be used to specify explicitly on which hosts to run the test VMs. The first *--hypervisor* argument specifies on which host to run the test server VM. The second *--hypervisor* argument (in the command line) specifies on which host to run the test client VMs.

The syntax to use for the argument value is either availability_zone and host name separated by a column (e.g. "--hypervisor nova:host26") or host name (e.g. "--hypervisor host12"). In the latter case, VMTP will automaticaly pick the availability zone of the host.

Picking a particular host can be handy for example when exact VM placement can impact the data path performance (for example rack based placement).

The value of the argument must match the hypervisor host name as known by OpenStack (or as displayed using "nova hypervisor-list").

If an availability zone is provided, VMTP will check that the host name exists in that availability zone.


Upload Images to Glance
^^^^^^^^^^^^^^^^^^^^^^^

VMTP requires a Linux image available in Glance to spawn VMs. It could be uploaded manually through Horizon or CLI, or VMTP will try to upload the image defined in the configuration file automatically.

There is a candidate image defined in the default config already. It has been verified working, but of course it is OK to try other Linux distro as well.

**NOTE:** Due to the limitation of the Python glanceclient API (v2.0), it is not able to create the image directly from a remote URL. So the implementation of this feature used a glance CLI command instead. Be sure to source the OpenStack rc file first before running VMTP with this feature.


Examples of running VMTP on an OpenStack Cloud
----------------------------------------------

Preparation
^^^^^^^^^^^

Download the openrc file from OpenStack Dashboard, and saved it to your local file system. (In Horizon dashboard: Project|Acces&Security!Api Access|Download OpenStack RC File)

Upload the Linux image to the OpenStack controller node, so that OpenStack is able to spawning VMs. You will be prompted an error if the Ubuntu image is not available to use when running the tool. The image can be uploaded using either Horizon dashboard, or the command below:

.. code::

    python vmtp.py -r admin-openrc.sh -p admin --vm_image_url http://<url_to_the_image>

**Note:** Currently, VMTP only supports the Linux image in qcow2 format.

If executing a VMTP Docker image "docker run" (or "sudo docker run") must be placed in front of these commands unless you run a shell script directly from inside the container.

Example 1: Typical Run
""""""""""""""""""""""
Run VMTP on an OpenStack cloud with the default configuration file, use "admin-openrc.sh" as the rc file, and "admin" as the password::

    python vmtp.py -r admin-openrc.sh -p admin

This will generate 6 standard sets of performance data:
(1) VM to VM same network (intra-node, private fixed IP)
(2) VM to VM different network (intra-node, L3 fixed IP)
(3) VM to VM different network and tenant (intra-node, floating IP)
(4) VM to VM same network (inter-node, private fixed IP)
(5) VM to VM different network (inter-node, L3 fixed IP)
(6) VM to VM different network and tenant (inter-node, floating IP)

By default, the performance data of all three protocols (TCP/UDP/ICMP) will be measured for each scenario mentioned above. However, it can be overridden by providing *--protocols*. E.g.::

    python vmtp.py -r admin-openrc.sh -p admin --protocols IT

This will tell VMTP to only collect ICMP and TCP measurements.

Example 2: Cloud upload/download performance measurement
""""""""""""""""""""""""""""""""""""""""""""""""""""""""

Run VMTP on an OpenStack cloud with a specified configuration file (mycfg.yaml), and saved the result to a JSON file::

    python vmtp.py -c mycfg.yaml -r admin-openrc.sh -p admin --external_host localadmin@172.29.87.29 --json res.json

This run will generate 8 sets of performance data, the standard 6 sets mentioned above, plus two sets of upload/download performance data for both TCP and UDP.

**Note:** In order to perform the upload/download performance test, an external server must be specified and configured with SSH password-less access. See below for more info.


Example 3: Store the OpenStack deployment details
"""""""""""""""""""""""""""""""""""""""""""""""""

Run VMTP on an OpenStack cloud, fetch the defails of the deployment and store it to JSON file. Assume the controlloer node is on 192.168.12.34 with admin/admin::

    python vmtp.py -r admin-openrc.sh -p admin --json res.json --controller-node root@192.168.12.34:admin


Example 4: Specify which availability zone to spawn VMs
"""""""""""""""""""""""""""""""""""""""""""""""""""""""

Run VMTP on an OpenStack cloud, spawn the test server VM on tme212, and the test client VM on tme210. Save the result, and perform the inter-node measurement only::

    python vmtp.py -r admin-openrc.sh -p admin --inter-node-only --json res.json --hypervisor tme212 --hypervisor tme210

Example 5: Collect native host performance data
"""""""""""""""""""""""""""""""""""""""""""""""

Run VMTP to get native host throughput between 172.29.87.29 and 172.29.87.30 using the localadmin ssh username and run each tcp/udp test session for 120 seconds (instead of the default 10 seconds)::

    python vmtp.py --host localadmin@172.29.87.29 --host localadmin@172.29.87.30 --time 120

**Note:** This command requires each host to have the VMTP public key (ssh/id_rsa.pub) inserted into the ssh/authorized_keys file in the username home directory, i.e. SSH password-less access. See below for more info.

Example 6: Measurement on pre-existing VMs
""""""""""""""""""""""""""""""""""""""""""

It is possible to run VMTP between pre-existing VMs that are accessible through SSH (using floating IP).

The first IP passed (*--host*) is always the one running the server side. Optionally a server side listening interface name can be passed if clients should connect using a particular server IP. For example, to measure throughput between 2 hosts using the network attached to the server interface "eth5"::

    python vmtp.py --host localadmin@172.29.87.29:eth5 --host localadmin@172.29.87.30

**Note:** Prior to running, the VMTP public key must be installed on each VM.


======
Setups
======

Public Cloud
------------

Public clouds are special because they may not expose all OpenStack APIs and may not allow all types of operations. Some public clouds have limitations in the way virtual networks can be used or require the use of a specific external router. Running VMTP against a public cloud will require a specific configuration file that takes into account those specificities.

Refer to the provided public cloud sample configuration files for more information.

SSH Password-less Access
------------------------

For host throughput (*--host*), VMTP expects the target hosts to be pre-provisioned with a public key in order to allow password-less SSH.

Test VMs are created through OpenStack by VMTP with the appropriate public key to allow password-less ssh. By default, VMTP uses a default VMTP public key located in ssh/id_rsa.pub, simply append the content of that file into the .ssh/authorized_keys file under the host login home directory).

**Note:** This default VMTP public key should only be used for transient test VMs and **MUST NOT** be used to provision native hosts since the corresponding private key is open to anybody! To use alternate key pairs, the 'private_key_file' variable in the configuration file must be overridden to point to the file containing the private key to use to connect with SSH.


===============
Implementations
===============

TCP Throughput Measurement
--------------------------

The TCP throughput reported is measured using the default message size of the test tool (64KB with nuttcp). The TCP MSS (maximum segment size) used is the one suggested by the TCP-IP stack (which is dependent on the MTU).


UDP Throughput Measurement
--------------------------
UDP throughput is tricky because of limitations of the performance tools used, limitations of the Linux kernel used and criteria for finding the throughput to report.

The default setting is to find the "optimal" throughput with packet loss rate within the 2%~5% range. This is achieved by successive iterations at different throughput values.

In some cases, it is not possible to converge with a loss rate within that range and trying to do so may require too many iterations. The algorithm used is empiric and tries to achieve a result within a reasonable and bounded number of iterations. In most cases the optimal throughput is found in less than 30 seconds for any given flow.

**Note:** UDP measurements are only available with nuttcp (not available with iperf).


========================
Caveats and Known Issues
========================

* UDP throughput is not available if iperf is selected (the iperf UDP reported results are not reliable enough for iterating)

* If VMTP hangs for native hosts throughputs, check firewall rules on the hosts to allow TCP/UDP ports 5001 and TCP port 5002

