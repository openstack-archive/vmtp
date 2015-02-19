========================
Caveats and Known Issues
========================

* UDP throughput is not available if iperf is selected (the iperf UDP reported results are not reliable enough for iterating)

* If VMTP hangs for native hosts throughputs, check firewall rules on the hosts to allow TCP/UDP ports 5001 and TCP port 5002
