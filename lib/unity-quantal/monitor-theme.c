/* Quantal's graph painter hard-codes white/black. Limit palette substitution
 * to its exported draw_background function, preserving plot/user colours and
 * every other Cairo caller. GTK/Cairo resolve from the original process. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <gtk/gtk.h>
#include <string.h>
#include <stdlib.h>

static GdkColor graph_base, graph_text;
static gboolean graph_style;

static gboolean graph_caller(void *address)
{
    Dl_info info;
    return dladdr(address, &info) && info.dli_sname &&
        strcmp(info.dli_sname, "_Z15draw_backgroundP9LoadGraph") == 0;
}

GtkStyle *gtk_widget_get_style(GtkWidget *widget)
{
    GtkStyle *(*original)(GtkWidget *) = dlsym(RTLD_NEXT, "gtk_widget_get_style");
    GtkStyle *style = original(widget);
    if (graph_caller(__builtin_return_address(0))) {
        graph_base = style->base[GTK_STATE_NORMAL];
        graph_text = style->fg[GTK_STATE_NORMAL];
        graph_style = TRUE;
    }
    return style;
}

void cairo_set_source_rgb(cairo_t *cr, double r, double g, double b)
{
    void (*original)(cairo_t *, double, double, double) = dlsym(RTLD_NEXT, "cairo_set_source_rgb");
    if (graph_style && graph_caller(__builtin_return_address(0)) && r == 1 && g == 1 && b == 1) {
        r = graph_base.red / 65535.0;
        g = graph_base.green / 65535.0;
        b = graph_base.blue / 65535.0;
    }
    original(cr, r, g, b);
}

void cairo_set_source_rgba(cairo_t *cr, double r, double g, double b, double a)
{
    void (*original)(cairo_t *, double, double, double, double) = dlsym(RTLD_NEXT, "cairo_set_source_rgba");
    if (graph_style && graph_caller(__builtin_return_address(0)) && r == 0 && g == 0 && b == 0 && a == 0.75) {
        r = graph_text.red / 65535.0;
        g = graph_text.green / 65535.0;
        b = graph_text.blue / 65535.0;
        a = 0.22;
    }
    original(cr, r, g, b, a);
}

static void graph_style_updated(GtkWidget *widget, gpointer unused)
{
    (void)unused;
    if (!gtk_widget_get_realized(widget))
        return;
    /* The original configure handler clears the cached graph background. */
    GdkEventConfigure event = { .type = GDK_CONFIGURE };
    gboolean handled = FALSE;
    g_signal_emit_by_name(widget, "configure-event", &event, &handled);
    gtk_widget_queue_draw(widget);
}

GtkWidget *gtk_drawing_area_new(void)
{
    GtkWidget *(*original)(void) = dlsym(RTLD_NEXT, "gtk_drawing_area_new");
    GtkWidget *widget = original();
    Dl_info info;
    if (dladdr(__builtin_return_address(0), &info) && info.dli_sname &&
        strncmp(info.dli_sname, "_ZN9LoadGraphC", sizeof("_ZN9LoadGraphC") - 1) == 0)
        g_signal_connect(widget, "style-updated", G_CALLBACK(graph_style_updated), NULL);
    return widget;
}

static gboolean sidebar_draw(GtkWidget *widget, cairo_t *cr, gpointer data)
{
    GdkPixbuf *logo = data;
    GtkWidget *notebook = gtk_widget_get_ancestor(widget, GTK_TYPE_NOTEBOOK);
    GtkStyle *style = gtk_widget_get_style(notebook ? notebook : widget);
    gdk_cairo_set_source_color(cr, &style->bg[GTK_STATE_NORMAL]);
    cairo_rectangle(cr, 5, 12, 92, 351);
    cairo_fill(cr);
    cairo_pattern_t *gradient = cairo_pattern_create_linear(0, 12, 0, 363);
    cairo_pattern_add_color_stop_rgba(gradient, 0, 0.322, 0.467, 0.765, 0.25);
    cairo_pattern_add_color_stop_rgba(gradient, 1, 0.494, 0.729, 0.894, 0.04);
    cairo_set_source(cr, gradient);
    cairo_rectangle(cr, 5, 12, 92, 351);
    cairo_fill(cr);
    cairo_pattern_destroy(gradient);
    if (logo) {
        gdk_cairo_set_source_pixbuf(cr, logo, 15, 30);
        cairo_paint(cr);
    }
    return TRUE; /* Replace both the Ubuntu bitmap and its orange draw handler. */
}

static void logo_free(gpointer logo)
{
    /* Keep GTK symbols lazy: lsb_release inherits LD_PRELOAD without GTK. */
    g_object_unref(logo);
}

GtkWidget *gtk_image_new_from_file(const gchar *filename)
{
    GtkWidget *(*original)(const gchar *) = dlsym(RTLD_NEXT, "gtk_image_new_from_file");
    if (!filename || !g_str_has_suffix(filename, "/gnome-system-monitor/side.png"))
        return original(filename);
    GdkPixbuf *blank = gdk_pixbuf_new(GDK_COLORSPACE_RGB, TRUE, 8, 92, 351);
    gdk_pixbuf_fill(blank, 0);
    GtkWidget *widget = gtk_image_new_from_pixbuf(blank);
    g_object_unref(blank);
    const char *path = getenv("UNITY_MONITOR_LOGO");
    GdkPixbuf *logo = path ? gdk_pixbuf_new_from_file(path, NULL) : NULL;
    if (logo)
        g_object_set_data_full(G_OBJECT(widget), "nixos-logo", logo, logo_free);
    g_signal_connect(widget, "draw", G_CALLBACK(sidebar_draw), logo);
    return widget;
}

GtkWidget *gtk_label_new(const gchar *text)
{
    GtkWidget *(*original)(const gchar *) = dlsym(RTLD_NEXT, "gtk_label_new");
    /* The System page otherwise reports the ISO's GNOME version as the desktop. */
    return original(text && g_str_has_prefix(text, "GNOME ") ? "Unity 6.8" : text);
}
