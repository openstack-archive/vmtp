=====
Usage
=====

VMTP Usage
----------

.. code::

    usage: vmtp [-h] [-c <config_file>] [-sc] [-r <openrc_file>]
                [-m <gmond_ip>[:<port>]] [-p <password>] [-t <time>]
                [--host <user>@<host_ssh_ip>[:<password>:<server-listen-if-name>]]
                [--external-host <user>@<host_ssh_ip>[:password>]]
                [--controller-node <user>@<host_ssh_ip>[:<password>]]
                [--mongod-server <server ip>] [--json <file>]
                [--tp-tool <nuttcp|iperf>]
                [--availability_zone <availability_zone>] [--hypervisor [<az>:]
                <hostname>] [--inter-node-only] [--same-network-only]
                [--protocols <T|U|I>] [--bandwidth <bandwidth>]
                [--tcpbuf <tcp_pkt_size1,...>] [--udpbuf <udp_pkt_size1,...>]
                [--reuse_network_name <network_name>]
                [--os-dataplane-network <network_name>] [--delete-image-after-run]
                [--no-env] [--vnic-type <direct|macvtap|normal>] [-d] [-v]
                [--stop-on-error] [--vm-image-url <url_to_image>]
                [--test-description <test_description>]

    optional arguments:
      -h, --help            show this help message and exit
      -c <config_file>, --config <config_file>
                            override default values with a config file
      -sc, --show-config    print the default config
      -r <openrc_file>, --rc <openrc_file>
                            source OpenStack credentials from rc file
      -m <gmond_ip>[:<port>], --monitor <gmond_ip>[:<port>]
                            Enable CPU monitoring (requires Ganglia)
      -p <password>, --password <password>
                            OpenStack password
      -t <time>, --time <time>
                            throughput test duration in seconds (default 10 sec)
      --host <user>@<host_ssh_ip>[:<password>:<server-listen-if-name>]
                            native host throughput (password or public key
                            required)
      --external-host <user>@<host_ssh_ip>[:password>]
                            external-VM throughput (password or public key
                            required)
      --controller-node <user>@<host_ssh_ip>[:<password>]
                            controller node ssh (password or public key required)
      --mongod-server <server ip>
                            provide mongoDB server IP to store results
      --json <file>         store results in json format file
      --tp-tool <nuttcp|iperf>
                            transport perf tool to use (default=nuttcp)
      --availability_zone <availability_zone>
                            availability zone for running VMTP
      --hypervisor [<az>:] <hostname>
                            hypervisor to use (1 per arg, up to 2 args)
      --inter-node-only     only measure inter-node
      --same-network-only   only measure same network
      --protocols <T|U|I>   protocols T(TCP), U(UDP), I(ICMP) - default=TUI (all)
      --bandwidth <bandwidth>
                            the bandwidth limit for TCP/UDP flows in K/M/Gbps,
                            e.g. 128K/32M/5G. (default=no limit)
      --tcpbuf <tcp_pkt_size1,...>
                            list of buffer length when transmitting over TCP in
                            Bytes, e.g. --tcpbuf 8192,65536. (default=65536)
      --udpbuf <udp_pkt_size1,...>
                            list of buffer length when transmitting over UDP in
                            Bytes, e.g. --udpbuf 128,2048. (default=128,1024,8192)
      --reuse_network_name <network_name>
                            the network to be reused for performing tests
      --os-dataplane-network <network_name>
                            Internal network name for OpenStack to hold data plane
                            traffic
      --delete-image-after-run
                            delete image that are uploaded by VMTP when tests are
                            finished
      --no-env              do not read env variables
      --vnic-type <direct|macvtap|normal>
                            binding vnic type for test VMs
      -d, --debug           debug flag (very verbose)
      -v, --version         print version of this script and exit
      --stop-on-error       Stop and keep everything as-is on error (must cleanup
                            manually)
      --vm-image-url <url_to_image>
                            URL to a Linux image in qcow2 format that can be
                            downloaded fromor location of the image file with
                            prefix file://
      --test-description <test_description>
                            The test description to be stored in JSON or MongoDB

Configuration File
^^^^^^^^^^^^^^^^^^

VMTP configuration files follow the yaml syntax and contain variables used by VMTP to run and collect performance data.
The default configuration is stored in the cfg.default.yaml file.

Default values should be overwritten for any cloud under test by defining new variable values in a new configuration file that follows the same format.
Variables that are not defined in the new configuration file will retain their default values.

The precedence order for configuration files is as follows:
- the command line argument "-c <file>" has highest precedence
- $HOME/.vmtp.yaml if the file exists in the user home directory
- cfg.default.yaml has the lowest precedence (always exists in the VMTP package root directory)

To override a default value set in cfg.default.yaml, simply redefine that value in the configuration file passed in -c or in the $HOME/.vmtp.yaml file.
Check the content of cfg.default.yaml file as it contains the list of configuration variables and instructions on how to set them.

.. note:: The configuration file is not needed if VMTP only runs the native host throughput option (*--host*)


OpenStack openrc File
^^^^^^^^^^^^^^^^^^^^^

VMTP requires downloading an "openrc" file from the OpenStack Dashboard (Project|Acces&Security!Api Access|Download OpenStack RC File)

This file should then be passed to VMTP using the *-r* option or should be sourced prior to invoking VMTP.

.. note:: The openrc file is not needed if VMTP only runs the native host throughput option (*--host*)


Access Info for Controller Node
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default, VMTP is not able to get the Linux distro nor the OpenStack version of the cloud deployment under test.
However, by providing the credentials of the controller node under test, VMTP will try to fetch these information, and output them along in the JSON file or to the MongoDB server.
For example to retrieve the OpenStack distribution information on a given controller node::

    python vmtp.py --json tb172.json --test-description 'Testbed 172' --controller-node root@172.22.191.172

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


VNIC Type and SR-IOV Support
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

By default test VMs will be created with ports that have a "normal" VNIC type. To create test VMs with ports that use PCI passthrough SR-IOV, specify **--vnic_type direct**. This will assume that the host where the VM are instantiated have SR-IOV capable NIC.

An exception will be thrown if a test VM is lauched on a host that does not have SRIOV capable NIC or has not been configured to use such feature.


Provider Network
^^^^^^^^^^^^^^^^

Provider networks are created by network administrators, which specifies the details of how network is physically realized, and usually match some existing networks in the data center. In general, provider networks only handle layer-2 connectivity for instances, and lack the concept of fixed and floating IP addresses. Running VMTP on provider network, means that VMTP is directly running on the infrastructure VLAN and no L3 in OpenStack is involved (L3 will be handled in the legacy L3 Router).

VMTP supports to run on a provider network by supplying the provider network name via either CLI or config file with **--reuse_network_name <network_name>**. Just happens that this mode allows to run on real provider network, but also the regular neutron network settings (e.g. VxLAN) where the user would like VMTP to reuse an already created network. VMTP will perform the L2-only throughput tests on the network provided when this parameter is set.

Note that the fixed IP addresses assigned to the test VM on the provider network must be reachable from the host which VMTP application is running on.


Examples of running VMTP on an OpenStack Cloud
----------------------------------------------
Examples below invoke VMTP using the python interpreter (suitable for git installation). For Docker container or pip installation, simply invoke vmtp directly (instead of "python vmtp.py").


Example 1: Typical Run
^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run VMTP on an OpenStack cloud with a specified configuration file (mycfg.yaml), and saved the result to a JSON file::

    python vmtp.py -c mycfg.yaml -r admin-openrc.sh -p admin --external-host localadmin@172.29.87.29 --json res.json

This run will generate 8 sets of performance data, the standard 6 sets mentioned above, plus two sets of upload/download performance data for both TCP and UDP.
If you do not have ssh password-less access to the external host (public key) you must specify a password::

    python vmtp.py -c mycfg.yaml -r admin-openrc.sh -p admin --external-host localadmin@172.29.87.29:secret --json res.json

Example 3: Retrieve the OpenStack deployment details
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run VMTP on an OpenStack cloud, fetch the details of the deployment and store it to JSON file. Assume the controller node is on 192.168.12.34 with admin/admin::

    python vmtp.py -r admin-openrc.sh -p admin --json res.json --controller-node root@192.168.12.34:admin

In addition, VMTP also supports to store the results to a MongoDB server::
    
    python vmtp.py -r admin-openrc.sh -p admin --json res.json --mongod-server 172.29.87.29 --controller-node root@192.168.12.34:admin

Before storing info into MongoDB, some configurations are needed to change to fit in your environment. By default, VMTP will store to database "client_db" with collection name "pns_web_entry", and of course these can be changed in the configuration file. Below are the fields which are related to accessing MongoDB::

   vmtp_mongod_port
   vmtp_db
   vmtp_collection


Example 4: Specify which compute nodes to spawn VMs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run VMTP on an OpenStack cloud, spawn the test server VM on tme212, and the test client VM on tme210. Save the result, and perform the inter-node measurement only::

    python vmtp.py -r admin-openrc.sh -p admin --inter-node-only --json res.json --hypervisor tme212 --hypervisor tme210


Example 5: Collect native host performance data
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Run VMTP to get native host throughput between 172.29.87.29 and 172.29.87.30 using the localadmin ssh username and run each tcp/udp test session for 120 seconds (instead of the default 10 seconds)::

    python vmtp.py --host localadmin@172.29.87.29 --host localadmin@172.29.87.30 --time 120

The first IP passed (*--host*) is always the one running the server side.
If you do not have public keys setup on these targets, you must provide a password::

    python vmtp.py --host localadmin@172.29.87.29:secret --host localadmin@172.29.87.30:secret --time 120

It is also possible to run VMTP between pre-existing VMs that are accessible through SSH (using floating IP) if you have the corresponding private key to access them.

In the case of servers that have multiple NIC and IP addresses, it is possible to specify the server side listening interface name to use (if you want the client side to connect using the associated IP address)
For example, to measure throughput between 2 hosts using the network attached to the server interface "eth5"::

    python vmtp.py --host localadmin@172.29.87.29::eth5 --host localadmin@172.29.87.30


Example 6: IPV6 throughput measurement
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is possible to use VMTP to measure throughput for IPv6.

Set ipv6_mode to slaac, dhcpv6-stateful or dhcpv6-stateless. If SLAAC or DHCPv6 stateless is enabled make sure to have radvd packaged in as part of openstack install. For DHCPv6 stateful you need dnsmasq version >= 2.68. The test creates 2 networks and creates 1 IPv4 and 1 IPv6 subnet inside each of these networks. The subnets are created based on the IPv6 mode that you set in the configuration file. The Floating IP result case is skipped for IPv6 since there is no concept of a floating ip with IPv6. 


Running VMTP as a library
-------------------------

VMTP supports to be invoked from another Python program, just like an API call. Once the benchmarking is finished, the API will return a Python dictionary with all details.

Example of code for running VMTP as an API call:

.. code-block:: python

    import argparse
    opts = argparse.Namespace()
    opts.rc = "<path_to_rc_file>"
    opts.passwd = "<password_of_the_cloud>"
    opts.inter_node_only = True
    opts.json = "my.json"

    import vmtp
    vmtp.run_vmtp(opts)


Generating charts from JSON results
-----------------------------------

.. code::

    usage: vmtp_genchart.py [-h] [-c <file>] [-b] [-p <all|tcp|udp>] [-v]
                       <file> [<file> ...]

    VMTP Chart Generator V0.0.1

    positional arguments:
      <file>                vmtp json result file

    optional arguments:
      -h, --help            show this help message and exit
      -c <file>, --chart <file>
                            create and save chart in html file
      -b, --browser         display (-c) chart in the browser
      -p <all|tcp|udp>, --protocol <all|tcp|udp>
                            select protocols:all, tcp, udp
      -v, --version         print version of this script and exit

Examples of use:

Generate charts from the JSON results file "tb172.json", store resulting html to "tb172.html" and open that file in the browser::

    python vmtp_genchart.py --chart tb172.html --browser tb172.json
    
Same but only show UDP numbers::

    python vmtp_genchart.py --chart tb172.html --browser --protocol udp tb172.json

