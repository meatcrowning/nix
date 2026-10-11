/* Quantal Compiz's unfocused-window AnyButton grab breaks XI2 scrolling.
 * Keep click-to-focus and modified wheel bindings; let bare wheel events
 * reach the client without the synthetic grab/ungrab crossing events.
 */
#define _GNU_SOURCE
#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <dlfcn.h>
#include <string.h>
#include <unistd.h>

static int is_compiz(void) {
    char path[4096];
    ssize_t size = readlink("/proc/self/exe", path, sizeof(path) - 1);
    if (size < 0) return 0;
    path[size] = 0;
    const char *base = strrchr(path, '/');
    return base && strcmp(base + 1, "compiz") == 0;
}

int XGrabButton(Display *display, unsigned int button, unsigned int modifiers,
                Window window, Bool owner_events, unsigned int event_mask,
                int pointer_mode, int keyboard_mode, Window confine_to, Cursor cursor) {
    typedef int (*Grab)(Display *, unsigned int, unsigned int, Window, Bool,
                       unsigned int, int, int, Window, Cursor);
    Grab original = (Grab)dlsym(RTLD_NEXT, "XGrabButton");
    int result = original(display, button, modifiers, window, owner_events,
                          event_mask, pointer_mode, keyboard_mode, confine_to, cursor);
    if (!is_compiz() || button != AnyButton || modifiers != AnyModifier ||
        owner_events || pointer_mode != GrabModeSync || keyboard_mode != GrabModeAsync)
        return result;
    unsigned int locks = LockMask;
    XModifierKeymap *map = XGetModifierMapping(display);
    if (map) {
        KeyCode num = XKeysymToKeycode(display, XK_Num_Lock);
        KeyCode scroll = XKeysymToKeycode(display, XK_Scroll_Lock);
        for (int mod = 0; mod < 8; ++mod)
            for (int key = 0; key < map->max_keypermod; ++key) {
                KeyCode code = map->modifiermap[mod * map->max_keypermod + key];
                if (code && (code == num || code == scroll)) locks |= 1u << mod;
            }
        XFreeModifiermap(map);
    }
    for (unsigned int mask = 0; mask < 256; ++mask)
        if (!(mask & ~locks))
            for (unsigned int wheel = 4; wheel <= 7; ++wheel)
                XUngrabButton(display, wheel, mask, window);
    return result;
}
