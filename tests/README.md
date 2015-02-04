
# VMTP testsuite: 

# How to run
#examples:

# 1. Run all tests in module.
python -m unittest pns_tests

# 2. Run specific class of tests:
# python -m unittest pns_tests.<class name>
# example:
# python -m unittest pns_tests.MongoTests

# 3. Run a specific test case:
# python -m unittest pns_tests.<class>.<func>
# example:
# python -m unittest pns_test.MongoTests.test_connect_to_mongo
