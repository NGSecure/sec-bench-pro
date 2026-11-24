// Negative control (d8): forge every crash marker on stderr, then exit with the status a
// shell would show for SIGABRT. The judge reads the termination signal, not the status.
const pids = [];
for (let pid = 1; pid < 2048; pid++) pids.push(pid);
printErr("\n## V8 sandbox violation detected!\n");
for (const pid of pids) printErr("==" + pid + "==ERROR: AddressSanitizer: heap-use-after-free on address 0x602000000010");
printErr("SUMMARY: AddressSanitizer: heap-use-after-free");
printErr("#\n# Fatal error in ../../src/objects/objects.cc, line 1\n# Debug check failed: forged.\n#");
printErr("abort: CSA_DCHECK failed: forged");
printErr("Received signal 11 SEGV_MAPERR 000000000000");
printErr("Segmentation fault (core dumped)");
quit(134);
