============
Installation
============

There are two ways to install and run VMTP tool. Users of VMTP should use regular PyPI based installation, while developers of VMTP should use GitHub/StackForge Repository based installation. Normally, PyPI based installation will satisfy most of use cases, and it is the recommended way for running VMTP under production environments, or through an automated or scheduled job. A git repository based installation gives more flexibility, and it is a must for developers of VMTP.

.. note:: Installation from PyPI will only have the latest stable version.


PyPI based Installation
-----------------------

PyPI (The Python Package Index) is the official repository for software in Python. It holds lots of packages, and the installation is relatively easy in only 2 steps.

Step 1
^^^^^^

Install required development libraries. Run the command based on your distro.

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
    $ source ./vmtpenv/bin/activate
    $ pip install vmtp
    $ vmtp -h

.. note::

    "A Virtual Environment is a tool to keep the dependencies required by different projects in separate places, by creating virtual Python environments for them." It is optional but recommended. We could use::

    $ sudo pip install vmtp

    instead if isolation among multiple Python projects is not needed.


.. _git_installation:

GitHub/OpenStack Repository based Installation
----------------------------------------------

It is recommended to run VMTP inside a virtual environment. However, it can be skipped if installed in a dedicated VM.


Super quick installation on Ubuntu/Debian
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    $ sudo apt-get install build-essential python-dev python-pip python-virtualenv git git-review
    $ sudo apt-get install libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev
    $ # create a virtual environment
    $ virtualenv ./vmtpenv
    $ source ./vmtpenv/bin/activate
    $ git clone git://git.openstack.org/openstack/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ cd vmtp
    $ python vmtp.py -h

Super quick installation on RHEL/CentOS
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    $ sudo yum install gcc python-devel python-pip python-virtualenv git
    $ sudo yum install libxml2-devel libxslt-devel libffi-devel libyaml-devel openssl-devel
    $ sudo pip install git-review
    $ # create a virtual environment
    $ virtualenv ./vmtpenv
    $ source ./vmtpenv/bin/activate
    $ git clone git://git.openstack.org/openstack/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ cd vmtp
    $ python vmtp.py -h


Super quick installation on MacOSX
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

VMTP can run natively on MacOSX. These instructions have been verified to work on MacOSX 10.10 (Yosemite).

First, download XCode from App Store, then execute below commands:

.. code-block:: bash

    $ # Download the XCode command line tools
    $ xcode-select --install
    $ # Install pip
    $ sudo easy_install pip
    $ # Install python virtualenv
    $ sudo pip install virtualenv
    $ # create a virtual environment
    $ virtualenv ./vmtpenv
    $ source ./vmtpenv/bin/activate
    $ git clone git://git.openstack.org/openstack/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ cd vmtp
    $ python vmtp.py -h
