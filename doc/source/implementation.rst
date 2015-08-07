==============
Implementation
==============

TCP Throughput Measurement
--------------------------

The TCP throughput reported is measured using the default message size of the test tool (64KB with nuttcp). The TCP MSS (maximum segment size) used is the one suggested by the TCP-IP stack (which is dependent on the MTU).


UDP Throughput Measurement
--------------------------
UDP throughput is tricky because of limitations of the performance tools used, limitations of the Linux kernel used and criteria for finding the throughput to report.

The default setting is to find the "optimal" throughput with packet loss rate within the 2%~5% range. This is achieved by successive iterations at different throughput values.

In some cases, it is not possible to converge with a loss rate within that range and trying to do so may require too many iterations. The algorithm used is empiric and tries to achieve a result within a reasonable and bounded number of iterations. In most cases the optimal throughput is found in less than 30 seconds for any given flow.

.. note:: UDP measurements are only available with nuttcp (not available with iperf).
