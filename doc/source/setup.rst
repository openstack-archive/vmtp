=====
Setup
=====


SSH Authentication
------------------

VMTP can optionally SSH to the following hosts:
- OpenStack controller node (if the --controller-node option is used)
- External host for cloud upload/download performance test (if the --external-host option is used)
- Native host throughput (if the --host option is used)

To connect to these hosts, the SSH library used by VMTP will try a number of authentication methods:
- if provided at the command line, try the provided password (e.g. --controller-node localadmin@10.1.1.78:secret)
- user's personal private key (~/.ssh/id_rsa)
- if provided in the configuration file, a specific private key file (private_key_file variable)

SSH to the test VMs is always based on key pairs with the following precedence:
- if provided in the passed configuration file, use the configured key pair (private_key_file and public_key_file variables),
- otherwise use the user's personal key pair (~/.ssh/id_rsa and ~/.ssh/id_rsa.pub)
- otherwise if there is no personal key pair configured, create a temporary key pair to access all test VMs

To summarize:
- if you have a personal key pair configured in your home directory, VMTP will use that key pair for all SSH connections (including to the test VMs)
- if you want to use your personal key pair, there is nothing to do other than making sure that the targeted hosts have been configured with the associated public key

In any case make sure you specify the correct username.
If there is a problem, you should see an error message and stack trace after the SSH library times out.
