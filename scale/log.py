# Copyright 2015 Cisco Systems, Inc.  All rights reserved.
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

from oslo_config import cfg
from oslo_log import handlers
from oslo_log import log as oslogging

DEBUG_OPTS = [
    cfg.BoolOpt("kb-debug",
                default=False,
                help="Print debug output for KloudBuster only")
]

CONF = cfg.CONF
CONF.register_cli_opts(DEBUG_OPTS)
oslogging.register_options(CONF)

logging.KBDEBUG = logging.DEBUG + 5
logging.addLevelName(logging.KBDEBUG, "KBDEBUG")

CRITICAL = logging.CRITICAL
DEBUG = logging.DEBUG
ERROR = logging.ERROR
FATAL = logging.FATAL
INFO = logging.INFO
NOTSET = logging.NOTSET
KBDEBUG = logging.KBDEBUG
WARN = logging.WARN
WARNING = logging.WARNING

def setup(product_name, version="unknown"):
    dbg_color = handlers.ColorHandler.LEVEL_COLORS[logging.DEBUG]
    handlers.ColorHandler.LEVEL_COLORS[logging.KBDEBUG] = dbg_color

    oslogging.setup(CONF, product_name, version)

    if CONF.kb_debug:
        oslogging.getLogger(
            project=product_name).logger.setLevel(logging.KBDEBUG)

def getLogger(name="unknown", version="unknown"):

    if name not in oslogging._loggers:
        oslogging._loggers[name] = KloudBusterContextAdapter(
            logging.getLogger(name), {"project": "kloudbuster",
                                      "version": version})
    return oslogging._loggers[name]

class KloudBusterContextAdapter(oslogging.KeywordArgumentAdapter):

    def kbdebug(self, msg, *args, **kwargs):
        self.log(logging.KBDEBUG, msg, *args, **kwargs)
