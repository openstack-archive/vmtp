# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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
#

import sys
import unittest

sys.path.append("..")
import pns_mongo
import sshutils


class MongoTests(unittest.TestCase):
    def test_connect_to_mongo_valid(self):
        print "test connect to mongo"
        mongod_ip = "172.29.87.29"
        mongod_port = 27017
        client = pns_mongo.connect_to_mongod(mongod_ip, mongod_port)
        print "client: ", client
        self.failUnless(client is not None)

    def test_connect_to_mongo_invalid(self):
        mongod_ip = "172.22.191.173"
        mongod_port = 27017
        client = pns_mongo.connect_to_mongod(mongod_ip, mongod_port)
        self.failUnless(client is None)

    def test_get_mongod_collection(self):
        mongod_ip = "172.29.87.29"
        mongod_port = 27017
        client = pns_mongo.connect_to_mongod(mongod_ip, mongod_port)
        self.failUnless(client is not None)
        collection = pns_mongo.get_mongod_collection(client,
                                                     "test", "testdata")
        self.failUnless(collection is not None)

    def test_get_mondog_collection_invalid_db(self):
        mongod_ip = "172.29.87.29"
        mongod_port = 27017
        client = pns_mongo.connect_to_mongod(mongod_ip, mongod_port)
        self.failUnless(client is not None)

        collection = pns_mongo.get_mongod_collection(client, "test1",
                                                     "testdata")
        self.failUnless(collection is not None)

    def test_search_documents_in_collection(self):
        mongod_ip = "172.29.87.29"
        mongod_port = 27017

        client = pns_mongo.connect_to_mongod(mongod_ip, mongod_port)
        self.failUnless(client is not None)

        collection = pns_mongo.get_mongod_collection(client,
                                                     "test",
                                                     "testdata")
        self.failUnless(collection is not None)

        docs = pns_mongo.search_documents_in_collection(collection, None)
        for doc in docs:
            print doc

    def test_pns_add_test_result_to_mongod(self):
        mongod_ip = "172.29.87.29"
        mongod_port = 27017
        pns_db = "dummy_db"
        pns_collection = "dummy_collection"
        doc = {}
        doc['name'] = "Behzad"
        doc['id'] = 909

        post_id = pns_mongo.\
            pns_add_test_result_to_mongod(mongod_ip, mongod_port,
                                          pns_db, pns_collection,
                                          doc)
        print"post id: ", post_id





class SSHTests(unittest.TestCase):
    def test_get_host_os_version(self):
        host = "172.22.191.173"
        user = "root"
        password = "cisco123"
        sshcon = sshutils.SSH(user, host, password=password)
        self.failUnless(sshcon is not None)

        data = sshcon.get_host_os_version()
        print "data: ", data

    def test_check_rpm_package_installed(self):
        host = "172.22.191.173"
        user = "root"
        password = "cisco123"
        sshcon = sshutils.SSH(user, host, password=password)
        self.failUnless(sshcon is not None)

        val = sshcon.check_rpm_package_installed("openstack-nova-scheduler")
        self.failUnless(val is not None)
        print "Installed: ", val

    def test_check_openstack_version(self):
        host = "172.22.191.173"
        user = "root"
        password = "cisco123"
        sshcon = sshutils.SSH(user, host, password=password)
        self.failUnless(sshcon is not None)

        os_version = sshcon.check_openstack_version()
        self.failUnless(os_version is not None)
        print "openstack version: ", os_version
