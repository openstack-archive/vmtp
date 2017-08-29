# Copyright 2017 Cisco Systems, Inc.  All rights reserved.
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

from datetime import datetime
from fluent import sender
from log import LogLevel
import logging


class FluentLogHandler(logging.Handler):
    '''This is a minimalist log handler for use with Fluentd

    Needs to be attached to a logger using the addHandler method.
    It only picks up from every record:
    - the formatted message (no timestamp and no level)
    - the level name
    - the runlogdate (to tie multiple run-related logs together)
    The timestamp is retrieved by the fluentd library.
    '''

    def __init__(self, tag, fluentd_ip='127.0.0.1', fluentd_port=24224):
        logging.Handler.__init__(self)
        self.tag = tag
        self.formatter = logging.Formatter('%(message)s')
        self.sender = sender.FluentSender(self.tag, port=fluentd_port)
        self.start_new_run()

    def start_new_run(self):
        '''Delimitate a new run in the stream of records with a new timestamp
        '''
        self.runlogdate = str(datetime.now())
        LogLevel.highest_level = LogLevel.INFO

    def emit(self, record):
        data = {
            "runlogdate": self.runlogdate,
            "loglevel": record.levelname,
            "message": self.formatter.format(record)
        }
        # if new log level is higher, update the value
        if record.levelno > LogLevel.highest_level and record.levelno != LogLevel.RUN_SUMMARY:
            LogLevel.highest_level = record.levelno
        elif record.levelno == LogLevel.RUN_SUMMARY:
            data["numloglevel"] = LogLevel.highest_level
        self.sender.emit(None, data)
