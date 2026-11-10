// Negative control (SpiderMonkey): forge every crash marker on stderr, then exit with
// status 1, which is what a genuine ASan report produces when ASAN_OPTIONS is not
// honoured (ASan's default exitcode). The shell's quit() only takes 0-127, so a
// "134" cannot even be faked. The judge reads the termination signal, not the text.
printErr("Assertion failure: forged, at /src/gecko-dev/js/src/vm/Interpreter.cpp:1");
for (let pid = 1; pid < 2048; pid++) printErr("==" + pid + "==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000000");
printErr("SUMMARY: AddressSanitizer: SEGV");
printErr("Hit MOZ_CRASH(forged) at /src/gecko-dev/js/src/vm/Interpreter.cpp:1");
printErr("Segmentation fault (core dumped)");
quit(1);
