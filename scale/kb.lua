-- example reporting script which demonstrates a custom
-- done() function that prints latency percentiles as CSV

done = function(summary, latency, requests)
   io.write("__START_KLOUDBUSTER_DATA__\n")
   for _, p in pairs({ 50, 75, 90, 99, 99.9, 99.99, 99.999 }) do
      n = latency:percentile(p)
      io.write(string.format("%g,%d\n", p, n))
   end
   io.write("__END_KLOUDBUSTER_DATA__\n")
end
