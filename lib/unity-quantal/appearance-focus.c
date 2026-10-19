/* Extend only the original Appearance builder, using its own GTK 3.6 widgets. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <gtk/gtk.h>

static gboolean setting(const char *operation, gint *value)
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
    if (ok && value) *value = g_str_has_prefix(output, "true") ? 1 : atoi(output);
    if (error) { g_warning("Dynamic Focus Color: %s", error->message); g_error_free(error); }
    g_free(output);
    return ok;
}

static void reload(GtkToggleButton *button)
{
    gint active, brightness;
    GtkRange *scale = g_object_get_data(G_OBJECT(button), "brightness");
    if (setting("focus-get", &active)) {
        g_object_set_data(G_OBJECT(button), "updating", GINT_TO_POINTER(1));
        gtk_toggle_button_set_active(button, active);
        gtk_widget_set_sensitive(GTK_WIDGET(scale), active);
        g_object_set_data(G_OBJECT(button), "updating", NULL);
    }
    if (setting("focus-brightness", &brightness)) {
        g_object_set_data(G_OBJECT(scale), "updating", GINT_TO_POINTER(1));
        gtk_range_set_value(scale, brightness);
        g_object_set_data(G_OBJECT(scale), "updating", NULL);
    }
}

static gboolean save_brightness(gpointer data)
{
    GtkRange *scale = data;
    g_object_set_data(G_OBJECT(scale), "pending", NULL);
    char *operation = g_strdup_printf("focus-brightness=%.0f", gtk_range_get_value(scale));
    setting(operation, NULL);
    g_free(operation);
    return FALSE;
}

static void brightness_changed(GtkRange *scale, gpointer unused)
{
    (void)unused;
    if (g_object_get_data(G_OBJECT(scale), "updating")) return;
    guint pending = GPOINTER_TO_UINT(g_object_get_data(G_OBJECT(scale), "pending"));
    if (pending) g_source_remove(pending);
    pending = g_timeout_add(300, save_brightness, scale);
    g_object_set_data(G_OBJECT(scale), "pending", GUINT_TO_POINTER(pending));
}

static void finish_brightness(GtkWidget *scale, gpointer unused)
{
    (void)unused;
    guint pending = GPOINTER_TO_UINT(g_object_get_data(G_OBJECT(scale), "pending"));
    if (pending) {
        g_source_remove(pending);
        save_brightness(scale);
    }
}

static gchar *format_brightness(GtkScale *scale, gdouble value, gpointer unused)
{
    (void)scale; (void)unused;
    return g_strdup_printf("%.0f%%", value);
}

static void toggled(GtkToggleButton *button, gpointer unused)
{
    (void)unused;
    if (g_object_get_data(G_OBJECT(button), "updating")) return;
    if (!setting(gtk_toggle_button_get_active(button) ? "focus-on" : "focus-off", NULL))
        reload(button);
    else
        gtk_widget_set_sensitive(g_object_get_data(G_OBJECT(button), "brightness"),
                                 gtk_toggle_button_get_active(button));
}

static void changed(GFileMonitor *monitor, GFile *file, GFile *other,
                    GFileMonitorEvent event, GtkToggleButton *button)
{
    (void)monitor; (void)file; (void)other; (void)event;
    GtkRange *scale = g_object_get_data(G_OBJECT(button), "brightness");
    if (!g_object_get_data(G_OBJECT(scale), "pending"))
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
    gtk_widget_set_tooltip_text(button, "Use the wallpaper color for orange highlights, controls and icons");
    GtkWidget *row = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 12);
    gtk_widget_set_name(row, "unity-dynamic-focus-row");
    gtk_widget_set_margin_left(row, 12);
    gtk_widget_set_margin_right(row, 12);
    gtk_widget_set_margin_bottom(row, 8);
    GtkWidget *scale = gtk_scale_new_with_range(GTK_ORIENTATION_HORIZONTAL, 25, 150, 1);
    gtk_widget_set_name(scale, "unity-focus-brightness");
    gtk_widget_set_tooltip_text(scale, "Focus color brightness");
    atk_object_set_name(gtk_widget_get_accessible(scale), "Focus color brightness");
    gtk_scale_set_value_pos(GTK_SCALE(scale), GTK_POS_RIGHT);
    gtk_scale_add_mark(GTK_SCALE(scale), 100, GTK_POS_BOTTOM, NULL);
    gtk_widget_set_size_request(scale, 160, -1);
    g_object_set_data(G_OBJECT(button), "brightness", scale);
    g_signal_connect(scale, "format-value", G_CALLBACK(format_brightness), NULL);
    g_signal_connect(scale, "value-changed", G_CALLBACK(brightness_changed), NULL);
    g_signal_connect(scale, "destroy", G_CALLBACK(finish_brightness), NULL);
    gtk_box_pack_start(GTK_BOX(row), button, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(row), scale, TRUE, TRUE, 0);
    reload(GTK_TOGGLE_BUTTON(button));
    g_signal_connect(button, "toggled", G_CALLBACK(toggled), NULL);
    gtk_box_pack_start(GTK_BOX(object), row, FALSE, FALSE, 0);
    gtk_box_reorder_child(GTK_BOX(object), row, 3);
    gtk_widget_show_all(row);
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
