=====
Setup
=====

Public Cloud
------------

Public clouds are special because they may not expose all OpenStack APIs and may not allow all types of operations. Some public clouds have limitations in the way virtual networks can be used or require the use of a specific external router. Running VMTP against a public cloud will require a specific configuration file that takes into account those specificities.

Refer to the provided public cloud sample configuration files for more information.

SSH Password-less Access
------------------------

For host throughput (*--host*), VMTP expects the target hosts to be pre-provisioned with a public key in order to allow password-less SSH.

Test VMs are created through OpenStack by VMTP with the appropriate public key to allow password-less ssh. By default, VMTP uses a default VMTP public key located in ssh/id_rsa.pub, simply append the content of that file into the .ssh/authorized_keys file under the host login home directory).

**Note:** This default VMTP public key should only be used for transient test VMs and **MUST NOT** be used to provision native hosts since the corresponding private key is open to anybody! To use alternate key pairs, the 'private_key_file' variable in the configuration file must be overridden to point to the file containing the private key to use to connect with SSH.
