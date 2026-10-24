/* Included in bubble.c: retain Notify OSD rendering, add optional interaction. */
static gboolean click_through(void)
{
    static gint64 checked;
    static gboolean enabled;
    gint64 now = g_get_monotonic_time();
    if (!checked || now - checked > G_USEC_PER_SEC) {
        GKeyFile *settings = g_key_file_new();
        char *path = g_build_filename(g_get_user_config_dir(), "unity-quantal", "notifications.ini", NULL);
        enabled = g_key_file_load_from_file(settings, path, G_KEY_FILE_NONE, NULL)
            && g_key_file_get_boolean(settings, "Notifications", "click-through", NULL);
        g_free(path);
        g_key_file_free(settings);
        checked = now;
    }
    return enabled;
}

static gboolean interactive(Bubble *bubble)
{
    return !bubble_is_synchronous(bubble) && !click_through();
}

static void close_center(Bubble *bubble, double *x, double *y)
{
    Defaults *d = bubble->defaults;
    double shadow = EM2PIXELS(defaults_get_bubble_shadow_size(d), d);
    *x = gtk_widget_get_allocated_width(GET_PRIVATE(bubble)->widget) - shadow - 14;
    *y = shadow + 14;
}

static gboolean clicked(GtkWidget *window, GdkEventButton *event, gpointer data)
{
    Bubble *bubble = data;
    if (event->button != 1 || !interactive(bubble)) return FALSE;
    double x, y;
    close_center(bubble, &x, &y);
    gboolean close = fabs(event->x - x) <= 12 && fabs(event->y - y) <= 12;
    const char *action = g_object_get_data(G_OBJECT(bubble), "default-action");
    if (!close && !action) return TRUE;
    g_object_ref(bubble);
    if (!close)
        dbus_send_action_signal(bubble_get_sender(bubble), bubble_get_id(bubble), action);
    bubble_clear_timer(bubble);
    bubble_hide(bubble);
    dbus_send_close_signal(bubble_get_sender(bubble), bubble_get_id(bubble), 2);
    g_signal_emit(bubble, g_bubble_signals[TIMED_OUT], 0);
    g_object_unref(bubble);
    return TRUE;
}

static void draw_close(Bubble *bubble, cairo_t *cr)
{
    if (!interactive(bubble)) return;
    double x, y;
    close_center(bubble, &x, &y);
    cairo_set_source_rgba(cr, 1, 1, 1, .85);
    cairo_set_line_width(cr, 1.5);
    cairo_move_to(cr, x - 4, y - 4);
    cairo_line_to(cr, x + 4, y + 4);
    cairo_move_to(cr, x + 4, y - 4);
    cairo_line_to(cr, x - 4, y + 4);
    cairo_stroke(cr);
}
