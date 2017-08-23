# -*- coding: utf-8 -*-

# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
test_vmtp
----------------------------------

Tests for `vmtp` module.
"""

import logging
from vmtp.fluentd import FluentLogHandler
import vmtp.log


def setup_module(module):
    vmtp.log.setup(product_name="test")


def test_fluentd():
    logger = logging.getLogger('fluent-logger')
    handler = FluentLogHandler('vmtp', fluentd_port=7081)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info('test')
    logger.warning('test %d', 100)
    try:
        raise Exception("test")
    except Exception:
        logger.exception("got exception")
