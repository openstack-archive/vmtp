============
Installation
============


Installing on Ubuntu/Debian
---------------------------

.. code::

    sudo apt-get install python-dev python-virtualenv git git-review
    sudo apt-get install libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev
    # create a virtual environment
    virtualenv ./vmtpenv
    source ./vmtpenv/bin/activate
    git clone git://git.openstack.org/stackforge/vmtp
    cd vmtp
    pip install -r requirements-dev.txt
    python vmtp.py -h

Installing on MacOSX
--------------------
VMTP can run natively on MacOSX. These instructions have been verified to work on MacOSX 10.10 (Yosemite). 

First download XCode from Apple Store.

.. code::

    # Download the XCode command line tools 
    code-select --install
    # Install pip
    sudo easy_install pip
    # Install python virtualenv
    sudo pip install virtualenv
    # create a virtual environment
    virtualenv ./vmtpenv
    source ./vmtpenv/bin/activate
    git clone git://git.openstack.org/stackforge/vmtp
    cd vmtp
    pip install -r requirements-dev.txt
    python vmtp.py -h