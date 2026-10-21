/* Unity 6's Dash buttons and switcher outline bypass panel::Style.
 * Redirect only these assets at the shared PNG file-loading boundary. Panel
 * style changes already reload buttons; each switcher show creates its view.
 * Compiz does not load GTK. Read the theme through the runtime's GSettings,
 * resolving its entry points only after the session plugins have loaded GIO.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <gio/gio.h>
#include <stdio.h>
#include <string.h>

static __thread int resolving;

static gchar *themed_path(const char *path)
{
    const char *prefix = "/usr/share/unity/6/";
    if (resolving || !path || strncmp(path, prefix, strlen(prefix))) return NULL;
    const char *name = path + strlen(prefix);
    if (strcmp(name, "close_dash.png") && strcmp(name, "close_dash_prelight.png") &&
        strcmp(name, "close_dash_pressed.png") && strcmp(name, "close_dash_disabled.png") &&
        strcmp(name, "switcher_round_rect.png")) return NULL;
    resolving = 1;
    GSettings *(*settings_new)(const gchar *) = dlsym(RTLD_DEFAULT, "g_settings_new");
    gchar *(*settings_string)(GSettings *, const gchar *) = dlsym(RTLD_DEFAULT, "g_settings_get_string");
    void (*object_unref)(gpointer) = dlsym(RTLD_DEFAULT, "g_object_unref");
    gchar *theme = NULL, *result = NULL;
    if (settings_new && settings_string && object_unref) {
        GSettings *settings = settings_new("org.gnome.desktop.interface");
        theme = settings_string(settings, "gtk-theme");
        object_unref(settings);
    }
    if (theme && g_str_has_prefix(theme, "Unity-Focus-") && !strchr(theme, '/')) {
        result = g_build_filename(g_get_home_dir(), ".themes", theme, "unity-shell", name, NULL);
        if (!g_file_test(result, G_FILE_TEST_IS_REGULAR)) {
            g_free(result);
            result = NULL;
        }
    }
    g_free(theme);
    resolving = 0;
    return result;
}

FILE *fopen(const char *path, const char *mode)
{
    FILE *(*original)(const char *, const char *) = dlsym(RTLD_NEXT, "fopen");
    gchar *replacement = mode && mode[0] == 'r' ? themed_path(path) : NULL;
    FILE *result = original(replacement ? replacement : path, mode);
    if (replacement) g_free(replacement);
    return result;
}

FILE *fopen64(const char *path, const char *mode)
{
    FILE *(*original)(const char *, const char *) = dlsym(RTLD_NEXT, "fopen64");
    gchar *replacement = mode && mode[0] == 'r' ? themed_path(path) : NULL;
    FILE *result = original(replacement ? replacement : path, mode);
    if (replacement) g_free(replacement);
    return result;
}
