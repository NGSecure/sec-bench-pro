#!/usr/bin/env python3
"""Drop privileges, confine, then exec the JS engine (one PoC run).

    python3 -I -S sandbox_exec.py <status_fd> <uid> <disable_aslr 0|1> -- <argv...>

task_server.py starts this wrapper as a fresh single-threaded process (no
preexec_fn in the multi-threaded server), so everything below runs before the
engine's first instruction and survives execve: the engine keeps this PID, which
is the PID ASan prints in its report header.

1. oom_score_adj = 1000, so a memory blow-up kills the engine, not the server;
2. optional personality(ADDR_NO_RANDOMIZE) for the one upstream instance that
   was recorded with ASLR off (meta.json disable_aslr);
3. become <uid>:<uid> with no supplementary groups (a fresh uid per run),
   keeping only CAP_DAC_OVERRIDE, and only until execve. The engine binary is
   execute-only (mode 0711), so a PoC cannot read it (d8 readbuffer() and the
   SpiderMonkey shell's os.file.readFile() read any file the process may open)
   to tell the two builds apart. But the kernel makes a process that executes
   an unreadable file non-dumpable, which turns /proc/self/environ root-owned,
   and ASan reads ASAN_OPTIONS from nowhere else: the engine would run with
   ASan's defaults (exit status 1 instead of SIGABRT on a report). Holding
   CAP_DAC_OVERRIDE across the setuid makes the file readable to execve's
   dumpability check; execve itself then drops every capability (a non-root
   uid, no file capabilities, empty inheritable and ambient sets), so the
   engine runs dumpable, with no capabilities, unable to open its own binary;
4. rlimits: no core files, 256 MiB per written file;
5. PR_SET_NO_NEW_PRIVS + a seccomp filter (x86-64 only):
   * no new processes: fork/vfork fail, clone only with CLONE_THREAD,
     clone3 -> ENOSYS (glibc then falls back to clone for threads);
   * no synthetic crash signals: kill/tkill/rt_sigqueueinfo may not send
     SIGSEGV/SIGBUS/SIGILL/SIGFPE/SIGTRAP/SIGSYS/SIGABRT, tgkill and
     rt_tgsigqueueinfo may not send the first six. abort() still works (glibc
     raise() is tgkill(SIGABRT)), so a genuine assertion or an ASan abort ends
     the process exactly as upstream, but a script cannot fake a fault signal;
   * no tracing or cross-process memory access, no namespaces or mounts, no
     SysV/POSIX message IPC, io_uring, bpf, perf, userfaultfd or keyrings;
   * sockets: AF_UNIX only.
   Every denial returns an errno; the filter never kills.

If any step fails, the reason is written to <status_fd> and the wrapper exits
125 without running the engine. The fd is close-on-exec, so the server reads EOF
with no data exactly when execve succeeded.
"""

import ctypes
import errno
import os
import resource
import struct
import sys

FSIZE_LIMIT = 256 << 20

# x86-64 syscall numbers
NR = dict(clone=56, fork=57, vfork=58, execveat=322, clone3=435, socket=41,
          kill=62, tkill=200, tgkill=234, rt_sigqueueinfo=129, rt_tgsigqueueinfo=297,
          pidfd_send_signal=424, pidfd_open=434, pidfd_getfd=438,
          ptrace=101, process_vm_readv=310, process_vm_writev=311, kcmp=312,
          perf_event_open=298, bpf=321, userfaultfd=323,
          unshare=272, setns=308, mount=165, umount2=166, pivot_root=155, chroot=161,
          keyctl=250, add_key=248, request_key=249,
          shmget=29, semget=64, msgget=68, mq_open=240,
          io_uring_setup=425, io_uring_enter=426, io_uring_register=427)
DENY_ALL = ("fork", "vfork", "execveat", "pidfd_send_signal", "pidfd_open", "pidfd_getfd",
            "ptrace", "process_vm_readv", "process_vm_writev", "kcmp", "perf_event_open", "bpf",
            "userfaultfd", "unshare", "setns", "mount", "umount2", "pivot_root", "chroot",
            "keyctl", "add_key", "request_key", "shmget", "semget", "msgget", "mq_open",
            "io_uring_setup", "io_uring_enter", "io_uring_register")
FAULT_SIGNALS = (4, 5, 7, 8, 11, 31)   # SIGILL SIGTRAP SIGBUS SIGFPE SIGSEGV SIGSYS
SIGABRT = 6
CLONE_THREAD = 0x00010000
AF_UNIX = 1
CAP_DAC_OVERRIDE = 1
PR_SET_KEEPCAPS, PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL = 8, 47, 4
PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP, SECCOMP_MODE_FILTER = 38, 22, 2


def seccomp_program():
    """Classic BPF with symbolic labels, assembled to struct sock_filter[]."""
    LD, JEQ, JGE, JSET, RET = 0x20, 0x15, 0x35, 0x45, 0x06
    ALLOW, KILL = 0x7FFF0000, 0x80000000                       # RET_ALLOW, RET_KILL_PROCESS
    EPERM, ENOSYS = 0x00050000 | errno.EPERM, 0x00050000 | errno.ENOSYS
    arg = lambda i: 16 + 8 * i                                 # low 32 bits of args[i]
    prog = []                                                  # (code, jt, jf, k)

    def op(code, k, jt=0, jf=0):
        prog.append([code, jt, jf, k])

    op(LD, 4)                                                  # arch
    op(JEQ, 0xC000003E, 1, 0)
    op(RET, KILL)
    op(LD, 0)                                                  # syscall nr
    op(JGE, 0x40000000, "eperm", 0)                            # x32 ABI
    for name in DENY_ALL:
        op(JEQ, NR[name], "eperm", 0)
    op(JEQ, NR["clone3"], "enosys", 0)
    op(JEQ, NR["clone"], "clone", 0)
    op(JEQ, NR["socket"], "socket", 0)
    for name in ("kill", "tkill", "rt_sigqueueinfo"):
        op(JEQ, NR[name], "sig_arg1_strict", 0)
    op(JEQ, NR["tgkill"], "sig_arg2", 0)
    op(JEQ, NR["rt_tgsigqueueinfo"], "sig_arg2", 0)
    op(RET, ALLOW)
    labels = {}

    def label(name):
        labels[name] = len(prog)

    label("clone")
    op(LD, arg(0))
    op(JSET, CLONE_THREAD, "allow", "eperm")
    label("socket")
    op(LD, arg(0))
    op(JEQ, AF_UNIX, "allow", "eperm")
    label("sig_arg1_strict")
    op(LD, arg(1))
    for s in FAULT_SIGNALS + (SIGABRT,):
        op(JEQ, s, "eperm", 0)
    op(RET, ALLOW)
    label("sig_arg2")
    op(LD, arg(2))
    for s in FAULT_SIGNALS:
        op(JEQ, s, "eperm", 0)
    op(RET, ALLOW)
    label("allow")
    op(RET, ALLOW)
    label("eperm")
    op(RET, EPERM)
    label("enosys")
    op(RET, ENOSYS)

    out = []
    for i, (code, jt, jf, k) in enumerate(prog):
        if isinstance(jt, str):
            jt = labels[jt] - i - 1
        if isinstance(jf, str):
            jf = labels[jf] - i - 1
        if not (0 <= jt <= 255 and 0 <= jf <= 255):
            raise ValueError("BPF jump out of range at %d" % i)
        out.append(struct.pack("HBBI", code, jt, jf, k))
    return b"".join(out), len(out)


class SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


class CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class CapData(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                ("inheritable", ctypes.c_uint32)]


def _prctl(libc, option, arg2=0, arg3=0):
    ul = ctypes.c_ulong
    return libc.prctl(ctypes.c_int(option), ul(arg2), ul(arg3), ul(0), ul(0))


def keep_only_dac_override_until_exec(libc):
    """Effective = permitted = {CAP_DAC_OVERRIDE}, inheritable = ambient = {}."""
    data = (CapData * 2)()
    data[0].effective = data[0].permitted = 1 << CAP_DAC_OVERRIDE
    if libc.capset(ctypes.byref(CapHeader(0x20080522, 0)), data):   # _LINUX_CAPABILITY_VERSION_3
        raise OSError(ctypes.get_errno(), "capset")
    _prctl(libc, PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL)          # empty already; old kernels: EINVAL


def install_seccomp(libc):
    code, n = seccomp_program()
    buf = ctypes.create_string_buffer(code, len(code))
    fprog = SockFprog(n, ctypes.cast(buf, ctypes.c_void_p))
    if _prctl(libc, PR_SET_NO_NEW_PRIVS, 1):
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS")
    if _prctl(libc, PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ctypes.addressof(fprog)):
        raise OSError(ctypes.get_errno(), "PR_SET_SECCOMP")


def confine(uid, disable_aslr):
    libc = ctypes.CDLL(None, use_errno=True)
    with open("/proc/self/oom_score_adj", "w") as f:
        f.write("1000")
    if disable_aslr:
        # Docker's default seccomp profile may refuse this flag; the caller records it.
        if libc.personality(ctypes.c_ulong(0x0040000)) == -1:
            sys.stderr.write("[secb] note: personality(ADDR_NO_RANDOMIZE) refused; ASLR stays on\n")
    if _prctl(libc, PR_SET_KEEPCAPS, 1):                    # keep permitted caps across setuid
        raise OSError(ctypes.get_errno(), "PR_SET_KEEPCAPS")
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    if os.getuid() != uid or os.geteuid() != uid:
        raise OSError(errno.EPERM, "setuid did not take effect")
    keep_only_dac_override_until_exec(libc)
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FSIZE_LIMIT, FSIZE_LIMIT))
    install_seccomp(libc)


def main():
    status_fd, uid, aslr = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3] == "1"
    if sys.argv[4] != "--" or len(sys.argv) < 6:
        os.write(status_fd, b"usage error")
        os._exit(125)
    argv = sys.argv[5:]
    os.set_inheritable(status_fd, False)          # closed by a successful execve
    try:
        confine(uid, aslr)
        os.execve(argv[0], argv, os.environ)
    except BaseException as exc:                  # never run the engine half-confined
        try:
            os.write(status_fd, ("%s: %s" % (type(exc).__name__, exc)).encode()[:2000])
        finally:
            os._exit(125)


if __name__ == "__main__":
    main()
