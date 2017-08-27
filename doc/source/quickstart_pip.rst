============================================
VMTP PyPI Installation and Quick Start Guide
============================================

.. _pip_installation:

1. Installation
---------------

PyPI (The Python Package Index) is the most popular distribution repository for software in Python. 
The latest stable version of VMTP can be installed from PyPI using pip.

Step 1
^^^^^^

Install required libraries. Run the command based on your distro.

Ubuntu/Debian based:

.. code-block:: bash

    $ sudo apt-get install build-essential python-dev python-pip python-virtualenv git git-review
    $ sudo apt-get install libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev

RHEL/CentOS based:

.. code-block:: bash

    $ sudo yum install gcc python-devel python-pip python-virtualenv git
    $ sudo yum install libxml2-devel libxslt-devel libffi-devel libyaml-devel openssl-devel

MacOSX:

.. code-block:: bash

    $ # Download the XCode command line tools from Apple App Store
    $ xcode-select --install
    $ sudo easy_install pip
    $ sudo pip install virtualenv

Step 2
^^^^^^

Create a virtual environment for Python, and install VMTP:

.. code-block:: bash

    $ virtualenv ./vmtpenv
    $ . ./vmtpenv/bin/activate
    $ pip install vmtp
    $ vmtp -h

.. note::

    "A Virtual Environment is a tool to keep the dependencies required by different projects in separate places, by creating virtual Python environments for them." It is optional but recommended. If isolation among multiple Python projects is not needed, we could use instead::

    $ sudo pip install vmtp


2. Key Pair
-----------
VMTP requires a key pair to use to ssh to the test VMs that it will launch in OpenStack.
You can use the current user's key pair (located in $HOME/.ssh on the host where you run the container) if they exist:

.. code-block:: bash

    $ ls -l ~/.ssh/id*
    -rw------- 1 localadmin localadmin 1679 Mar  9  2015 /home/localadmin/.ssh/id_rsa
    -rw-r--r-- 1 localadmin localadmin  400 Mar  9  2015 /home/localadmin/.ssh/id_rsa.pub

Otherwise you need to create a key pair on your host:

.. code-block:: bash

    ssh-keygen -t rsa


3. Download RC file
-------------------

VMTP requires downloading an "openrc" file from the OpenStack Dashboard (Project|Acces&Security!Api Access|Download OpenStack RC File). That RC file is required to connect to OpenStack using the OpenStack API.
This file should be passed to VMTP using the *-r* option or should be sourced prior to invoking VMTP.
In this example we assume the RC file is saved in the current directory under the name "admin-openrc.sh".


4. Preparation steps with OpenStack
-----------------------------------

In the VMTP virtual environment, you can run any OpenStack CLI command (since the virtual environment will have all standard OpenStack client packages installed along with VMTP). Source the RC file so we can execute the CLI commands:

.. code-block:: bash

    source admin-openrc.sh


4.1. Verify flavor names
^^^^^^^^^^^^^^^^^^^^^^^^

If you are planning to reuse an existing flavor, we will have to check the flavor names available to select one flavor that VMTP should use to launch VM instances.
List the flavors (results may be different):

.. code-block:: bash

    $ nova flavor-list
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | ID | Name      | Memory_MB | Disk | Ephemeral | Swap | VCPUs | RXTX_Factor | Is_Public |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    | 1  | m1.tiny   | 512       | 1    | 0         |      | 1     | 1.0         | True      |
    | 2  | m1.small  | 2048      | 20   | 0         |      | 1     | 1.0         | True      |
    | 3  | m1.medium | 4096      | 40   | 0         |      | 2     | 1.0         | True      |
    | 4  | m1.large  | 8192      | 80   | 0         |      | 4     | 1.0         | True      |
    | 5  | m1.xlarge | 16384     | 160  | 0         |      | 8     | 1.0         | True      |
    +----+-----------+-----------+------+-----------+------+-------+-------------+-----------+
    $

Otherwise, a temporary flavor can be created for you from the config file specification (Step 5).

4.2. Upload any Linux VM image to OpenStack
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

VMTP requires a standard Linux VM image to run its tests in OpenStack.
You can skip this step if you already have a standard Linux VM image in your OpenStack (Ubuntu, Fedora, RHEL...).

Otherwise, you can upload any Linux VM image using the glance CLI or using the Horizon dashboard.
In the example below we will upload the Ubuntu 14.04 cloud image available from the uec-images.ubuntu.com web site using the glance CLI and we will name it "Ubuntu Server 14.04".

If your OpenStack can access directly the Internet:

.. code-block:: bash

    glance --os-image-api-version 1 image-create --copy-from http://uec-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-uefi1.img --disk-format qcow2 --container-format bare --name 'Ubuntu Server 14.04'

The glance command will return immediately but it will take some time for the file to get transferred. You will need to check for the status of the image before you can use it (will "queued", then "saving" then "active" if there is no issue).


If you prefer to make a local copy of the image:

.. code-block:: bash

    wget http://uec-images.ubuntu.com/trusty/current/trusty-server-cloudimg-amd64-uefi1.img

Then copy it to OpenStack using the glance CLI:

.. code-block:: bash

    glance --os-image-api-version 1 image-create --file /tmp/vmtp/trusty-server-cloudimg-amd64-uefi1.img --disk-format qcow2 --container-format bare --name 'Ubuntu 14.04'

Then list the images to verify:

.. code-block:: bash

    $ glance image-list
    +--------------------------------------+---------------------+
    | ID                                   | Name                |
    +--------------------------------------+---------------------+
    | 5d7899d9-811c-483f-82b3-282a9bf143bf | cirros              |
    | 443ee290-b714-4bfe-9acb-b996ed6cc118 | Ubuntu 14.04        |
    +--------------------------------------+---------------------+
    $ glance image-show 443ee290-b714-4bfe-9acb-b996ed6cc118
    +------------------+--------------------------------------+
    | Property         | Value                                |
    +------------------+--------------------------------------+
    | checksum         | 479a314d90cefc163fdcfb875a070cd8     |
    | container_format | bare                                 |
    | created_at       | 2016-07-04T17:53:20Z                 |
    | disk_format      | qcow2                                |
    | id               | 443ee290-b714-4bfe-9acb-b996ed6cc118 |
    | min_disk         | 0                                    |
    | min_ram          | 0                                    |
    | name             | Ubuntu 14.04                         |
    | owner            | 5d912149f7474804824a463464874a21     |
    | protected        | False                                |
    | size             | 268829184                            |
    | status           | active                               |
    | tags             | []                                   |
    | updated_at       | 2016-07-04T18:06:38Z                 |
    | virtual_size     | None                                 |
    | visibility       | private                              |
    +------------------+--------------------------------------+
    $


5. Create your VMTP config file
-------------------------------

Get a copy of the default VMTP configuration file and save it in the local directory:

.. code-block:: bash

    vmtp -sc > vmtp.cfg

Edit the vmtp.cfg file and make sure the following parameters are set properly:

- "image_name" must be the image name to use by VMTP ('Ubuntu Server 14.04' in the above example)
- "ssh_vm_username" must be a valid user name for the Linux image ("ubuntu" for Ubuntu images)
- "flavor_type" must be either an appropriate flavor name (step 4.1 above) or a custom flavor will be created with "flavor_type" name and specification declared in "flavor" config.
- "flavor" must be the specification of a custom flavor that will be created in case "flavor_type" is non-existing in OpenStack.

6. Run VMTP
-----------

VMTP options used:

* -d : debug mode (more verbose)
* -c vmtp.cfg : specify the config file to use
* -r admin-openrc.sh : specify the RC file to use
* -p secret : specify the OpenStack password to use (replace with your own password)
* --protocol T : only do TCP throughput test (shorter time)
* --json test.json : save results in json format to a file

.. code-block:: bash

    vmtp -d -c vmtp.cfg -r admin-openrc.sh -p secret --protocol T --json test.json

This should produce an output similar to this (a complete run with the above options should take around 15 minutes but may vary based on the control plane speed of your OpenStack cloud):

.. code-block:: bash

    Using http://172.29.86.28:5000/v2.0
    VM public key:  /home/localadmin/.ssh/id_rsa.pub
    VM private key: /home/localadmin/.ssh/id_rsa
    Found image Ubuntu Server 14.04 to launch VM, will continue
    Using external network: ext-net
    Found external router: demo-router
    Created internal network: pns-internal-net
    Created internal network: pns-internal-net2
    Ext router associated to pns-internal-net
    Ext router associated to pns-internal-net2
    OpenStack agent: Open vSwitch agent
    OpenStack network type: vlan
    [TestServer1] Creating server VM...
    [TestServer1] Starting on zone nova:compute-server-2
    [TestServer1] VM status=BUILD, retrying 1 of 50...
    [TestServer1] VM status=BUILD, retrying 2 of 50...
    ...
    [TestServer1] Floating IP 10.23.220.45 created
    [TestServer1] Started - associating floating IP 10.23.220.45
    [TestServer1] Internal network IP: 192.168.1.3
    [TestServer1] SSH IP: 10.23.220.45
    [TestServer1] Setup SSH for ubuntu@10.23.220.45
    [TestServer1] Installing nuttcp-7.3.2...
    [TestServer1] Copying nuttcp-7.3.2 to target...
    [TestServer1] Starting nuttcp-7.3.2 server...
    [TestServer1]
    [TestClient1] Creating client VM...
    [TestClient1] Starting on zone nova:compute-server-2
    [TestClient1] VM status=BUILD, retrying 1 of 50...
    [TestClient1] VM status=BUILD, retrying 2 of 50...
    ...
    [TestClient1] Floating IP 10.23.220.46 created
    [TestClient1] Started - associating floating IP 10.23.220.46
    [TestClient1] Internal network IP: 192.168.1.4
    [TestClient1] SSH IP: 10.23.220.46
    [TestClient1] Setup SSH for ubuntu@10.23.220.46
    [TestClient1] Installing nuttcp-7.3.2...
    [TestClient1] Copying nuttcp-7.3.2 to target...
    ============================================================
    Flow 1: VM to VM same network fixed IP (intra-node)
    [TestClient1] Measuring TCP Throughput (packet size=65536)...
    [TestClient1] /tmp/nuttcp-7.3.2 -T10  -l65536 -p5001 -P5002 -fparse 192.168.1.3
    [TestClient1] megabytes=20329.1875 real_seconds=10.00 rate_Mbps=17049.6212 tx_cpu=92 rx_cpu=53 retrans=0 rtt_ms=0.47
    ...
    {   'az_from': u'nova:compute-server-2',
        'az_to': u'nova:compute-server-2',
        'desc': 'VM to VM same network fixed IP (intra-node)',
        'distro_id': 'Ubuntu',
        'distro_version': '14.04',
        'ip_from': u'192.168.1.4',
        'ip_to': u'192.168.1.3',
        'results': [   {   'pkt_size': 65536,
                           'protocol': 'TCP',
                           'rtt_ms': 0.47,
                           'throughput_kbps': 17458812,
                           'tool': 'nuttcp-7.3.2'},
                       {   'pkt_size': 65536,
                           'protocol': 'TCP',
                           'rtt_ms': 0.19,
                           'throughput_kbps': 13832383,
                           'tool': 'nuttcp-7.3.2'},
                       {   'pkt_size': 65536,
                           'protocol': 'TCP',
                           'rtt_ms': 0.21,
                           'throughput_kbps': 17130867,
                           'tool': 'nuttcp-7.3.2'}]}
    [TestClient1] Floating IP 10.23.220.46 deleted
    [TestClient1] Instance deleted
    [TestClient2] Creating client VM...
    [TestClient2] Starting on zone nova:compute-server-2
    [TestClient2] VM status=BUILD, retrying 1 of 50...
    [TestClient2] VM status=BUILD, retrying 2 of 50...

    ...

    ---- Cleanup ----
    [TestServer1] Terminating nuttcp-7.3.2
    [TestServer1] Floating IP 10.23.220.45 deleted
    [TestServer1] Instance deleted
    Network pns-internal-net deleted
    Network pns-internal-net2 deleted
    Removed public key pns_public_key
    Deleting security group

    Summary of results
    ==================
    Total Scenarios:   22
    Passed Scenarios:  5 [100.00%]
    Failed Scenarios:  0 [0.00%]
    Skipped Scenarios: 17
    +----------+--------------------------------------------------+-------------------+----------------------------------------------+
    | Scenario | Scenario Name                                    | Functional Status | Data                                         |
    +----------+--------------------------------------------------+-------------------+----------------------------------------------+
    | 1.1      | Same Network, Fixed IP, Intra-node, TCP          | PASSED            | {'tp_kbps': '16140687', 'rtt_ms': '0.29'}    |
    | 1.2      | Same Network, Fixed IP, Intra-node, UDP          | SKIPPED           | {}                                           |
    | 1.3      | Same Network, Fixed IP, Intra-node, ICMP         | SKIPPED           | {}                                           |
    | 2.1      | Same Network, Fixed IP, Inter-node, TCP          | PASSED            | {'tp_kbps': '4082749', 'rtt_ms': '0.5'}      |
    | 2.2      | Same Network, Fixed IP, Inter-node, UDP          | SKIPPED           | {}                                           |
    | 2.3      | Same Network, Fixed IP, Inter-node, ICMP         | SKIPPED           | {}                                           |
    | 3.1      | Different Network, Fixed IP, Intra-node, TCP     | PASSED            | {'tp_kbps': '2371753', 'rtt_ms': '0.386667'} |
    | 3.2      | Different Network, Fixed IP, Intra-node, UDP     | SKIPPED           | {}                                           |
    | 3.3      | Different Network, Fixed IP, Intra-node, ICMP    | SKIPPED           | {}                                           |
    | 4.1      | Different Network, Fixed IP, Inter-node, TCP     | PASSED            | {'tp_kbps': '2036303', 'rtt_ms': '0.623333'} |
    | 4.2      | Different Network, Fixed IP, Inter-node, UDP     | SKIPPED           | {}                                           |
    | 4.3      | Different Network, Fixed IP, Inter-node, ICMP    | SKIPPED           | {}                                           |
    | 5.1      | Different Network, Floating IP, Intra-node, TCP  | PASSED            | {'tp_kbps': '2260145', 'rtt_ms': '0.476667'} |
    | 5.2      | Different Network, Floating IP, Intra-node, UDP  | SKIPPED           | {}                                           |
    | 5.3      | Different Network, Floating IP, Intra-node, ICMP | SKIPPED           | {}                                           |
    | 6.1      | Different Network, Floating IP, Inter-node, TCP  | PASSED            | {'tp_kbps': '2134303', 'rtt_ms': '0.543333'} |
    | 6.2      | Different Network, Floating IP, Inter-node, UDP  | SKIPPED           | {}                                           |
    | 6.3      | Different Network, Floating IP, Inter-node, ICMP | SKIPPED           | {}                                           |
    | 7.1      | Native Throughput, TCP                           | SKIPPED           | {}                                           |
    | 7.2      | Native Throughput, UDP                           | SKIPPED           | {}                                           |
    | 7.3      | Native Throughput, ICMP                          | SKIPPED           | {}                                           |
    | 8.1      | VM to Host Uploading                             | SKIPPED           | {}                                           |
    | 8.2      | VM to Host Downloading                           | SKIPPED           | {}                                           |
    +----------+--------------------------------------------------+-------------------+----------------------------------------------+
    Saving results in json file: test.json...


8. Generate the results chart from the JSON result file
-------------------------------------------------------

Assuming the json result file is saved by the container run the vmtp_genchart container command from the host current directory:

.. code-block:: bash

    $ vmtp_genchart -c test.html test.json
    Generating chart drawing code to /tmp/vmtp/test.html...
    $

vmtp_genchart options:

* -c test.html : save the generated html file to the mapped directory
* test.json : the json file that contains the results of the VMTP run

The fie is available in the current directory and can be viewed with any browser:

.. code-block:: bash

    $ ls -l test.html
    -rw-r--r-- 1 root root 1557 Jul  4 14:10 test.html


