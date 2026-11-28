#define _GNU_SOURCE
#include <dlfcn.h>
#include <link.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* DF 53.17 still supplies surroundings bits 2 (tavern) and 4 (workshop),
 * but its FMOD surroundings updater omits those events. Reconnect the native
 * events without accessing game memory or changing the game's sound banks.
 * A DFHack observer supplies nearby fortress crowds and occupied trade depots,
 * which have no inputs in environment_state. Observations expire after 5 s.
 * Gate the environment_state ABI to the Steam Linux executable verified here.
 */
static const unsigned char build_id[20] = {
    0xf9,0xd1,0x3d,0x46,0xa8,0xb7,0xe2,0xe8,0xb7,0x0c,
    0x38,0x01,0x27,0xde,0xcf,0x53,0xc4,0x35,0x81,0xbd
};
static bool enabled;
static atomic_uint surroundings;
static const char *activity_path;
static unsigned crowd_level, depot_active;
static bool crowd_parameter_owned;
static float previous_walla;
struct environment_state {
    int32_t biome, weather;
    uint32_t surroundings;
    int32_t elevation;
    float occlusion, evilness, savagery;
};
_Static_assert(sizeof(struct environment_state) == 28, "DF 53.17 environment ABI");
struct layer {
    unsigned bit;
    const char *path;
    void *instance;
    float volume;
    enum { ENVIRONMENT, DEPOT, CROWD } activity;
};
static struct layer layers[] = {
    {2, "event:/Ambiance/Surroundings/Tavern", NULL, 0, ENVIRONMENT},
    {4, "event:/Ambiance/Surroundings/Workshop", NULL, 0, ENVIRONMENT},
    {0, "event:/Ambiance/Surroundings/TradeDepot", NULL, 0, DEPOT},
    {0, "event:/Ambiance/Dynamic/Global Ambience/Global Surroundings/Walla_Fortress", NULL, 0, CROWD},
};
static int (*get_event)(void *, const char *, void **);
static int (*get_count)(void *, int *);
static int (*create_instance)(void *, void **);
static int (*start_instance)(void *);
static int (*stop_instance)(void *, int);
static int (*release_instance)(void *);
static int (*set_volume)(void *, float);
static int (*set_parameter)(void *, const char *, float, int);
static int (*get_parameter)(void *, const char *, float *, float *);

static int check_build(struct dl_phdr_info *info, size_t size, void *data)
{
    (void)size;
    (void)data;
    if (info->dlpi_name[0]) return 0;
    for (int i = 0; i < info->dlpi_phnum; ++i) {
        const ElfW(Phdr) *p = &info->dlpi_phdr[i];
        if (p->p_type != PT_NOTE) continue;
        const unsigned char *s = (void *)(info->dlpi_addr + p->p_vaddr);
        const unsigned char *end = s + p->p_memsz;
        while ((size_t)(end - s) >= sizeof(ElfW(Nhdr))) {
            ElfW(Nhdr) n;
            memcpy(&n, s, sizeof(n));
            s += sizeof(n);
            size_t namesize = ((size_t)n.n_namesz + 3) & ~(size_t)3;
            size_t descsize = ((size_t)n.n_descsz + 3) & ~(size_t)3;
            if (namesize > (size_t)(end - s) || descsize > (size_t)(end - s) - namesize) break;
            if (n.n_type == NT_GNU_BUILD_ID && n.n_namesz == 4 &&
                !memcmp(s, "GNU", 4) && n.n_descsz == sizeof(build_id) &&
                !memcmp(s + namesize, build_id, sizeof(build_id))) enabled = true;
            s += namesize + descsize;
        }
    }
    return 1;
}

__attribute__((constructor)) static void initialize(void)
{
    const char *off = getenv("DF_AMBIENCE_FIX");
    if (off && !strcmp(off, "0")) return;
    dl_iterate_phdr(check_build, NULL);
    activity_path = getenv("DF_AMBIENCE_STATE");
    if (enabled) fprintf(stderr, "df-ambience: restoring DF 53.17 activity ambience\n");
}

/* These hooks forward the original C++ ABI; FMOD's opaque C API supplies all
 * playback operations. No Lua ABI, DFHack structures or binary offsets used.
 */
bool environment(void *, const struct environment_state *)
    __asm__("_ZN12musicsoundst15set_environmentERKN7dfaudio17environment_stateE");
bool environment(void *self, const struct environment_state *state)
{
    static bool (*real)(void *, const struct environment_state *);
    if (!real) real = dlsym(RTLD_NEXT, "_ZN12musicsoundst15set_environmentERKN7dfaudio17environment_stateE");
    if (enabled) atomic_store(&surroundings, state->surroundings);
    return real(self, state);
}

static bool resolve_api(void)
{
#define RESOLVE(var, symbol) do { if (!var) var = dlsym(RTLD_NEXT, symbol); if (!var) return false; } while (0)
    RESOLVE(get_event, "FMOD_Studio_System_GetEvent");
    RESOLVE(get_count, "FMOD_Studio_EventDescription_GetInstanceCount");
    RESOLVE(create_instance, "FMOD_Studio_EventDescription_CreateInstance");
    RESOLVE(start_instance, "FMOD_Studio_EventInstance_Start");
    RESOLVE(stop_instance, "FMOD_Studio_EventInstance_Stop");
    RESOLVE(release_instance, "FMOD_Studio_EventInstance_Release");
    RESOLVE(set_volume, "FMOD_Studio_EventInstance_SetVolume");
    RESOLVE(set_parameter, "FMOD_Studio_System_SetParameterByName");
    RESOLVE(get_parameter, "FMOD_Studio_System_GetParameterByName");
#undef RESOLVE
    return true;
}

static void restore_walla(void *system)
{
    if (crowd_parameter_owned) set_parameter(system, "Walla", previous_walla, 1);
    crowd_parameter_owned = false;
}

static bool embedded_crowd(void *system)
{
    float biome;
    void *description;
    int count;
    /* Settlement biomes already embed a Walla layer in Global Ambience.
     * Fortress maps normally send a landscape biome instead. Feed the shared
     * parameter in both cases, adding a standalone layer only for landscapes.
     */
    if (get_parameter(system, "Biome", &biome, NULL) ||
        !(biome == 8 || biome == 10 || biome == 11 || biome == 14 || biome == 15)) return false;
    return !get_event(system, "event:/Ambiance/Dynamic/Global Ambience/Global Ambience", &description) &&
        !get_count(description, &count) && count > 0;
}

static void read_activity(void)
{
    static time_t last_read;
    time_t now = time(NULL);
    if (now == last_read) return;
    last_read = now;
    crowd_level = depot_active = 0;
    if (!activity_path) return;
    FILE *file = fopen(activity_path, "r");
    if (!file) return;
    long long stamp;
    unsigned crowd, depot;
    if (fscanf(file, "%lld %u %u", &stamp, &crowd, &depot) == 3 &&
        stamp <= (long long)now && (long long)now - stamp <= 5 && crowd <= 3 && depot <= 1) {
        crowd_level = crowd;
        depot_active = depot;
    }
    fclose(file);
}

static void release_layers(void *system)
{
    for (size_t i = 0; i < sizeof(layers)/sizeof(layers[0]); ++i) {
        struct layer *l = &layers[i];
        if (l->instance) {
            stop_instance(l->instance, 1);
            release_instance(l->instance);
        }
        l->instance = NULL;
        l->volume = 0;
    }
    atomic_store(&surroundings, 0);
    restore_walla(system);
    crowd_level = depot_active = 0;
}

int update(void *) __asm__("_ZN4FMOD6Studio6System6updateEv");
int update(void *system)
{
    static int (*real)(void *);
    if (!real) real = dlsym(RTLD_NEXT, "_ZN4FMOD6Studio6System6updateEv");
    if (enabled && resolve_api()) {
        unsigned flags = atomic_load(&surroundings);
        read_activity();
        bool crowd_wanted = crowd_level != 0 && !(flags & 2) && !depot_active;
        if (crowd_wanted && !crowd_parameter_owned &&
            !get_parameter(system, "Walla", &previous_walla, NULL) &&
            !set_parameter(system, "Walla", crowd_level, 1)) crowd_parameter_owned = true;
        if (crowd_wanted && crowd_parameter_owned) set_parameter(system, "Walla", crowd_level, 0);
        bool use_embedded_crowd = crowd_wanted && embedded_crowd(system);
        for (size_t i = 0; i < sizeof(layers)/sizeof(layers[0]); ++i) {
            struct layer *l = &layers[i];
            bool crowd = l->activity == CROWD;
            bool wanted = l->bit ? (flags & l->bit) != 0 :
                crowd ? crowd_wanted && crowd_parameter_owned && !use_embedded_crowd : depot_active != 0;
            if (wanted && !l->instance) {
                void *description = NULL;
                int count = 0;
                /* Leave a native instance alone if a later fix starts it. */
                if (get_event(system, l->path, &description) ||
                    get_count(description, &count) || count ||
                    create_instance(description, &l->instance)) continue;
                set_volume(l->instance, 0);
                if (start_instance(l->instance)) {
                    release_instance(l->instance);
                    l->instance = NULL;
                    continue;
                }
                fprintf(stderr, "df-ambience: started %s\n", l->path);
            }
            if (!l->instance) continue;
            /* Match the existing 50 Hz presentation rate with a short fade. */
            /* A modest +1.94 dB lift over the stock ambience event. */
            float target = wanted ? (crowd ? 1.0f : 1.25f) : 0.0f;
            l->volume += (target - l->volume) * 0.04f;
            set_volume(l->instance, l->volume);
            if (!wanted && l->volume < 0.001f) {
                stop_instance(l->instance, 1);
                release_instance(l->instance);
                l->instance = NULL;
                l->volume = 0;
                fprintf(stderr, "df-ambience: stopped %s\n", l->path);
            }
        }
        if (!crowd_wanted && !layers[3].instance) restore_walla(system);
    }
    return real(system);
}

int unload(void *) __asm__("_ZN4FMOD6Studio6System9unloadAllEv");
int unload(void *system)
{
    static int (*real)(void *);
    if (!real) real = dlsym(RTLD_NEXT, "_ZN4FMOD6Studio6System9unloadAllEv");
    if (enabled && resolve_api()) release_layers(system);
    return real(system);
}

int release_system(void *) __asm__("_ZN4FMOD6Studio6System7releaseEv");
int release_system(void *system)
{
    static int (*real)(void *);
    if (!real) real = dlsym(RTLD_NEXT, "_ZN4FMOD6Studio6System7releaseEv");
    if (enabled && resolve_api()) release_layers(system);
    return real(system);
}

void reset_audio(void *) __asm__("_ZN12musicsoundst15reset_all_audioEv");
void reset_audio(void *self)
{
    static void (*real)(void *);
    if (!real) real = dlsym(RTLD_NEXT, "_ZN12musicsoundst15reset_all_audioEv");
    if (enabled) atomic_store(&surroundings, 0);
    real(self);
}
