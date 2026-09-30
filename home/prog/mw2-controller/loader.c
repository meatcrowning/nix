#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdint.h>

static void *remote_proc(DWORD pid, const char *name) {
    void *local = (void *)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), name);
    HMODULE owner;
    wchar_t path[MAX_PATH];
    if (!local || !GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, local, &owner) ||
            !GetModuleFileNameW(owner, path, MAX_PATH)) return NULL;
    wchar_t *base = wcsrchr(path, L'\\');
    base = base ? base + 1 : path;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid);
    MODULEENTRY32W entry = {.dwSize = sizeof(entry)};
    void *result = NULL;
    if (snap != INVALID_HANDLE_VALUE && Module32FirstW(snap, &entry)) do {
        if (!_wcsicmp(entry.szModule, base)) {
            result = entry.modBaseAddr + ((uintptr_t)local - (uintptr_t)owner);
            break;
        }
    } while (Module32NextW(snap, &entry));
    if (snap != INVALID_HANDLE_VALUE) CloseHandle(snap);
    return result;
}

static DWORD call(HANDLE process, void *fn, void *arg) {
    HANDLE thread = CreateRemoteThread(process, NULL, 0,
        (LPTHREAD_START_ROUTINE)fn, arg, 0, NULL);
    DWORD result = 0;
    if (!thread) return 0;
    // Keep remote buffers alive until the thread completes, including slow
    // Wine startup on the first launch of a prefix.
    WaitForSingleObject(thread, INFINITE);
    GetExitCodeThread(thread, &result);
    CloseHandle(thread);
    return result;
}

int wmain(void) {
    wchar_t dll[MAX_PATH], command[32768];
    if (!GetModuleFileNameW(NULL, dll, MAX_PATH)) return 1;
    wchar_t *slash = wcsrchr(dll, L'\\');
    if (!slash || slash - dll + 20 >= MAX_PATH) return 1;
    wcscpy(slash + 1, L"mw2-controller.dll");
    // Preserve Windows command-line quoting exactly while dropping argv[0].
    const wchar_t *args = GetCommandLineW();
    if (*args == L'"') { ++args; while (*args && *args != L'"') ++args; if (*args) ++args; }
    else while (*args && *args != L' ' && *args != L'\t') ++args;
    if (wcslen(args) + 20 >= 32768) return 1;
    swprintf(command, 32768, L"iw4x-sp.exe%ls", args);
    STARTUPINFOW startup = {.cb = sizeof(startup)};
    PROCESS_INFORMATION child;
    if (!CreateProcessW(L"iw4x-sp.exe", command, NULL, NULL, FALSE, 0,
                        NULL, NULL, &startup, &child)) {
        fprintf(stderr, "Controller launcher: CreateProcess failed: %lu\n", GetLastError());
        return 1;
    }
    void *load = NULL;
    for (int i = 0; i < 600 && !load; ++i) {
        if (WaitForSingleObject(child.hProcess, 50) == WAIT_OBJECT_0) break;
        load = remote_proc(child.dwProcessId, "LoadLibraryW");
    }
    SIZE_T bytes = (wcslen(dll) + 1) * sizeof(wchar_t), written;
    void *remote = VirtualAllocEx(child.hProcess, NULL, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    DWORD module = 0, initialized = 0;
    if (load && remote && WriteProcessMemory(child.hProcess, remote, dll, bytes, &written) && written == bytes)
        module = call(child.hProcess, load, remote);
    if (remote) VirtualFreeEx(child.hProcess, remote, 0, MEM_RELEASE);
    HMODULE local = LoadLibraryExW(dll, NULL, DONT_RESOLVE_DLL_REFERENCES);
    FARPROC init = local ? GetProcAddress(local, "Initialize") : NULL;
    if (module && init)
        initialized = call(child.hProcess, (void *)(module + (uintptr_t)init - (uintptr_t)local),
                           (void *)(uintptr_t)child.dwThreadId);
    if (local) FreeLibrary(local);
    if (!initialized) {
        fprintf(stderr, "Controller extension failed to initialize; see spdata/controller.log\n");
        TerminateProcess(child.hProcess, 1);
    }
    WaitForSingleObject(child.hProcess, INFINITE);
    DWORD status = 1;
    GetExitCodeProcess(child.hProcess, &status);
    CloseHandle(child.hThread);
    CloseHandle(child.hProcess);
    return (int)status;
}
