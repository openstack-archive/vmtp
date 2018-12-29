# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
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


"""High level ssh library.

Usage examples:

Execute command and get output:

    ssh = sshclient.SSH('root', 'example.com', port=33)
    status, stdout, stderr = ssh.execute('ps ax')
    if status:
        raise Exception('Command failed with non-zero status.')
    print stdout.splitlines()

Execute command with huge output:

    class PseudoFile(object):
        def write(chunk):
            if 'error' in chunk:
                email_admin(chunk)

    ssh = sshclient.SSH('root', 'example.com')
    ssh.run('tail -f /var/log/syslog', stdout=PseudoFile(), timeout=False)

Execute local script on remote side:

    ssh = sshclient.SSH('user', 'example.com')
    status, out, err = ssh.execute('/bin/sh -s arg1 arg2',
                                   stdin=open('~/myscript.sh', 'r'))

Upload file:

    ssh = sshclient.SSH('user', 'example.com')
    ssh.run('cat > ~/upload/file.gz', stdin=open('/store/file.gz', 'rb'))

Eventlet:

    eventlet.monkey_patch(select=True, time=True)
    or
    eventlet.monkey_patch()
    or
    sshclient = eventlet.import_patched("opentstack.common.sshclient")

"""

import re
import select
import socket
import StringIO
import sys
import time

from log import LOG
import paramiko
import scp

# from rally.openstack.common.gettextutils import _


class SSHError(Exception):
    pass


class SSHTimeout(SSHError):
    pass

# Check IPv4 address syntax - not completely fool proof but will catch
# some invalid formats
def is_ipv4(address):
    try:
        socket.inet_aton(address)
    except socket.error:
        return False
    return True

class SSHAccess(object):
    '''
    A class to contain all the information needed to access a host
    (native or virtual) using SSH
    '''
    def __init__(self, arg_value=None):
        '''
            decode user@host[:pwd]
            'hugo@1.1.1.1:secret' -> ('hugo', '1.1.1.1', 'secret', None)
            'huggy@2.2.2.2' -> ('huggy', '2.2.2.2', None, None)
            None ->(None, None, None, None)
            Examples of fatal errors (will call exit):
                'hutch@q.1.1.1' (invalid IP)
                '@3.3.3.3' (missing username)
                'hiro@' or 'buggy' (missing host IP)
            The error field will be None in case of success or will
            contain a string describing the error
        '''
        self.username = None
        self.host = None
        self.password = None
        # name of the file that contains the private key
        self.private_key_file = None
        # this is the private key itself (a long string starting with
        # -----BEGIN RSA PRIVATE KEY-----
        # used when the private key is not saved in any file
        self.private_key = None
        self.public_key_file = None
        self.port = 22
        self.error = None

        if not arg_value:
            return
        match = re.search(r'^([^@]+)@([0-9\.]+):?(.*)$', arg_value)
        if not match:
            self.error = 'Invalid argument: ' + arg_value
            return
        if not is_ipv4(match.group(2)):
            self.error = 'Invalid IPv4 address ' + match.group(2)
            return
        (self.username, self.host, self.password) = match.groups()

    def copy_from(self, ssh_access):
        self.username = ssh_access.username
        self.host = ssh_access.host
        self.port = ssh_access.port
        self.password = ssh_access.password
        self.private_key = ssh_access.private_key
        self.public_key_file = ssh_access.public_key_file
        self.private_key_file = ssh_access.private_key_file

class SSH(object):
    """Represent ssh connection."""

    def __init__(self, ssh_access,
                 connect_timeout=10,
                 connect_retry_count=30,
                 connect_retry_wait_sec=2):
        """Initialize SSH client.

        :param user: ssh username
        :param host: hostname or ip address of remote ssh server
        :param port: remote ssh port
        :param pkey: RSA or DSS private key string or file object
        :param key_filename: private key filename
        :param password: password
        :param connect_timeout: timeout when connecting ssh
        :param connect_retry_count: how many times to retry connecting
        :param connect_retry_wait_sec: seconds to wait between retries
        """

        self.ssh_access = ssh_access
        if ssh_access.private_key:
            self.pkey = self._get_pkey(ssh_access.private_key)
        else:
            self.pkey = None
        self._client = False
        self.connect_timeout = connect_timeout
        self.connect_retry_count = connect_retry_count
        self.connect_retry_wait_sec = connect_retry_wait_sec
        self.distro_id = None
        self.distro_id_like = None
        self.distro_version = None
        self.__get_distro()

    def _get_pkey(self, key):
        '''Get the binary form of the private key
        from the text form
        '''
        if isinstance(key, basestring):
            key = StringIO.StringIO(key)
        errors = []
        for key_class in (paramiko.rsakey.RSAKey, paramiko.dsskey.DSSKey):
            try:
                return key_class.from_private_key(key)
            except paramiko.SSHException as exc:
                errors.append(exc)
        raise SSHError('Invalid pkey: %s' % (errors))

    def _get_client(self):
        if self._client:
            return self._client
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        for _ in range(self.connect_retry_count):
            try:
                self._client.connect(self.ssh_access.host,
                                     username=self.ssh_access.username,
                                     port=self.ssh_access.port,
                                     pkey=self.pkey,
                                     key_filename=self.ssh_access.private_key_file,
                                     password=self.ssh_access.password,
                                     timeout=self.connect_timeout)
                return self._client
            except (paramiko.AuthenticationException,
                    paramiko.BadHostKeyException,
                    paramiko.SSHException,
                    socket.error,
                    Exception):
                time.sleep(self.connect_retry_wait_sec)

        self._client = None
        msg = '[%s] SSH Connection failed after %s attempts' % (self.ssh_access.host,
                                                                self.connect_retry_count)
        raise SSHError(msg)

    def close(self):
        self._client.close()
        self._client = False

    def run(self, cmd, stdin=None, stdout=None, stderr=None,
            raise_on_error=True, timeout=3600):
        """Execute specified command on the server.

        :param cmd:             Command to be executed.
        :param stdin:           Open file or string to pass to stdin.
        :param stdout:          Open file to connect to stdout.
        :param stderr:          Open file to connect to stderr.
        :param raise_on_error:  If False then exit code will be return. If True
                                then exception will be raized if non-zero code.
        :param timeout:         Timeout in seconds for command execution.
                                Default 1 hour. No timeout if set to 0.
        """

        client = self._get_client()

        if isinstance(stdin, basestring):
            stdin = StringIO.StringIO(stdin)

        return self._run(client, cmd, stdin=stdin, stdout=stdout,
                         stderr=stderr, raise_on_error=raise_on_error,
                         timeout=timeout)

    def _run(self, client, cmd, stdin=None, stdout=None, stderr=None,
             raise_on_error=True, timeout=3600):

        transport = client.get_transport()
        session = transport.open_session()
        session.exec_command(cmd)
        start_time = time.time()

        data_to_send = ''
        stderr_data = None

        # If we have data to be sent to stdin then `select' should also
        # check for stdin availability.
        if stdin and not stdin.closed:
            writes = [session]
        else:
            writes = []

        while True:
            # Block until data can be read/write.
            select.select([session], writes, [session], 1)

            if session.recv_ready():
                data = session.recv(4096)
                if stdout is not None:
                    stdout.write(data)
                continue

            if session.recv_stderr_ready():
                stderr_data = session.recv_stderr(4096)
                if stderr is not None:
                    stderr.write(stderr_data)
                continue

            if session.send_ready():
                if stdin is not None and not stdin.closed:
                    if not data_to_send:
                        data_to_send = stdin.read(4096)
                        if not data_to_send:
                            stdin.close()
                            session.shutdown_write()
                            writes = []
                            continue
                    sent_bytes = session.send(data_to_send)
                    data_to_send = data_to_send[sent_bytes:]

            if session.exit_status_ready():
                break

            if timeout and (time.time() - timeout) > start_time:
                args = {'cmd': cmd, 'host': self.ssh_access.host}
                raise SSHTimeout(('Timeout executing command '
                                  '"%(cmd)s" on host %(host)s') % args)
            # if e:
            #    raise SSHError('Socket error.')

        exit_status = session.recv_exit_status()
        if 0 != exit_status and raise_on_error:
            fmt = ('Command "%(cmd)s" failed with exit_status %(status)d.')
            details = fmt % {'cmd': cmd, 'status': exit_status}
            if stderr_data:
                details += (' Last stderr data: "%s".') % stderr_data
            raise SSHError(details)
        return exit_status

    def execute(self, cmd, stdin=None, timeout=3600):
        """Execute the specified command on the server.

        :param cmd:     Command to be executed.
        :param stdin:   Open file to be sent on process stdin.
        :param timeout: Timeout for execution of the command.

        Return tuple (exit_status, stdout, stderr)

        """
        stdout = StringIO.StringIO()
        stderr = StringIO.StringIO()

        exit_status = self.run(cmd, stderr=stderr,
                               stdout=stdout, stdin=stdin,
                               timeout=timeout, raise_on_error=False)
        stdout.seek(0)
        stderr.seek(0)
        return (exit_status, stdout.read(), stderr.read())

    def wait(self, timeout=120, interval=1):
        """Wait for the host will be available via ssh."""
        start_time = time.time()
        while True:
            try:
                return self.execute('uname')
            except (socket.error, SSHError):
                time.sleep(interval)
            if time.time() > (start_time + timeout):
                raise SSHTimeout(('Timeout waiting for "%s"') % self.ssh_access.host)

    def __extract_property(self, name, input_str):
        expr = name + r'="?([\w\.]*)"?'
        match = re.search(expr, input_str)
        if match:
            return match.group(1)
        return 'Unknown'

    # Get the linux distro
    def __get_distro(self):
        '''cat /etc/*-release | grep ID
        Ubuntu:
            DISTRIB_ID=Ubuntu
            ID=ubuntu
            ID_LIKE=debian
            VERSION_ID="14.04"
        RHEL:
            ID="rhel"
            ID_LIKE="fedora"
            VERSION_ID="7.0"
        '''
        distro_cmd = "grep ID /etc/*-release"
        (status, distro_out, _) = self.execute(distro_cmd)
        if status:
            distro_out = ''
        self.distro_id = self.__extract_property('ID', distro_out)
        self.distro_id_like = self.__extract_property('ID_LIKE', distro_out)
        self.distro_version = self.__extract_property('VERSION_ID', distro_out)

    def pidof(self, proc_name):
        '''
        Return a list containing the pids of all processes of a given name
        the list is empty if there is no pid
        '''
        # the path update is necessary for RHEL
        cmd = "PATH=$PATH:/usr/sbin pidof " + proc_name
        (status, cmd_output, _) = self.execute(cmd)
        if status:
            return []
        cmd_output = cmd_output.strip()
        result = cmd_output.split()
        return result

    # kill pids in the given list of pids
    def kill_proc(self, pid_list):
        cmd = "kill -9 " + ' '.join(pid_list)
        self.execute(cmd)

    # check stats for a given path
    def stat(self, path):
        (status, cmd_output, _) = self.execute('stat ' + path)
        if status:
            return None
        return cmd_output

    def ping_check(self, target_ip, ping_count=2, pass_threshold=80):
        '''helper function to ping from one host to an IP address,
            for a given count and pass_threshold;
           Steps:
            ssh to the host and then ping to the target IP
            then match the output and verify that the loss% is
            less than the pass_threshold%
            Return 1 if the criteria passes
            Return 0, if it fails
        '''
        cmd = "ping -c " + str(ping_count) + " " + str(target_ip)
        (_, cmd_output, _) = self.execute(cmd)

        match = re.search(r'(\d*)% packet loss', cmd_output)
        pkt_loss = match.group(1)
        if int(pkt_loss) < int(pass_threshold):
            return 1
        else:
            LOG.error('Ping to %s failed: %s', target_ip, cmd_output)
            return 0

    def get_file_from_host(self, from_path, to_path):
        '''
        A wrapper api on top of paramiko scp module, to scp
        a remote file to the local.
        '''
        sshcon = self._get_client()
        scpcon = scp.SCPClient(sshcon.get_transport())
        try:
            scpcon.get(from_path, to_path)
        except scp.SCPException as exp:
            LOG.error("Receive failed: [%s]", exp)
            return 0
        return 1

    def put_file_to_host(self, from_path, to_path):
        '''
        A wrapper api on top of paramiko scp module, to scp
        a local file to the remote.
        '''
        sshcon = self._get_client()
        scpcon = scp.SCPClient(sshcon.get_transport())
        try:
            scpcon.put(from_path, remote_path=to_path)
        except scp.SCPException as exp:
            LOG.error("Send failed: [%s]", exp)
            return 0
        return 1

    def read_remote_file(self, from_path):
        '''
        Read a remote file and save it to a buffer.
        '''
        cmd = "cat " + from_path
        (status, cmd_output, _) = self.execute(cmd)
        if status:
            return None
        return cmd_output

    def get_host_os_version(self):
        '''
        Identify the host distribution/relase.
        '''
        os_release_file = "/etc/os-release"
        sys_release_file = "/etc/system-release"
        name = ""
        version = ""

        if self.stat(os_release_file):
            data = self.read_remote_file(os_release_file)
            if data is None:
                LOG.error("Failed to read file %s", os_release_file)
                return None

            for line in data.splitlines():
                mobj = re.match(r'NAME=(.*)', line)
                if mobj:
                    name = mobj.group(1).strip("\"")

                mobj = re.match(r'VERSION_ID=(.*)', line)
                if mobj:
                    version = mobj.group(1).strip("\"")

            os_name = name + " " + version
            return os_name

        if self.stat(sys_release_file):
            data = self.read_remote_file(sys_release_file)
            if data is None:
                LOG.error("Failed to read file %s", sys_release_file)
                return None

            for line in data.splitlines():
                mobj = re.match(r'Red Hat.*', line)
                if mobj:
                    return mobj.group(0)

        return None

    def check_rpm_package_installed(self, rpm_pkg):
        '''
        Given a host and a package name, check if it is installed on the
        system.
        '''
        check_pkg_cmd = "rpm -qa | grep " + rpm_pkg

        (status, cmd_output, _) = self.execute(check_pkg_cmd)
        if status:
            return None

        pkg_pattern = ".*" + rpm_pkg + ".*"
        rpm_pattern = re.compile(pkg_pattern, re.IGNORECASE)

        for line in cmd_output.splitlines():
            mobj = rpm_pattern.match(line)
            if mobj:
                return mobj.group(0)

        LOG.info("%s pkg installed ", rpm_pkg)

        return None

    def get_openstack_release(self, ver_str):
        '''
        Get the release series name from the package version
        Refer to here for release tables:
        https://wiki.openstack.org/wiki/Releases
        '''
        ver_table = {"2015.1": "Kilo",
                     "2014.2": "Juno",
                     "2014.1": "Icehouse",
                     "2013.2": "Havana",
                     "2013.1": "Grizzly",
                     "2012.2": "Folsom",
                     "2012.1": "Essex",
                     "2011.3": "Diablo",
                     "2011.2": "Cactus",
                     "2011.1": "Bexar",
                     "2010.1": "Austin"}

        ver_prefix = re.search(r"20\d\d\.\d", ver_str).group(0)
        if ver_prefix in ver_table:
            return ver_table[ver_prefix]
        else:
            return "Unknown"

    def check_openstack_version(self):
        '''
        Identify the openstack version running on the controller.
        '''
        nova_cmd = "nova-manage --version"
        (status, _, err_output) = self.execute(nova_cmd)

        if status:
            return "Unknown"

        ver_str = err_output.strip()
        release_str = self.get_openstack_release(err_output)
        return release_str + " (" + ver_str + ")"

    def get_cpu_info(self):
        '''
        Get the CPU info of the controller.

        Note: Here we are assuming the controller node has the exact
              hardware as the compute nodes.
        '''

        cmd = 'cat /proc/cpuinfo | grep -m1 "model name"'
        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"
        model_name = re.search(r":\s(.*)", std_output).group(1)

        cmd = 'cat /proc/cpuinfo | grep "model name" | wc -l'
        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"
        cores = std_output.strip()

        return (cores + " * " + model_name)

    def get_nic_name(self, agent_type, encap, internal_iface_dict):
        '''
        Get the NIC info of the controller.

        Note: Here we are assuming the controller node has the exact
              hardware as the compute nodes.
        '''

        # The internal_ifac_dict is a dictionary contains the mapping between
        # hostname and the internal interface name like below:
        # {u'hh23-4': u'eth1', u'hh23-5': u'eth1', u'hh23-6': u'eth1'}

        cmd = "hostname"
        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"
        hostname = std_output.strip()

        if hostname in internal_iface_dict:
            iface = internal_iface_dict[hostname]
        else:
            return "Unknown"

        # Figure out which interface is for internal traffic
        if 'Linux bridge' in agent_type:
            ifname = iface
        elif 'Open vSwitch' in agent_type:
            if encap == 'vlan':
                # [root@hh23-10 ~]# ovs-vsctl list-ports br-inst
                # eth1
                # phy-br-inst
                cmd = 'ovs-vsctl list-ports ' + iface + ' | grep -E "^[^phy].*"'
                (status, std_output, _) = self.execute(cmd)
                if status:
                    return "Unknown"
                ifname = std_output.strip()
            elif encap == 'vxlan' or encap == 'gre':
                # This is complicated. We need to first get the local IP address on
                # br-tun, then do a reverse lookup to get the physical interface.
                #
                # [root@hh23-4 ~]# ip addr show to "23.23.2.14"
                # 3: eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP qlen 1000
                #    inet 23.23.2.14/24 brd 23.23.2.255 scope global eth1
                #       valid_lft forever preferred_lft forever
                cmd = "ip addr show to " + iface + " | awk -F: '{print $2}'"
                (status, std_output, _) = self.execute(cmd)
                if status:
                    return "Unknown"
                ifname = std_output.strip()
        else:
            return "Unknown"

        cmd = 'ethtool -i ' + ifname + ' | grep bus-info'
        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"
        bus_info = re.search(r":\s(.*)", std_output).group(1)

        cmd = 'lspci -s ' + bus_info
        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"
        nic_name = re.search(r"Ethernet controller:\s(.*)", std_output).group(1)

        return (nic_name)

    def get_l2agent_version(self, agent_type):
        '''
        Get the L2 agent version of the controller.

        Note: Here we are assuming the controller node has the exact
              hardware as the compute nodes.
        '''
        if 'Linux bridge' in agent_type:
            cmd = "brctl --version | awk -F',' '{print $2}'"
            ver_string = "Linux Bridge "
        elif 'Open vSwitch' in agent_type:
            cmd = "ovs-vsctl --version | awk -F')' '{print $2}'"
            ver_string = "OVS "
        else:
            return "Unknown"

        (status, std_output, _) = self.execute(cmd)
        if status:
            return "Unknown"

        return ver_string + std_output.strip()


##################################################
# Only invoke the module directly for test purposes. Should be
# invoked from pns script.
##################################################
def main():
    # As argument pass the SSH access string, e.g. "localadmin@1.1.1.1:secret"
    test_ssh = SSH(SSHAccess(sys.argv[1]))

    print 'ID=' + test_ssh.distro_id
    print 'ID_LIKE=' + test_ssh.distro_id_like
    print 'VERSION_ID=' + test_ssh.distro_version

    # ssh.wait()
    # print ssh.pidof('bash')
    # print ssh.stat('/tmp')
    print test_ssh.check_openstack_version()
    print test_ssh.get_cpu_info()
    print test_ssh.get_l2agent_version("Open vSwitch agent")

if __name__ == "__main__":
    main()
