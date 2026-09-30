// Runs in a disposable Wine prefix. No game process, windows, XInput reads,
// or operating-system input events: all engine calls terminate in these sinks.
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
static void *test_address(uintptr_t address);
static void *test_memory(uintptr_t address);
#define ENGINE(type, address) ((type)test_address(address))
#define GAME_MEMORY(address) test_memory(address)
#include "controller.c"

static char commands[4096];
static unsigned char memory[0x200000];
static void *test_memory(uintptr_t address) {
    assert(address >= 0x730000 && address < 0x930000);
    return memory + address - 0x730000;
}
static int keys[128], key_count;
static void __cdecl sink_command(int client, const char *text) {
    assert(client == 0 && strlen(commands) + strlen(text) < sizeof(commands));
    strcat(commands, text);
}
static void __cdecl sink_key(int client, int code, int down, unsigned time) {
    (void)time;
    assert(client == 0 && key_count < 128);
    keys[key_count++] = down ? code : -code;
}
static unsigned __cdecl milliseconds(void) { return 1000; }
static void *test_address(uintptr_t address) {
    switch (address) {
    case 0x4A1090: return sink_command;
    case 0x442D60: return sink_key;
    case 0x44E130: return milliseconds;
    default: assert(!"Unexpected engine call in isolated controller test"); return NULL;
    }
}
static unsigned char *setting(float f) {
    unsigned char *result = calloc(32, 1);
    assert(result); memcpy(result + 16, &f, 4); return result;
}
static unsigned char *toggle(int on) {
    unsigned char *result = setting(0); result[16] = on; return result;
}
int main(void) {
    // Engine-memory accesses resolve into this process's private test array.
    ready = 1;
    deadzone = setting(.2f); outer = setting(.01f); sensitivity = setting(1);
    yaw_rate = setting(260); pitch_rate = setting(90); yaw_ads = setting(90); pitch_ads = setting(55);
    invert = toggle(0); assist = toggle(1); lockon = toggle(1);
    XINPUT_GAMEPAD sample = {.wButtons = XINPUT_GAMEPAD_A};
    process_pad(&sample, 1, 0);
    assert(key_count == 2 && keys[0] == 13 && keys[1] == -13);
    process_pad(&sample, 1, 1); // Holding menu confirmation must not jump.
    assert(!commands[0]);
    sample.wButtons = 0; process_pad(&sample, 1, 1);
    sample.bRightTrigger = 255; process_pad(&sample, 1, 1);
    assert(!strcmp(commands, "+attack\n"));
    process_pad(&sample, 1, 1);
    assert(!strcmp(commands, "+attack\n"));
    process_pad(&sample, 0, 1);
    assert(!strcmp(commands, "+attack\n-attack\n") && !held && !playing);
    sample = (XINPUT_GAMEPAD){0}; process_pad(&sample, 1, 1);
    sample.wButtons = XINPUT_GAMEPAD_LEFT_SHOULDER; process_pad(&sample, 1, 1);
    process_pad(&sample, 1, 0);
    assert(strstr(commands, "+smoke\n-smoke\n") && !held);
    sample = (XINPUT_GAMEPAD){.sThumbLX = 32767, .sThumbRY = 32767};
    process_pad(&sample, 1, 1);
    unsigned char cmd[64] = {0};
    *(int *)GAME_MEMORY(0x88BA04) = 10;
    apply_gamepad(cmd);
    assert((signed char)cmd[0x1B] == 127 && cmd[0x1A] == 0);
    assert(fabsf(*(float *)GAME_MEMORY(0x9291BC) + .9f) < .001f);
    assert(*(float *)GAME_MEMORY(0x9291C0) == 0);
    invert[16] = 1; apply_gamepad(cmd);
    assert(fabsf(*(float *)GAME_MEMORY(0x9291BC)) < .001f);
    AimGlobals *aa = (AimGlobals *)GAME_MEMORY(0x73EA90);
    aa->initialized = aa->weapon = aa->has_ammo = 1;
    aa->count = 1;
    aa->targets[0] = (AimTarget){.entity = 1, .mins = {-.1f, -.1f}, .maxs = {.1f, .1f}, .distance_squared = 10000};
    sample = (XINPUT_GAMEPAD){.sThumbRX = 32767}; process_pad(&sample, 1, 1);
    apply_gamepad(cmd);
    assert(fabsf(*(float *)GAME_MEMORY(0x9291C0) + 1.04f) < .001f);
    aa->targets[0].mins[0] = .2f;
    *(float *)GAME_MEMORY(0x9291C0) = 0; apply_gamepad(cmd);
    assert(fabsf(*(float *)GAME_MEMORY(0x9291C0) + 2.6f) < .001f);
    process_pad(&sample, 0, 1);
    float before = *(float *)GAME_MEMORY(0x9291C0); apply_gamepad(cmd);
    assert(*(float *)GAME_MEMORY(0x9291C0) == before);
    puts("native controller tests passed: menus, transitions, disconnect, analog movement, invert, aim slowdown");
    return 0;
}
