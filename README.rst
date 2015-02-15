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

Pre-requisite to run VMTP
-------------------------

For VM related performance measurements
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Access to the cloud Horizon Dashboard
* 1 working external network pre-configured on the cloud (VMTP will pick the first one found)
* At least 2 floating IP if an external router is configured or 3 floating IP if there is no external router configured
* 1 Linux image available in OpenStack (any distribution)
* A configuration file that is properly set for the cloud to test (see "Configuration File" section below)

For native/external host throughputs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* A public key must be installed on the target hosts (see ssh password-less access below)

For pre-existing native host throughputs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* Firewalls must be configured to allow TCP/UDP ports 5001 and TCP port 5002

For running VMTP Docker Image
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Docker is installed. See `here <https://docs.docker.com/installation/#installation/>`_ for instructions.

Sample Results Output
---------------------

VMTP will display the results to stdout with the following data:

.. code::

    - Session general information (date, auth_url, OpenStack encaps, VMTP version...)
    - List of results per flow, for each flow:
    |   flow name
    |   to and from IP addresses
    |   to and from availability zones (if VM)
    |   - results:
    |   |   -TCP
    |   |   |  packet size
    |   |   |  throughput value
    |   |   |  number of retransmissions
    |   |   |  round trip time in ms
    |   |   |  - CPU usage (if enabled), for each host in the openstack cluster
    |   |   |  | baseline (before test starts)
    |   |   |  | 1 or more readings during test
    |   |   -UDP
    |   |   |  - for each packet size
    |   |   |  | throughput value
    |   |   |  | loss rate
    |   |   |  | CPU usage (if enabled)
    |   |   - ICMP
    |   |   |  average, min, max and stddev round trip time in ms

Detailed results can also be stored in a file in JSON format using the *--json* command line argument.

Documentation
^^^^^^^^^^^^^
For more information, see the `VMTP online documentation <http://vmtp.readthedocs.org>`_