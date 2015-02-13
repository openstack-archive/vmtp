============
Installation
============

For people who wants to do development for VMTP, it is recommended to set up the develop environments as below. However, for people who just wants to run the tool, or without root access, please refer to the "How to Run VMTP Tool" section and use VMTP Docker Image instead.

Here is an example for Ubuntu developers, and similar packages can be found and installed on RPM-based distro as well.

.. code::

    $ sudo apt-get install python-dev python-virtualenv git git-review
    $ sudo apt-get install libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev
    $ virtualenv vmtpenv
    $ source vmtpenv/bin/activate
    $ git clone git://git.openstack.org/stackforge/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ python vmtp.py -h
