#ifndef MW2_PAD_H
#define MW2_PAD_H
#include <math.h>
#include <stdint.h>

typedef struct { float x, y; } Stick;
typedef struct {
    int entity;
    float mins[2], maxs[2], position[3], velocity[3], distance_squared, crosshair_squared;
} AimTarget;
_Static_assert(sizeof(AimTarget) == 0x34, "SP159 aim target layout");
static inline int near_crosshair(const AimTarget *t) {
    // The engine supplies its visible aim targets; only slow the stick within
    // their projected bounds, with a small margin around the crosshair.
    return t->entity >= 0 && t->entity < 2047 &&
        t->distance_squared > 0 && t->distance_squared <= 1000.f * 1000.f &&
        t->mins[0] <= .03f && t->maxs[0] >= -.03f &&
        t->mins[1] <= .03f && t->maxs[1] >= -.03f;
}
static inline float limit(float x, float lo, float hi) {
    return x < lo ? lo : x > hi ? hi : x;
}
static inline Stick stick(int16_t x, int16_t y, float deadzone, float outer) {
    Stick s = {x / 32768.f, y / 32768.f};
    float length = sqrtf(s.x * s.x + s.y * s.y);
    if (length <= deadzone) return (Stick){0, 0};
    float scale = limit((length - deadzone) / (1 - outer - deadzone), 0, 1) / length;
    return (Stick){s.x * scale, s.y * scale};
}
static inline signed char movement(int old, float axis) {
    return (signed char)limit(old + roundf(axis * 127), -127, 127);
}
static inline Stick tracking(const AimTarget *t, const float velocity[3],
                             const float right[3], const float up[3], float dt) {
    float yaw = 0, pitch = 0;
    for (int i = 0; i < 3; ++i) {
        float relative = t->velocity[i] - velocity[i];
        yaw += relative * right[i];
        pitch += relative * up[i];
    }
    float scale = 57.2957795f * .6f / sqrtf(t->distance_squared);
    return (Stick){limit(yaw * scale, -90, 90) * dt,
                   limit(pitch * scale, -90, 90) * dt};
}
#endif
