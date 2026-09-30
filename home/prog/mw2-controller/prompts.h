#ifndef MW2_PROMPTS_H
#define MW2_PROMPTS_H
#include <string.h>
#include <stddef.h>

static int replace_prompts(const char *src, char *out, size_t size) {
    static const struct { const char *action, *label; } prompts[] = {
        {"+usereload", "[Square]"}, {"+activate", "[Square]"}, {"+reload", "[Square]"},
        {"+gostand", "[Cross]"}, {"+stance", "[Circle]"}, {"+movedown", "[Circle]"},
        {"+prone", "[Hold Circle]"}, {"weapnext", "[Triangle]"},
        {"+attack", "[R2]"}, {"+speed_throw", "[L2]"}, {"+toggleads_throw", "[L2]"},
        {"+frag", "[R1]"}, {"+smoke", "[L1]"}, {"+melee", "[R3]"},
        {"+breath_sprint", "[L3]"}, {"+sprint", "[L3]"}, {"+holdbreath", "[L3]"},
        {"+actionslot 1", "[D-pad Up]"}, {"+actionslot 2", "[D-pad Down]"},
        {"+actionslot 3", "[D-pad Left]"}, {"+actionslot 4", "[D-pad Right]"},
        {"+forward", "[Left stick Up]"}, {"+back", "[Left stick Down]"},
        {"+moveleft", "[Left stick Left]"}, {"+moveright", "[Left stick Right]"},
        {"togglemenu", "[Options]"}, {"+scores", "[Share]"},
    };
    size_t written = 0;
    while (*src) {
        const char *replacement = NULL;
        size_t consumed = 1;
        if (src[0] == '[' && src[1] == '{') {
            for (size_t i = 0; i < sizeof(prompts) / sizeof(*prompts); ++i) {
                size_t n = strlen(prompts[i].action);
                if (!strncmp(src + 2, prompts[i].action, n) && !strncmp(src + 2 + n, "}]", 2)) {
                    replacement = prompts[i].label; consumed = n + 4; break;
                }
            }
        }
        size_t n = replacement ? strlen(replacement) : 1;
        if (written + n >= size) return 0;
        memcpy(out + written, replacement ? replacement : src, n);
        written += n; src += consumed;
    }
    if (written >= size) return 0;
    out[written] = 0;
    return 1;
}
#endif
