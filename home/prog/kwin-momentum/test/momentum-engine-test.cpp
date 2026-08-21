/*
    kwin-momentum — offscreen regression test for the session-agnostic momentum
    core (momentumengine.{h,cpp}). Pure math, no KWin, no session — the only part
    of this plugin an agent can verify without the user's touchpad (runbook §5).

    Build + run on book (Fedora g++; the engine needs no KWin headers):

      env -u CMAKE_PREFIX_PATH -u LIBRARY_PATH -u CPATH -u C_INCLUDE_PATH \
          -u CPLUS_INCLUDE_PATH -u PKG_CONFIG_PATH \
        /usr/bin/g++ -std=c++20 -I ../src \
          momentum-engine-test.cpp ../src/momentumengine.cpp -o /tmp/kwm-enginetest
      /tmp/kwm-enginetest   # exit 0 = all pass

    What it pins (momentum-engine-spec §1.4, §3):
      * coast distance ≈ v0/k  (closed-form integral, §3.2)
      * tick-rate independence (30 Hz vs 144 Hz within 5%)
      * exactly one axis-stop, never a mid-flight zero  (§3.3)
      * min_start_velocity, staleness, and axis-lock gates  (§1.4, §3.4)
*/
#include "momentumengine.h"

#include <chrono>
#include <cmath>
#include <cstdio>

using namespace KWinMomentum;
using std::chrono::microseconds;

static microseconds ms(double m) { return microseconds((long long)(m * 1000)); }

int main()
{
    int fails = 0;

    // v0 ≈ 2400 px/s: twelve 20 px frames at ~120 Hz.
    auto drag = [](MomentumEngine &e, double perFrame, double dxPerFrame = 0.0) {
        double t = 0;
        for (int i = 0; i < 12; i++) { e.feed(dxPerFrame, perFrame, ms(t)); t += 8.333; }
        return t;
    };

    // --- T1: coast distance ≈ v0/k, one stop, no zero, within max-duration ---
    {
        MomentumEngine e;
        double dist = 0; int stops = 0; bool zero = false;
        e.setEmit([&](double dx, double dy) { dist += dy; if (dx == 0.0 && dy == 0.0) zero = true; });
        e.setStop([&]() { stops++; });
        double t = drag(e, 20.0);
        bool started = e.release(ms(t));
        double ct = t;
        for (int i = 0; i < 400 && e.coasting(); i++) { ct += 16.667; e.tick(ms(ct)); }
        const double expected = 2400.0 / 3.6;
        printf("T1 started=%d dist=%.1f expected=%.1f stops=%d elapsed=%.0fms\n",
               started, dist, expected, stops, ct - t);
        if (!started) { printf("  FAIL: no fling\n"); fails++; }
        if (e.coasting()) { printf("  FAIL: still coasting\n"); fails++; }
        if (stops != 1) { printf("  FAIL: want 1 stop, got %d\n", stops); fails++; }
        if (zero) { printf("  FAIL: emitted mid-flight zero\n"); fails++; }
        if (std::abs(dist - expected) / expected > 0.25) { printf("  FAIL: distance off >25%%\n"); fails++; }
        if (ct - t > 2100) { printf("  FAIL: exceeded max-duration\n"); fails++; }
    }

    // --- T2: tick-rate independence ---
    {
        auto run = [&](double hz) {
            MomentumEngine e; double dist = 0;
            e.setEmit([&](double, double dy) { dist += dy; });
            e.setStop([]() {});
            double t = drag(e, 20.0);
            e.release(ms(t));
            double ct = t, step = 1000.0 / hz;
            for (int i = 0; i < 2000 && e.coasting(); i++) { ct += step; e.tick(ms(ct)); }
            return dist;
        };
        double d30 = run(30), d144 = run(144);
        printf("T2 30Hz=%.1f 144Hz=%.1f diff=%.3f%%\n", d30, d144, 100 * std::abs(d30 - d144) / d144);
        if (std::abs(d30 - d144) / d144 > 0.05) { printf("  FAIL: >5%% rate dependence\n"); fails++; }
    }

    // --- T3: below min_start_velocity -> no fling ---
    {
        MomentumEngine e; e.setEmit([](double, double) {}); e.setStop([]() {});
        double t = 0; for (int i = 0; i < 6; i++) { e.feed(0, 1.0, ms(t)); t += 8.333; }
        bool started = e.release(ms(t));
        printf("T3 slow started=%d (want 0)\n", started);
        if (started) { printf("  FAIL\n"); fails++; }
    }

    // --- T4: staleness gate ---
    {
        MomentumEngine e; e.setEmit([](double, double) {}); e.setStop([]() {});
        double t = drag(e, 20.0) + 250.0; // rested 250 ms > staleMs
        bool started = e.release(ms(t));
        printf("T4 stale started=%d (want 0)\n", started);
        if (started) { printf("  FAIL\n"); fails++; }
    }

    // --- T5: axis lock (near-vertical flick doesn't drift sideways) ---
    {
        MomentumEngine e; double dx = 0;
        e.setEmit([&](double x, double) { dx += x; }); e.setStop([]() {});
        double t = drag(e, 20.0, 2.0); // 10:1 vertical
        e.release(ms(t)); double ct = t;
        for (int i = 0; i < 400 && e.coasting(); i++) { ct += 16.667; e.tick(ms(ct)); }
        printf("T5 axis-lock dx_sum=%.2f (want ~0)\n", dx);
        if (std::abs(dx) > 0.5) { printf("  FAIL: minor axis not locked\n"); fails++; }
    }

    printf("\n%s (%d failures)\n", fails ? "FAILURES" : "ALL PASS", fails);
    return fails ? 1 : 0;
}
