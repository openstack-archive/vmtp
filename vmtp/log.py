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
    # Add RUN_SUMMARY as a custom log level to log highest level of log
    # along with the number of errors and warnings in the run
    logging.addLevelName(RunStatus.RUN_SUMMARY_LOG_LEVEL, "RUN_SUMMARY")

    def run_summary(self, message, *args, **kws):
        self._log(RunStatus.RUN_SUMMARY_LOG_LEVEL, message, args, **kws)

    logging.Logger.run_summary = run_summary

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
        all_logger.addHandler(file_handler)


def getLogger(product, target):
    logger = logging.getLogger(product + "_" + target)
    return logger


CONLOG = getLogger('vmtp', 'console')
LOG = getLogger('vmtp', 'all')
FILELOG = getLogger('vmtp', 'file')


class RunStatus(object):
    RUN_SUMMARY_LOG_LEVEL = 100
    warning_counter = 0
    error_counter = 0

    @staticmethod
    def get_highest_level_desc():
        highest_level = RunStatus.get_warning_count()
        if highest_level == logging.INFO:
            return "GOOD RUN"
        elif highest_level == logging.WARNING:
            return "RUN WITH WARNINGS"
        else:
            return "RUN WITH ERRORS"

    @staticmethod
    def reset():
        RunStatus.warning_counter = 0
        RunStatus.error_counter = 0

    @staticmethod
    def get_warning_count():
        return RunStatus.warning_counter

    @staticmethod
    def get_error_count():
        return RunStatus.error_counter

    @staticmethod
    def get_highest_level():
        if RunStatus.get_error_count() > 0:
            return logging.ERROR
        elif RunStatus.get_warning_count() > 0:
            return logging.WARNING
        return logging.INFO
