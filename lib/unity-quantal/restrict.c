/* Applied after bubblewrap creates namespaces, inherited by every app child. */
#include <errno.h>
#include <linux/sockios.h>
#include <seccomp.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    if (!ctx) return 1;
    const char *denied[] = {
        "mount", "umount2", "pivot_root", "chroot", "unshare", "setns",
        "ptrace", "process_vm_readv", "process_vm_writev", "bpf",
        "perf_event_open", "userfaultfd", "keyctl", "add_key", "request_key",
        "kexec_load", "kexec_file_load", "init_module", "finit_module",
        "delete_module", "reboot", "swapon", "swapoff", "acct",
        "open_by_handle_at", "name_to_handle_at", "io_uring_setup",
    };
    int error = 0;
    for (unsigned i = 0; i < sizeof(denied) / sizeof(denied[0]); i++) {
        int nr = seccomp_syscall_resolve_name(denied[i]);
        if (nr != __NR_SCMP_ERROR)
            error |= seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), nr, 0);
    }
    error |= seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(socket), 1,
                              SCMP_A0(SCMP_CMP_NE, AF_UNIX));
    error |= seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(ioctl), 1,
                              SCMP_A1(SCMP_CMP_EQ, TIOCSTI));
    error |= seccomp_rule_add(ctx, SCMP_ACT_ERRNO(EPERM), SCMP_SYS(ioctl), 1,
                              SCMP_A1(SCMP_CMP_EQ, TIOCLINUX));
    if (error || seccomp_load(ctx)) {
        fputs("Cannot apply application syscall restrictions\n", stderr);
        seccomp_release(ctx);
        return 1;
    }
    seccomp_release(ctx);
    execvp(argv[1], argv + 1);
    perror("execvp");
    return 1;
}
