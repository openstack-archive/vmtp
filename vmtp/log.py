# Copyright 2016 Cisco Systems, Inc.  All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging

def setup(product_name, debug=False, logfile=None):
    log_level = logging.DEBUG if debug else logging.INFO
    console_handler = file_handler = None

    # logging.basicConfig()
    console_formatter_str = '%(asctime)s %(levelname)s %(message)s'
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(console_formatter_str))

    # Add a FileHandler if logfile is supplied
    if logfile:
        file_formatter_str = '%(asctime)s %(levelname)s %(message)s'
        file_handler = logging.FileHandler(logfile, mode='w')
        file_handler.setFormatter(logging.Formatter(file_formatter_str))

    # Add appropriate handlers to loggers

    # This is to workaround the paramiko logging issue when SSH failed
    paramiko_logger = logging.getLogger("paramiko.transport")
    paramiko_logger.addHandler(console_handler)
    paramiko_logger.setLevel(log_level)

    console_logger = logging.getLogger(product_name + '_' + 'console')
    console_logger.addHandler(console_handler)
    console_logger.setLevel(log_level)

    file_logger = logging.getLogger(product_name + '_' + 'file')
    file_logger.setLevel(log_level)

    all_logger = logging.getLogger(product_name + '_' + 'all')
    all_logger.addHandler(console_handler)
    all_logger.setLevel(log_level)

    if file_handler:
        file_logger.addHandler(file_handler)
        paramiko_logger.addHandler(file_handler)
        all_logger.addHandler(file_handler)

def getLogger(product, target):
    logger = logging.getLogger(product + "_" + target)

    return logger

CONLOG = getLogger('vmtp', 'console')
LOG = getLogger('vmtp', 'all')
FILELOG = getLogger('vmtp', 'file')
