/* Extend only the original Appearance builder, using its own GTK 3.6 widgets. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <gtk/gtk.h>

static gboolean setting(const char *operation, gboolean *active)
{
    const char *script = g_getenv("UNITY_FOCUS_SETTINGS");
    if (!script) return FALSE;
    char *argv[] = { "/usr/bin/python2.7", (char *)script, (char *)operation, NULL };
    char *output = NULL;
    GError *error = NULL;
    gint status = 0;
    gchar **environment = g_get_environ();
    environment = g_environ_unsetenv(environment, "LD_PRELOAD");
    gboolean ok = g_spawn_sync(NULL, argv, environment, 0, NULL, NULL, &output, NULL, &status, &error);
    g_strfreev(environment);
    if (ok) ok = g_spawn_check_exit_status(status, &error);
    if (ok && active) *active = g_str_has_prefix(output, "true");
    if (error) { g_warning("Dynamic Focus Color: %s", error->message); g_error_free(error); }
    g_free(output);
    return ok;
}

static void reload(GtkToggleButton *button)
{
    gboolean active;
    if (setting("focus-get", &active)) {
        g_object_set_data(G_OBJECT(button), "updating", GINT_TO_POINTER(1));
        gtk_toggle_button_set_active(button, active);
        g_object_set_data(G_OBJECT(button), "updating", NULL);
    }
}

static void toggled(GtkToggleButton *button, gpointer unused)
{
    (void)unused;
    if (g_object_get_data(G_OBJECT(button), "updating")) return;
    if (!setting(gtk_toggle_button_get_active(button) ? "focus-on" : "focus-off", NULL))
        reload(button);
}

static void changed(GFileMonitor *monitor, GFile *file, GFile *other,
                    GFileMonitorEvent event, GtkToggleButton *button)
{
    (void)monitor; (void)file; (void)other; (void)event;
    reload(button);
}

static void release_monitor(gpointer monitor)
{
    g_file_monitor_cancel(monitor);
    g_object_unref(monitor);
}

GObject *gtk_builder_get_object(GtkBuilder *builder, const gchar *name)
{
    GObject *(*original)(GtkBuilder *, const gchar *) = dlsym(RTLD_NEXT, "gtk_builder_get_object");
    GObject *result = original(builder, name);
    GObject *object = original(builder, "background-panel");
    if (!GTK_IS_BOX(object) ||
        !original(builder, "theme-selector") ||
        g_object_get_data(object, "unity-focus-installed")) return result;
    g_object_set_data(object, "unity-focus-installed", GINT_TO_POINTER(1));
    GtkWidget *button = gtk_check_button_new_with_label("Dynamic Focus Color");
    gtk_widget_set_name(button, "unity-dynamic-focus-color");
    gtk_widget_set_tooltip_text(button, "Use the wallpaper color for focus and selection in Ambiance or Radiance");
    gtk_widget_set_margin_left(button, 12);
    gtk_widget_set_margin_bottom(button, 8);
    reload(GTK_TOGGLE_BUTTON(button));
    g_signal_connect(button, "toggled", G_CALLBACK(toggled), NULL);
    gtk_box_pack_start(GTK_BOX(object), button, FALSE, FALSE, 0);
    gtk_box_reorder_child(GTK_BOX(object), button, 3);
    gtk_widget_show(button);
    char *path = g_build_filename(g_get_user_config_dir(), "unity-quantal", NULL);
    GFile *directory = g_file_new_for_path(path);
    GFileMonitor *monitor = g_file_monitor_directory(directory, G_FILE_MONITOR_NONE, NULL, NULL);
    if (monitor) {
        g_signal_connect_object(monitor, "changed", G_CALLBACK(changed), button, 0);
        g_object_set_data_full(G_OBJECT(button), "monitor", monitor, release_monitor);
    }
    g_object_unref(directory);
    g_free(path);
    return result;
}
