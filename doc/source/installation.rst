============
Installation
============

There are two ways to install and run VMTP tool, Docker based, and GitHub/StackForge Repository based. Normally, a VMTP Docker image will satisfy most of use cases, and it is easy to start and use. Docker image is recommended if running under a production environment, or running through an automated or scheduled job. A git repository based installation gives more flexibility, and it is recommended for developing purposes.


Docker based Installation
-------------------------

Docker provides an easy and convenient way to run VMTP on Linux. The docker image pre-builds all the dependencies needed to run VMTP, including all the OpenStack python client libraries needed to access any OpenStack cloud, all the dependent python libraries and all the dependent distribution packages needed by these python libraries.

To run the container image all you need is docker.io installed on your Linux host. Refer `here <https://docs.docker.com/installation/#installation>`_ for details about how to install docker.

**Note:** An official image from Docker Hub is coming soon and this is a temporary private image.

Once the docker.io is installed, download the latest VMTP image from Docker Hub::

    $ sudo docker pull ahothan/vmtp

The new image will be shown in the list::

    $ sudo docker images
    REPOSITORY          TAG                 IMAGE ID            CREATED             VIRTUAL SIZE
    ahothan/vmtp        2.0.0               9f08056496d7        27 hours ago        494.6 MB
    ahothan/vmtp        latest              9f08056496d7        27 hours ago        494.6 MB

Alternatively, for development or test purpose, a binary image could be loaded from a filesystem as well::

    $ sudo docker load -i vmtp_image

Note that the image loaded from archive doesn't have a TAG, so the exact image ID must be specified to all docker commands mentioned below.

In its Docker image form, VMTP is located under the /vmtp directory in the container and can either take arguments from the host shell, or can be executed from inside the Docker image shell.

To run VMTP directly from the host shell::

    $ sudo docker run <vmtp-docker-image-name> python /vmtp/vmtp.py <args>

To run VMTP from the Docker image shell::

    $ sudo docker run <vmtp-docker-image-name>
    $ cd /vmtp.py
    $ python vmtp.py <args>

(then type exit to exit and terminate the container instance)


Docker Shared Volume to Share Files with the Container
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

VMTP can accept files as input (e.g. configuration and openrc file) and can generate json results into a file. It is possible to use the VMTP Docker image with files persisted on the host by using Docker shared volumes.

For example, to get a copy of the VMTP default configuration file from the container::

    $ sudo docker run -v $PWD:/vmtp/shared:rw -t <docker-vmtp-image-name>  cp /vmtp/cfg.default.yaml /vmtp/shared/mycfg.yaml

The local directory to share ($PWD) is to be mapped to /vmtp/shared in the container in read/write mode. That way, mycfg.yaml will be copied to the local directory on the host.

Assume you have edited the configuration file "mycfg.yaml", retrieved an openrc file "admin-openrc.sh" from Horizon on the local directory, and would like to get results back in the "res.json" file. What you can do is to map the current directory ($PWD) to /vmtp/shared inside the container in read/write mode, then run the script inside the container and use use files from the shared directory.

E.g. From the host shell, you could do that in one-shot::

    $ sudo docker run -v $PWD:/vmtp/shared:rw -t <docker-vmtp-image-name> python /vmtp/vmtp.py -c shared/mycfg.yaml -r shared/admin-openrc.sh -p admin --json shared/res.json
    $ cat res.json

Or from the Docker image shell::

    $ sudo docker run -v $PWD:/vmtp/shared:rw -t <docker-vmtp-image-name>
    $ python /vmtp/vmtp.py -c shared/mycfg.yaml -r shared/admin-openrc.sh -p admin --json shared/res.json
    $ cat shared/res.json


.. _git_installation:

GitHub/StackForge Repository based Installation
-----------------------------------------------

It is recommended to run VMTP inside a virtual environment. However, it can be skipped if installed in a dedicated VM.


Super quick installation on Ubuntu/Debian
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code::

    $ sudo apt-get install python-dev python-virtualenv git git-review
    $ sudo apt-get install libxml2-dev libxslt-dev libffi-dev libz-dev libyaml-dev libssl-dev
    $ # create a virtual environment
    $ virtualenv ./vmtpenv
    $ source ./vmtpenv/bin/activate
    $ git clone git://git.openstack.org/stackforge/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ python vmtp.py -h


Super quick installation on MacOSX
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

VMTP can run natively on MacOSX. These instructions have been verified to work on MacOSX 10.10 (Yosemite).

First, download XCode from App Store, then execute below commands:

.. code::

    $ # Download the XCode command line tools
    $ code-select --install
    $ # Install pip
    $ sudo easy_install pip
    $ # Install python virtualenv
    $ sudo pip install virtualenv
    $ # create a virtual environment
    $ virtualenv ./vmtpenv
    $ source ./vmtpenv/bin/activate
    $ git clone git://git.openstack.org/stackforge/vmtp
    $ cd vmtp
    $ pip install -r requirements-dev.txt
    $ python vmtp.py -h
