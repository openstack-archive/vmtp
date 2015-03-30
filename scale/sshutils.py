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
import time

import paramiko
import scp

# from rally.openstack.common.gettextutils import _


class SSHError(Exception):
    pass


class SSHTimeout(SSHError):
    pass


class SSH(object):
    """Represent ssh connection."""

    def __init__(self, user, host, port=22, pkey=None,
                 key_filename=None, password=None,
                 connect_timeout=60,
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

        self.user = user
        self.host = host
        self.port = port
        self.pkey = self._get_pkey(pkey) if pkey else None
        self.password = password
        self.key_filename = key_filename
        self._client = False
        self.connect_timeout = connect_timeout
        self.connect_retry_count = connect_retry_count
        self.connect_retry_wait_sec = connect_retry_wait_sec
        self.distro_id = None
        self.distro_id_like = None
        self.distro_version = None
        self.__get_distro()

    def _get_pkey(self, key):
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
                self._client.connect(self.host, username=self.user,
                                     port=self.port, pkey=self.pkey,
                                     key_filename=self.key_filename,
                                     password=self.password,
                                     timeout=self.connect_timeout)
                return self._client
            except (paramiko.AuthenticationException,
                    paramiko.BadHostKeyException,
                    paramiko.SSHException,
                    socket.error):
                time.sleep(self.connect_retry_wait_sec)

        self._client = None
        msg = '[%s] SSH Connection failed after %s attempts' % (self.host,
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
                args = {'cmd': cmd, 'host': self.host}
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
                raise SSHTimeout(('Timeout waiting for "%s"') % self.host)

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
            print 'Ping to %s failed: %s' % (target_ip, cmd_output)
            return 0

    def get_file_from_host(self, from_path, to_path):
        '''
        A wrapper api on top of paramiko scp module, to scp
        a local file to the host.
        '''
        sshcon = self._get_client()
        scpcon = scp.SCPClient(sshcon.get_transport())
        try:
            scpcon.get(from_path, to_path)
        except scp.SCPException as exp:
            print ("Send failed: [%s]", exp)
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


##################################################
# Only invoke the module directly for test purposes. Should be
# invoked from pns script.
##################################################
def main():
    # ssh = SSH('localadmin', '172.29.87.29', key_filename='./ssh/id_rsa')
    ssh = SSH('localadmin', '172.22.191.173', key_filename='./ssh/id_rsa')

    print 'ID=' + ssh.distro_id
    print 'ID_LIKE=' + ssh.distro_id_like
    print 'VERSION_ID=' + ssh.distro_version

    # ssh.wait()
    # print ssh.pidof('bash')
    # print ssh.stat('/tmp')

if __name__ == "__main__":
    main()
