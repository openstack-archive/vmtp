========================
Caveats and Known Issues
========================

* UDP throughput is not available if iperf is selected (the iperf UDP reported results are not reliable enough for iterating)

* If VMTP hangs for native hosts throughputs, check firewall rules on the hosts to allow TCP/UDP ports 5001 and TCP port 5002

* When storing the results to JSON or MongoDB, the quotes in the command-line will not be saved. In a unix-like environment, the magic happened even before Python can see them. e.g. quotes get consumed, variables get interpolated, etc. Keep this in mind when you want to execute the command stored in "*args*", and pay more attention in any parameter that may have quotes inside like *test_description*.
