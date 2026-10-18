/* libgtop's mount list names host paths. Query their actual filesystems,
 * not the runtime's tmpfs root or the store-backed compatibility libraries. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <mntent.h>
#include <stdio.h>
#include <string.h>
#include <sys/statvfs.h>

FILE *setmntent(const char *path, const char *mode)
{
    FILE *(*original)(const char *, const char *) = dlsym(RTLD_NEXT, "setmntent");
    if (!original) {
        errno = ENOSYS;
        return NULL;
    }
    return original(strcmp(path, "/etc/mtab") == 0 ? "/run/unity-monitor-mtab" : path, mode);
}

int statvfs(const char *path, struct statvfs *buf)
{
    int (*original)(const char *, struct statvfs *) = dlsym(RTLD_NEXT, "statvfs");
    char host_path[PATH_MAX];
    if (!original) {
        errno = ENOSYS;
        return -1;
    }
    if (path[0] != '/')
        return original(path, buf);
    if (snprintf(host_path, sizeof(host_path), "/run/unity-monitor-host%s", path)
        >= (int)sizeof(host_path)) {
        errno = ENAMETOOLONG;
        return -1;
    }
    return original(host_path, buf);
}
