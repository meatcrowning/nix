#include <gtk/gtk.h>
#include <math.h>

/* Match the original executable's exported call site, not arbitrary Cairo. */
void graph_paint(GtkWidget *widget, cairo_t *cr, int grid)
    __asm__("_Z15draw_backgroundP9LoadGraph");
void graph_paint(GtkWidget *widget, cairo_t *cr, int grid)
{
    gtk_widget_get_style(widget);
    if (grid)
        cairo_set_source_rgba(cr, 0, 0, 0, 0.75);
    else
        cairo_set_source_rgb(cr, 1, 1, 1);
}

static void check_color(cairo_t *cr, GdkColor color, double alpha)
{
    double r, g, b, a;
    g_assert_cmpint(cairo_pattern_get_rgba(cairo_get_source(cr), &r, &g, &b, &a), ==, CAIRO_STATUS_SUCCESS);
    g_assert(fabs(r - color.red / 65535.0) < 0.001);
    g_assert(fabs(g - color.green / 65535.0) < 0.001);
    g_assert(fabs(b - color.blue / 65535.0) < 0.001);
    g_assert(fabs(a - alpha) < 0.001);
}

int main(int argc, char **argv)
{
    gtk_init(&argc, &argv);
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    GtkWidget *notebook = gtk_notebook_new();
    gtk_container_add(GTK_CONTAINER(window), notebook);
    gtk_widget_show_all(window);
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 102, 375);
    cairo_t *cr = cairo_create(surface);
    for (int dark = 0; dark < 2; dark++) {
        GtkCssProvider *provider = gtk_css_provider_new();
        gtk_css_provider_load_from_data(provider, dark ?
            "* { background-color: #20252a; color: #eeeeee; }" :
            "* { background-color: #e6e9ec; color: #222222; }", -1, NULL);
        gtk_style_context_add_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_USER);
        for (int frame = 0; frame < 20; frame++) {
            while (gtk_events_pending()) gtk_main_iteration();
            g_usleep(10000);
        }
        GtkStyle *style = gtk_widget_get_style(notebook);
        if (dark)
            g_assert_cmpuint(style->base[GTK_STATE_NORMAL].red, <, 32768);
        else
            g_assert_cmpuint(style->base[GTK_STATE_NORMAL].red, >, 32768);
        graph_paint(notebook, cr, 0);
        check_color(cr, style->base[GTK_STATE_NORMAL], 1);
        graph_paint(notebook, cr, 1);
        check_color(cr, style->fg[GTK_STATE_NORMAL], .22);
        /* White outside the graph painter must stay white. */
        cairo_set_source_rgb(cr, 1, 1, 1);
        GdkColor white = {0, 65535, 65535, 65535};
        check_color(cr, white, 1);
        gtk_style_context_remove_provider_for_screen(gdk_screen_get_default(), GTK_STYLE_PROVIDER(provider));
        g_object_unref(provider);
    }
    GtkWidget *label = gtk_label_new("GNOME 3.6.0");
    g_assert_cmpstr(gtk_label_get_text(GTK_LABEL(label)), ==, "Unity 6.8");
    gtk_widget_destroy(label);
    gchar *heading = g_strdup_printf("<big><big><b><u>%s</u></b></big></big>", g_get_host_name());
    GtkWidget *frame = gtk_frame_new(heading);
    gtk_widget_show_all(frame);
    g_assert(!gtk_widget_get_visible(frame));
    gtk_widget_destroy(frame);
    g_free(heading);
    frame = gtk_frame_new("Other frame");
    gtk_widget_show_all(frame);
    g_assert(gtk_widget_get_visible(frame));
    gtk_widget_destroy(frame);
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    gtk_widget_destroy(window);
    g_print("PASS: light/dark graph palettes, theme foreground grid, unrelated Cairo colours, desktop identity\n");
    return 0;
}
