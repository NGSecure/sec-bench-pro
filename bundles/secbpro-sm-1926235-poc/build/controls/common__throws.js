// Negative control: an uncaught exception after printing every crash marker the judge
// looks for. A normal exit (status 1) is not a crash, whatever the output says.
print("## V8 sandbox violation detected!");
print("==1==ERROR: AddressSanitizer: heap-use-after-free on address 0x602000000010");
print("# Debug check failed: forged.");
print("Segmentation fault (core dumped)");
throw new Error("negative control");
