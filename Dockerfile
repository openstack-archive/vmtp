# docker file for creating a container that has vmtp installed and ready to use
FROM ubuntu:14.04
MAINTAINER vmtp-core <vmtp-core@lists.launchpad.net>

# Install VMTP script and dependencies
RUN apt-get update && apt-get install -y \
       libz-dev \
       libffi-dev \
       libssl-dev \
       libxml2-dev \
       libxslt-dev \
       libyaml-dev \
       python \
       python-dev \
       python-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install pip --upgrade
RUN pip install pbr setuptools
RUN pip install vmtp

