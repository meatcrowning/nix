#pragma once
#include <stdint.h>
bool gpu_capture_line(float sx, float sy, float ex, float ey, float start, float end, float width);
bool gpu_capture_fade(int width, int height, const uint32_t *field);
bool gpu_active();
// Seed for the next component load ('W' shape, 'D' field, 'C' colours, 'P'
// particle): a recalled preset's seed when one is pending, else a fresh one.
// Loads evaluate their rnd() constants right away, so seeding the load makes a
// recalled look match the saved one, not just its file names.
long gpu_load_seed(char kind);

// Independent equation clocks; particles use theirs for END_TIME/lifetime too.
float* gpu_clock(char kind, float* fallback);
bool gpu_smooth_wave(float* samples, int count);

float gpu_scene_scale();
void gpu_capture_field(int width, int height, const float* uv);

void gpu_particle_layer(bool particles);

// A live override; preset connection flags remain unchanged when disabled.
bool gpu_force_connect();
