#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <xinput.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "pad.h"
#include "prompts.h"

// IW4 SP159, loaded by the pinned AlterWare iw4x-sp executable. Addresses are
// checked before patching; the launcher additionally verifies both PE hashes.
#ifndef ENGINE
#define ENGINE(type, address) ((type)(uintptr_t)(address))
#endif
#ifndef GAME_MEMORY
#define GAME_MEMORY(address) ((void *)(uintptr_t)(address))
#endif
typedef void (__cdecl *Frame)(void);
typedef void (__cdecl *Command)(int, const char *);
typedef void (__cdecl *KeyEvent)(int, int, int, unsigned);
typedef unsigned char *(__cdecl *FindDvar)(const char *);
typedef unsigned char *(__cdecl *FloatDvar)(const char *, float, float, float, unsigned short, const char *);
typedef unsigned char *(__cdecl *BoolDvar)(const char *, unsigned char, unsigned short, const char *);
static Frame original_frame;
void *original_mouse = (void *)0x57AFF0;
static unsigned char *enabled, *deadzone, *outer, *sensitivity, *invert, *assist, *lockon;
static unsigned char *yaw_rate, *pitch_rate, *yaw_ads, *pitch_ads;
static XINPUT_GAMEPAD pad;
static int playing, ready;
static unsigned held, previous;
static int menu_key;
static DWORD repeat_at;
static int controller_active;
typedef void (__cdecl *Directive)(int, const char *, char *, int);
static Directive original_directive;
typedef struct {
    float velocity[3];
    int eflags, linkflags, pmflags, weapon_flags, weapon_state;
    float weapon_fraction;
    int weapon;
    unsigned char has_ammo, dual, third_person, extended_melee;
    char padding[4];
    float screen_matrix[16], inverse_matrix[16];
    unsigned char initialized;
    char alignment[3];
    int previous_buttons;
    float regions[8], eye[3], origin[3], angles[3], axis[3][3];
    float fov_rate, fov_inverse, ads, pitch_delta, yaw_delta, width, height;
    AimTarget targets[64];
    int count;
} AimGlobals;
_Static_assert(offsetof(AimGlobals, initialized) == 0xB0, "SP159 aim initialization");
_Static_assert(offsetof(AimGlobals, axis) == 0xFC, "SP159 view basis");
_Static_assert(offsetof(AimGlobals, targets) == 0x13C, "SP159 target list");
_Static_assert(offsetof(AimGlobals, count) == 0xE3C, "SP159 target count");

static void __cdecl directive_stub(int client, const char *src, char *dst, int size) {
    char text[8192];
    if (!src || !dst || size <= 0) return;
    if (controller_active && replace_prompts(src, text, sizeof(text))) src = text;
    original_directive(client, src, dst, size);
}

static void log_line(const char *line) {
    FILE *f = fopen("spdata/controller.log", "a");
    if (f) { fprintf(f, "%s\n", line); fclose(f); }
}
static float value(unsigned char *dvar) { float f; memcpy(&f, dvar + 16, 4); return f; }
static void command(const char *text) { ENGINE(Command, 0x4A1090)(0, text); }
static void key(int code, int down) { ENGINE(KeyEvent, 0x442D60)(0, code, down, ENGINE(unsigned (__cdecl *)(void), 0x44E130)()); }

enum { LT = 1u << 16, RT = 1u << 17 };
static const struct Binding { unsigned mask; const char *press, *release; } bindings[] = {
    {XINPUT_GAMEPAD_A, "+gostand\n", "-gostand\n"},
    {XINPUT_GAMEPAD_B, "+stance\n", "-stance\n"},
    {XINPUT_GAMEPAD_X, "+usereload\n", "-usereload\n"},
    {XINPUT_GAMEPAD_Y, "weapnext\n", NULL},
    {XINPUT_GAMEPAD_LEFT_SHOULDER, "+smoke\n", "-smoke\n"},
    {XINPUT_GAMEPAD_RIGHT_SHOULDER, "+frag\n", "-frag\n"},
    {XINPUT_GAMEPAD_LEFT_THUMB, "+breath_sprint\n", "-breath_sprint\n"},
    {XINPUT_GAMEPAD_RIGHT_THUMB, "+melee\n", "-melee\n"},
    {XINPUT_GAMEPAD_BACK, "+scores\n", "-scores\n"},
    {LT, "+speed_throw\n", "-speed_throw\n"},
    {RT, "+attack\n", "-attack\n"},
    {XINPUT_GAMEPAD_DPAD_UP, "+actionslot 1\n", "-actionslot 1\n"},
    {XINPUT_GAMEPAD_DPAD_DOWN, "+actionslot 2\n", "-actionslot 2\n"},
    {XINPUT_GAMEPAD_DPAD_LEFT, "+actionslot 3\n", "-actionslot 3\n"},
    {XINPUT_GAMEPAD_DPAD_RIGHT, "+actionslot 4\n", "-actionslot 4\n"},
};
static void release_all(void) {
    for (unsigned i = 0; i < sizeof(bindings) / sizeof(*bindings); ++i)
        if ((held & bindings[i].mask) && bindings[i].release) command(bindings[i].release);
    held = 0;
    if (menu_key) key(menu_key, 0);
    menu_key = 0;
    memset(&pad, 0, sizeof(pad));
}

static void process_pad(const XINPUT_GAMEPAD *sample, int connected, int gameplay) {
    controller_active = connected;
    if (!connected) { release_all(); previous = 0; playing = 0; return; }
    unsigned buttons = sample->wButtons |
        (sample->bLeftTrigger > XINPUT_GAMEPAD_TRIGGER_THRESHOLD ? LT : 0) |
        (sample->bRightTrigger > XINPUT_GAMEPAD_TRIGGER_THRESHOLD ? RT : 0);
    if (playing != gameplay) { release_all(); previous = buttons; }
    playing = gameplay;
    pad = *sample;
    unsigned pressed = buttons & ~previous;
    if (pressed & XINPUT_GAMEPAD_START) { key(27, 1); key(27, 0); }
    if (playing) {
        for (unsigned i = 0; i < sizeof(bindings) / sizeof(*bindings); ++i) {
            const struct Binding *b = &bindings[i];
            if (pressed & b->mask) { command(b->press); held |= b->mask; }
            if ((held & b->mask) && !(buttons & b->mask)) {
                if (b->release) command(b->release);
                held &= ~b->mask;
            }
        }
    } else {
        if (pressed & XINPUT_GAMEPAD_A) { key(13, 1); key(13, 0); }
        if (pressed & XINPUT_GAMEPAD_B) { key(27, 1); key(27, 0); }
        Stick s = stick(pad.sThumbLX, pad.sThumbLY, value(deadzone), value(outer));
        int next = (buttons & XINPUT_GAMEPAD_DPAD_UP) || s.y > .5f ? 154 :
                   (buttons & XINPUT_GAMEPAD_DPAD_DOWN) || s.y < -.5f ? 155 :
                   (buttons & XINPUT_GAMEPAD_DPAD_LEFT) || s.x < -.5f ? 156 :
                   (buttons & XINPUT_GAMEPAD_DPAD_RIGHT) || s.x > .5f ? 157 : 0;
        DWORD now = GetTickCount();
        if (next != menu_key) {
            if (menu_key) key(menu_key, 0);
            menu_key = next;
            if (next) key(next, 1);
            repeat_at = now + 420;
        } else if (next && (LONG)(now - repeat_at) >= 0) {
            key(next, 1); repeat_at = now + 210;
        }
    }
    previous = buttons;
}

static void poll_pad(void) {
    if (!ready) {
        FloatDvar reg = ENGINE(FloatDvar, 0x4051D0);
        enabled = ENGINE(BoolDvar, 0x429390)("gpad_enabled", 1, 1, "Enable native controller input");
        invert = ENGINE(BoolDvar, 0x429390)("input_invertPitch", 0, 1, "Invert controller pitch");
        assist = ENGINE(BoolDvar, 0x429390)("gpad_slowdown_enabled", 1, 1, "Controller slowdown over visible aim targets");
        lockon = ENGINE(BoolDvar, 0x429390)("gpad_lockon_enabled", 1, 1, "Controller rotational assistance");
        deadzone = reg("gpad_stick_deadzone_min", .2f, 0, .8f, 1, "Inner stick deadzone");
        outer = reg("gpad_stick_deadzone_max", .01f, 0, .1f, 1, "Outer stick deadzone");
        sensitivity = reg("input_viewSensitivity", 1, .1f, 5, 1, "Controller look sensitivity");
        yaw_rate = reg("aim_turnrate_yaw", 260, 0, 1000, 1, "Controller yaw speed");
        pitch_rate = reg("aim_turnrate_pitch", 90, 0, 1000, 1, "Controller pitch speed");
        yaw_ads = reg("aim_turnrate_yaw_ads", 90, 0, 1000, 1, "Controller aimed yaw speed");
        pitch_ads = reg("aim_turnrate_pitch_ads", 55, 0, 1000, 1, "Controller aimed pitch speed");
        ready = 1;
        log_line("Main-frame hook active; XInput and native menu input ready");
    }
    DWORD owner = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &owner);
    XINPUT_STATE state = {0};
    int connected = 0;
    if (enabled[16] && owner == GetCurrentProcessId())
        for (DWORD index = 0; index < XUSER_MAX_COUNT; ++index)
            if (XInputGetState(index, &state) == ERROR_SUCCESS) { connected = 1; break; }
    unsigned char *paused = ENGINE(FindDvar, 0x4B29D0)("cl_paused");
    int gameplay = ENGINE(int (__cdecl *)(int), 0x4EEA50)(0) &&
        !*(volatile int *)GAME_MEMORY(0x929140) && !(paused && *(int *)(paused + 16));
    process_pad(&state.Gamepad, connected, gameplay);
}

void __cdecl apply_gamepad(unsigned char *cmd) {
    static int logged;
    if (!logged) { log_line("Native usercmd hook active (analog movement and view angles)"); logged = 1; }
    if (!ready || !playing) return;
    Stick move = stick(pad.sThumbLX, pad.sThumbLY, value(deadzone), value(outer));
    Stick look = stick(pad.sThumbRX, pad.sThumbRY, value(deadzone), value(outer));
    cmd[0x1A] = movement((signed char)cmd[0x1A], move.y);
    cmd[0x1B] = movement((signed char)cmd[0x1B], move.x);
    float dt = limit(*(int *)GAME_MEMORY(0x88BA04) / 1000.f, 0, .2f);
    const AimGlobals *aa = (const AimGlobals *)GAME_MEMORY(0x73EA90);
    float ads = aa->initialized ? limit(aa->ads, 0, 1) : 0;
    float speed = dt * value(sensitivity);
    float yaw = value(yaw_rate) * (1 - ads) + value(yaw_ads) * ads;
    float pitch = value(pitch_rate) * (1 - ads) + value(pitch_ads) * ads;
    // This target list is also used by SP's native auto-melee. It is rebuilt
    // by the engine, including visibility, every frame; never enumerate actors
    // through walls or apply assistance to mouse input.
    if (aa->initialized && aa->weapon && aa->has_ammo && aa->count >= 0 && aa->count <= 64 &&
        !(held & (XINPUT_GAMEPAD_LEFT_SHOULDER | XINPUT_GAMEPAD_RIGHT_SHOULDER | XINPUT_GAMEPAD_RIGHT_THUMB))) {
        for (int i = 0; i < aa->count; ++i) {
            const AimTarget *t = &aa->targets[i];
            if (!near_crosshair(t)) continue;
            if (assist[16]) speed *= .4f + .1f * ads;
            if (lockon[16] && (fabsf(look.x) > .05f || fabsf(look.y) > .05f || fabsf(move.x) > .05f)) {
                Stick correction = tracking(t, aa->velocity, aa->axis[1], aa->axis[2], dt);
                if (isfinite(correction.x) && isfinite(correction.y)) {
                    *(float *)GAME_MEMORY(0x9291C0) += correction.x;
                    *(float *)GAME_MEMORY(0x9291BC) -= correction.y;
                }
            }
            break;
        }
    }
    *(float *)GAME_MEMORY(0x9291C0) -= look.x * yaw * speed;
    *(float *)GAME_MEMORY(0x9291BC) -= look.y * pitch * speed * (invert[16] ? -1 : 1);
}

// The engine passes usercmd in EDI and its mouse delta on the stack, not via
// the C ABI. Leave that stack intact and tail-call its original mouse handler.
__attribute__((naked)) static void mouse_stub(void) {
    __asm__ volatile("pushal\n\tpush %edi\n\tcall _apply_gamepad\n\tadd $4, %esp\n\tpopal\n\tjmp *_original_mouse");
}
static void __cdecl frame_stub(void) { original_frame(); poll_pad(); }

static int patch_call(uintptr_t site, void *target) {
    DWORD old;
    if (!VirtualProtect((void *)site, 5, PAGE_EXECUTE_READWRITE, &old)) return 0;
    int32_t displacement = (uintptr_t)target - site - 5;
    memcpy((void *)(site + 1), &displacement, 4);
    FlushInstructionCache(GetCurrentProcess(), (void *)site, 5);
    DWORD ignored;
    VirtualProtect((void *)site, 5, old, &ignored);
    return 1;
}

static int patch_directive(void) {
    // One complete six-byte instruction, with no relative operands.
    unsigned char *trampoline = VirtualAlloc(NULL, 11, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!trampoline) return 0;
    memcpy(trampoline, (void *)0x4BBD10, 6);
    trampoline[6] = 0xE9;
    int32_t rel = 0x4BBD16 - (uintptr_t)(trampoline + 11);
    memcpy(trampoline + 7, &rel, 4);
    DWORD old;
    if (!VirtualProtect(trampoline, 11, PAGE_EXECUTE_READ, &old)) return 0;
    FlushInstructionCache(GetCurrentProcess(), trampoline, 11);
    original_directive = (Directive)trampoline;
    if (!VirtualProtect((void *)0x4BBD10, 6, PAGE_EXECUTE_READWRITE, &old)) return 0;
    *(unsigned char *)0x4BBD10 = 0xE9;
    rel = (uintptr_t)directive_stub - 0x4BBD15;
    memcpy((void *)0x4BBD11, &rel, 4);
    *(unsigned char *)0x4BBD15 = 0x90;
    FlushInstructionCache(GetCurrentProcess(), (void *)0x4BBD10, 6);
    DWORD ignored;
    VirtualProtect((void *)0x4BBD10, 6, old, &ignored);
    return 1;
}

__declspec(dllexport) DWORD WINAPI Initialize(void *main_id) {
    log_line("Initializing native SP159 controller extension");
    HANDLE thread = OpenThread(THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, FALSE, (DWORD)(uintptr_t)main_id);
    if (!thread) return 0;
    // Wait until AlterWare has mapped SP and installed its scheduler hook.
    for (int attempt = 0; attempt < 1200; ++attempt) {
        Sleep(25);
        MEMORY_BASIC_INFORMATION info;
        if (!VirtualQuery((void *)0x49C3AF, &info, sizeof(info)) || info.State != MEM_COMMIT ||
            (info.Protect & (PAGE_NOACCESS | PAGE_GUARD))) continue;
        if (*(unsigned char *)0x49C3AF != 0xE8) continue;
        int32_t rel; memcpy(&rel, (void *)0x49C3B0, 4);
        uintptr_t target = 0x49C3B4 + rel;
        if (target == 0x4D3FC0 || *(int *)0x145AC28 != 16384) continue;
        if (SuspendThread(thread) == (DWORD)-1) break;
        CONTEXT context = {.ContextFlags = CONTEXT_CONTROL};
        int safe = GetThreadContext(thread, &context) &&
            !(context.Eip >= 0x49C3AF && context.Eip < 0x49C3B4) &&
            !(context.Eip >= 0x57BB4D && context.Eip < 0x57BB52) &&
            !(context.Eip >= 0x4BBD10 && context.Eip < 0x4BBD16);
        int ok = 0;
        if (safe && !memcmp((void *)0x57BB4D, "\xe8\x9e\xf4\xff\xff", 5) &&
            !memcmp((void *)0x4BBD10, "\x81\xec\x08\x02\x00\x00", 6)) {
            original_frame = (Frame)target;
            ok = patch_directive() && patch_call(0x57BB4D, mouse_stub) && patch_call(0x49C3AF, frame_stub);
        }
        ResumeThread(thread);
        if (!safe) continue;
        CloseHandle(thread);
        log_line(ok ? "Hooks installed; preserved AlterWare scheduler" : "Unsupported engine hooks; refusing to patch");
        return ok;
    }
    CloseHandle(thread);
    log_line("Timed out waiting for SP159 initialization");
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(instance);
    return TRUE;
}
