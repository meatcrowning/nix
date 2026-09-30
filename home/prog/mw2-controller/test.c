#include <assert.h>
#include <stdio.h>
#include "pad.h"
#include "prompts.h"

int main(void) {
    Stick s = stick(3000, -2000, .2f, .01f);
    assert(s.x == 0 && s.y == 0);
    s = stick(-32768, 32767, .2f, .01f);
    assert(isfinite(s.x) && isfinite(s.y));
    assert(fabsf(s.x * s.x + s.y * s.y - 1) < .00001f);
    s = stick(0, 16384, .2f, .01f);
    assert(s.x == 0 && s.y > .37f && s.y < .39f);
    assert(movement(0, s.y) == 48);
    assert(movement(100, 1) == 127 && movement(-100, -1) == -127);
    assert(movement(-50, 0) == -50);
    AimTarget target = {.entity = 4, .mins = {-.1f, -.1f}, .maxs = {.1f, .1f}, .distance_squared = 10000};
    assert(near_crosshair(&target));
    target.distance_squared = 2000000;
    assert(!near_crosshair(&target));
    target.distance_squared = 10000; target.mins[0] = .1f;
    assert(!near_crosshair(&target));
    target.mins[0] = NAN;
    assert(!near_crosshair(&target));
    target.velocity[1] = 100;
    float still[] = {0, 0, 0}, right[] = {0, -1, 0}, up[] = {0, 0, 1};
    s = tracking(&target, still, right, up, .01f);
    assert(s.x < -.34f && s.x > -.35f && s.y == 0);
    s = tracking(&target, target.velocity, right, up, .01f);
    assert(s.x == 0 && s.y == 0);
    char out[256];
    assert(replace_prompts("Hold [{+usereload}] then [{+attack}]", out, sizeof(out)));
    assert(!strcmp(out, "Hold [Square] then [R2]"));
    assert(replace_prompts("[{+unknown}] [{+attack_extra}] [{+attack", out, sizeof(out)));
    assert(!strcmp(out, "[{+unknown}] [{+attack_extra}] [{+attack"));
    assert(!replace_prompts("[{+usereload}]", out, 3));
    assert(replace_prompts("", out, 1) && !out[0]);
    puts("controller math, aim region, and prompt tests passed");
}
