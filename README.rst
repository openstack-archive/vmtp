===============================
vmtp
===============================

A data path performance tool for OpenStack clouds.

* Free software: Apache license
* Documentation: http://docs.openstack.org/developer/vmtp
* Source: http://git.openstack.org/cgit/stackforge/vmtp
* Bugs: http://bugs.launchpad.net/vmtp

Features
--------

VMTP is a python application that will automatically perform ping connectivity, ping round trip time measuerment (latency) and TCP/UDP throughput measurement for the following flows on any OpenStack deployment:

* VM to VM same network (private fixed IP)
* VM to VM different network same tenant (intra-tenant L3 fixed IP)
* VM to VM different network and tenant (floating IP inter-tenant L3)

Optionally, when an external Linux host is available:

* external host/VM download and upload throughput/latency (L3/floating IP)

Optionally, when ssh login to any Linux host (native or virtual) is available:

* host to host throughput (intra-node and inter-node)

Optionally, VMTP can extract automatically CPU usage from all native hosts in the cloud during the throughput tests, provided the Ganglia monitoring service (gmond) is installed and enabled on those hosts.
