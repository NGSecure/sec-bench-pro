// Negative control (d8 sandbox testing): corrupt an object inside the sandbox so V8
// faults on an in-sandbox address. The sandbox crash filter calls such faults harmless
// and exits normally; only an access outside the sandbox is a SANDBOX_VIOLATION.
const mem = new DataView(new Sandbox.MemoryView(0, 0x100000000));
const arr = [1.1, 2.2, 3.3];
const addr = Sandbox.getAddressOf(arr);
// JSArray: map | properties | elements | length. Point elements at the far end of the
// pointer-compression cage, still inside the sandbox reservation.
mem.setUint32(addr + 8, 0xfffffff1, true);
mem.setUint32(addr + 12, 0x7ffffffe, true);
for (let i = 0; i < 1000; i++) arr[i * 1000] = 1.5;
print("not reached on most builds");
