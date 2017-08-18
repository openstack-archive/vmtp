#!/usr/bin/env python

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

import pymongo

def connect_to_mongod(mongod_ip, mongod_port):
    '''
    Create a connection to the mongo deamon.
    '''
    if mongod_ip is None:
        mongod_ip = "localhost"

    if mongod_port is None:
        mongod_port = 27017

    client = None

    try:
        client = pymongo.MongoClient(mongod_ip, mongod_port)
    except pymongo.errors.ConnectionFailure:
        print "ERROR: pymongo. Connection Failure (%s) (%d)" % \
            (mongod_ip, mongod_port)
        return None

    return client


def get_mongod_collection(db_client, database_name, collection_name):
    '''
    Given db name and collection name, get the collection object.
    '''
    mongo_db = db_client[database_name]
    if mongo_db is None:
        print "Invalid database name"
        return None

    collection = mongo_db[collection_name]
    if collection is None:
        return None

    return collection


def is_type_dict(var):
    if isinstance(var, dict):
        return True
    return False


def add_new_document_to_collection(collection, document):
    if collection is None:
        print "collection cannot be none"
        return None

    if not is_type_dict(document):
        print "Document type should be a dictionary"
        return None

    post_id = collection.insert(document)

    return post_id


def search_documents_in_collection(collection, pattern):
    if collection is None:
        print "collection cannot be None"
        return None

    if pattern is None:
        pattern = {}

    if not is_type_dict(pattern):
        print "pattern type should be a dictionary"
        return None

    try:
        output = collection.find(pattern)
    except TypeError:
        print "A TypeError occurred. Invalid pattern: ", pattern
        return None

    return output


def pns_add_test_result_to_mongod(mongod_ip,
                                  mongod_port, pns_database,
                                  pns_collection, document):
    '''
    Invoked from vmtp to add a new result to the mongod database.
    '''
    client = connect_to_mongod(mongod_ip, mongod_port)
    if client is None:
        print "ERROR: Failed to connect to mongod (%s) (%d)" % \
              (mongod_ip, mongod_port)
        return None

    collection = get_mongod_collection(client, pns_database, pns_collection)
    if collection is None:
        print "ERROR: Failed to get collection DB: %s, %s" % \
              (pns_database, pns_collection)
        return None

    post_id = add_new_document_to_collection(collection, document)

    return post_id


def pns_search_results_from_mongod(mongod_ip, mongod_port,
                                   pns_database, pns_collection,
                                   pattern):
    '''
    Can be invoked from a helper script to query the mongod database
    '''
    client = connect_to_mongod(mongod_ip, mongod_port)
    if client is None:
        print "ERROR: Failed to connect to mongod (%s) (%d)" % \
              (mongod_ip, mongod_port)
        return

    collection = get_mongod_collection(client, pns_database, pns_collection)
    if collection is None:
        print "ERROR: Failed to get collection DB: %s, %s" % \
              (pns_database, pns_collection)
        return

    docs = search_documents_in_collection(collection, pattern)

    return docs
