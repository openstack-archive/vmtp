=====
Usage
=====

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

    OpenStack VM Throughput V2.0.1

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

VMTP configuration files follow the yaml syntax and contain variables used by VMTP to run and collect performance data. The default configuration is stored in the cfg.default.yaml file.

Default values should be overwritten for any cloud under test by defining new variable values in a new configuration file that follows the same format. Variables that are not defined in the new configuration file will retain their default values.

Check the content of cfg.default.yaml file as it contains the list of configuration variables and instructions on how to set them.

**Note:** the configuration file is not needed if the VMTP only runs the native host throughput option (*--host*)


OpenStack openrc File
^^^^^^^^^^^^^^^^^^^^^

VMTP requires downloading an "openrc" file from the OpenStack Dashboard (Project|Acces&Security!Api Access|Download OpenStack RC File)

This file should then be passed to VMTP using the *-r* option or should be sourced prior to invoking VMTP.

**Note:** the openrc file is not needed if VMTP only runs the native host throughput option (*--host*)


Access Info for Controller Node
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, VMTP is not able to get the Linux distro nor the OpenStack version of the cloud deployment under test. However, by providing the credentials of the controller node under test, VMTP will try to fetch these information, and output them along in the JSON file or to the MongoDB server.


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

**Note:** Due to the limitation of the Python glanceclient API (v2.0), it is not able to create the image directly from a remote URL. So the implementation of this feature used a glance CLI command instead. Be sure to source the OpenStack rc file first before running VMTP with this feature.


Quick guide to run VMTP on an OpenStack Cloud
----------------------------------------------

Preparation
^^^^^^^^^^^

* Step 1)

Download the openrc file from OpenStack Dashboard, and saved it to your local file system. (In Horizon dashboard: Project|Acces&Security!Api Access|Download OpenStack RC File)

* Step 2)

Create one configuration file for your specific cloud and use the *-c* option to pass that file name to VMTP. Parameters that you are most certainly required to change are:

    **image_name**: The name of the Linux image that will run the test VMs created by vmtp. It must be set to an existing image available in openstack (check the name with Horizon or using "nova image-list" from the shell). Any recent Ubuntu or CentOS/Fedora image should work -- if needed you will need to upload an image to OpenStack manually prior to running VMTP.

    **ssh_vm_username**: VM SSH username to use (specific to the image)

    **flavor_type**: The flavor name to use (often specific to each cloud)

* Step 3)

Upload the Linux image to the OpenStack controller node, so that OpenStack is able to spawning VMs. You will be prompted an error if the image defined in the config file is not available to use when running the tool. The image can be uploaded using either Horizon dashboard, or the command below::
    python vmtp.py -r admin-openrc.sh -p admin --vm_image_url http://<url_to_the_image>

**Note:** Currently, VMTP only supports the Linux image in qcow2 format.


Examples of running VMTP on an OpenStack Cloud
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

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

By default, the performance data of all three protocols (TCP/UDP/ICMP) will be measured for each scenario mentioned above. However, it can be overridden by providing *--protocols*::

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


Example 4: Specify which compute nodes to spawn VMs
"""""""""""""""""""""""""""""""""""""""""""""""""""

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

Example 7: IPV6 throughput measurement
""""""""""""""""""""""""""""""""""""""""

It is possible to use VMTP to measure throughput for ipv6

Set ipv6_mode to slaac, dhcpv6-stateful or dhcpv6-stateless. If SLAAC or DHCPv6 stateless is enabled make sure to have
radvd packaged in as part of openstack install. For DHCPv6 stateful you need dnsmasq version >= 2.68. The test creates
2 networks and creates 1 ipv4 and 1 ipv6 subnet inside each of these networks. The subnets are created based on the ipv6
mode that you set in the configuration file. The floatingip result case is skipped for ipv6 since there is no concept of
a floating ip with ipv6. 

