/* A content-sized, theme-rendered Rhythmbox entry in the original Unity panel.
 * The panel supplies hit testing; no pointer grabs or synthetic input. */
#include "now-playing.h"
#include <gio/gio.h>
#include <pango/pangocairo.h>
#include <math.h>

#define PLAYER "org.mpris.MediaPlayer2.unity-rhythmbox"
#define OBJECT "/org/mpris/MediaPlayer2"
#define INTERFACE "org.mpris.MediaPlayer2.Player"
#define WIDTH 248
#define HEIGHT 22
#define TEXT_X 28
#define TEXT_WIDTH (WIDTH - TEXT_X)

typedef struct {
    IndicatorObject parent;
    GtkImage *image;
    GtkMenu *menu;
    GtkWidget *heading;
    GtkStyleContext *style;
    GDBusProxy *proxy;
    GdkPixbuf *art;
    gchar *text, *art_uri;
    guint timer;
    gboolean visible, hovered;
    gint64 hover_start;
    gint last_offset;
    NowPlayingHovered hit_test;
    gpointer panel;
} NowPlaying;
typedef IndicatorObjectClass NowPlayingClass;
G_DEFINE_TYPE(NowPlaying, now_playing, INDICATOR_OBJECT_TYPE)

static PangoLayout *text_layout(NowPlaying *self)
{
    PangoLayout *layout = gtk_widget_create_pango_layout(GTK_WIDGET(self->image), self->text ? self->text : "Rhythmbox");
    pango_layout_set_font_description(layout, gtk_style_context_get_font(self->style, GTK_STATE_FLAG_NORMAL));
    pango_layout_set_single_paragraph_mode(layout, TRUE);
    return layout;
}

static void render(NowPlaying *self, gint offset)
{
    PangoLayout *layout = text_layout(self);
    gint natural_width;
    pango_layout_get_pixel_size(layout, &natural_width, NULL);
    /* Reserve the maximum only for overflowing text; hover keeps that width. */
    gint text_width = MIN(MAX(natural_width, 1), TEXT_WIDTH);
    gint width = TEXT_X + text_width;
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, width, HEIGHT);
    cairo_t *cr = cairo_create(surface);
    GdkRGBA color;
    gtk_style_context_get_color(self->style, GTK_STATE_FLAG_NORMAL, &color);
    if (self->art) {
        gint w = gdk_pixbuf_get_width(self->art), h = gdk_pixbuf_get_height(self->art);
        gdk_cairo_set_source_pixbuf(cr, self->art, (HEIGHT-w)/2., (HEIGHT-h)/2.);
        cairo_paint(cr);
    } else {
        gdk_cairo_set_source_rgba(cr, &color);
        cairo_set_line_width(cr, 1.5);
        cairo_arc(cr, 11, 11, 8, 0, 2*G_PI);
        cairo_stroke(cr);
        cairo_arc(cr, 11, 11, 2, 0, 2*G_PI);
        cairo_stroke(cr);
    }
    if (offset < 0) {
        pango_layout_set_width(layout, TEXT_WIDTH * PANGO_SCALE);
        pango_layout_set_ellipsize(layout, PANGO_ELLIPSIZE_END);
    }
    gint w, h;
    pango_layout_get_pixel_size(layout, &w, &h);
    cairo_rectangle(cr, TEXT_X, 0, text_width, HEIGHT);
    cairo_clip(cr);
    gdk_cairo_set_source_rgba(cr, &color);
    cairo_move_to(cr, TEXT_X - MAX(offset, 0), (HEIGHT-h)/2.);
    pango_cairo_show_layout(cr, layout);
    GdkPixbuf *pixels = gdk_pixbuf_get_from_surface(surface, 0, 0, width, HEIGHT);
    gtk_image_set_from_pixbuf(self->image, pixels);
    g_object_unref(pixels);
    g_object_unref(layout);
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    self->last_offset = offset;
}

static void load_art(NowPlaying *self, const gchar *uri)
{
    if (!g_strcmp0(uri, self->art_uri)) return;
    g_free(self->art_uri);
    self->art_uri = g_strdup(uri);
    g_clear_object(&self->art);
    /* Only local artwork from the existing media bridge; never fetch URLs. */
    gchar *host = NULL;
    gchar *path = uri ? g_filename_from_uri(uri, &host, NULL) : NULL;
    GFile *file = path ? g_file_new_for_path(path) : NULL;
    GFileInfo *info = file ? g_file_query_info(file, "standard::size,standard::type", G_FILE_QUERY_INFO_NONE, NULL, NULL) : NULL;
    gint w = 0, h = 0;
    if (path && (!host || !*host || !g_strcmp0(host, "localhost")) &&
        info && g_file_info_get_file_type(info) == G_FILE_TYPE_REGULAR &&
        g_file_info_get_size(info) <= 16*1024*1024 &&
        gdk_pixbuf_get_file_info(path, &w, &h) && w > 0 && h > 0 && w <= 8192 && h <= 8192)
        self->art = gdk_pixbuf_new_from_file_at_scale(path, HEIGHT, HEIGHT, TRUE, NULL);
    g_clear_object(&info);
    g_clear_object(&file);
    g_free(host);
    g_free(path);
}

static void update(NowPlaying *self)
{
    gchar *owner = g_dbus_proxy_get_name_owner(self->proxy);
    gboolean visible = owner != NULL;
    g_free(owner);
    GVariant *metadata = g_dbus_proxy_get_cached_property(self->proxy, "Metadata");
    const gchar *title = NULL, *uri = NULL;
    if (metadata && g_variant_is_of_type(metadata, G_VARIANT_TYPE("a{sv}"))) {
        g_variant_lookup(metadata, "xesam:title", "&s", &title);
        g_variant_lookup(metadata, "mpris:artUrl", "&s", &uri);
    }
    gchar *text = g_strdup(title && *title ? title : "Rhythmbox");
    if (g_strcmp0(text, self->text) || g_strcmp0(uri, self->art_uri) || visible != self->visible) {
        g_free(self->text);
        self->text = g_strdup(text);
        load_art(self, uri);
        self->hover_start = g_get_monotonic_time();
        render(self, -1);
        gtk_menu_item_set_label(GTK_MENU_ITEM(self->heading), text);
        /* Keep the full title available to accessibility clients. */
        GList *entries = indicator_object_get_entries(INDICATOR_OBJECT(self));
        for (GList *it = entries; it; it = it->next) {
            IndicatorObjectEntry *entry = it->data;
            entry->accessible_desc = self->text;
            g_signal_emit_by_name(self, INDICATOR_OBJECT_SIGNAL_ACCESSIBLE_DESC_UPDATE, entry);
        }
        g_list_free(entries);
    }
    if (visible != self->visible) {
        self->visible = visible;
        indicator_object_set_visible(INDICATOR_OBJECT(self), visible);
    }
    g_free(text);
    if (metadata) g_variant_unref(metadata);
}

static void changed(GDBusProxy *proxy, GVariant *values, gchar **invalidated, gpointer data)
{ (void)proxy; (void)values; (void)invalidated; update(data); }
static void owner_changed(GObject *proxy, GParamSpec *spec, gpointer data)
{ (void)proxy; (void)spec; update(data); }

static gboolean tick(gpointer data)
{
    NowPlaying *self = data;
    gboolean hovered = self->visible && self->hit_test && self->hit_test(self->panel, INDICATOR_OBJECT(self));
    gint64 now = g_get_monotonic_time();
    if (hovered != self->hovered) {
        self->hovered = hovered;
        self->hover_start = now;
    }
    gint offset = -1;
    if (hovered && now - self->hover_start > 700000) {
        PangoLayout *layout = text_layout(self);
        gint width;
        pango_layout_get_pixel_size(layout, &width, NULL);
        g_object_unref(layout);
        if (width > TEXT_WIDTH) {
            /* Read through once, pause at the end, then repeat while hovered. */
            double distance = width - TEXT_WIDTH;
            double elapsed = (now - self->hover_start - 700000) / 1000000.;
            double phase = fmod(elapsed, distance / 32. + 2.);
            offset = MIN(distance, phase * 32.);
        }
    }
    if (offset != self->last_offset) render(self, offset);
    return TRUE;
}

static void ready(GObject *source, GAsyncResult *result, gpointer data)
{
    (void)source;
    NowPlaying *self = data;
    self->proxy = g_dbus_proxy_new_for_bus_finish(result, NULL);
    if (self->proxy) {
        g_signal_connect(self->proxy, "g-properties-changed", G_CALLBACK(changed), self);
        g_signal_connect(self->proxy, "notify::g-name-owner", G_CALLBACK(owner_changed), self);
        update(self);
    }
    g_object_unref(self);
}
static GtkImage *get_image(IndicatorObject *object) { return ((NowPlaying *)object)->image; }
static GtkMenu *get_menu(IndicatorObject *object) { return ((NowPlaying *)object)->menu; }
static const gchar *get_desc(IndicatorObject *object) { return ((NowPlaying *)object)->text; }
static void open_player(GtkMenuItem *item, gpointer data)
{
    (void)item;
    NowPlaying *self = data;
    if (self->proxy && self->visible)
        g_dbus_connection_call(g_dbus_proxy_get_connection(self->proxy), PLAYER, OBJECT,
            "org.mpris.MediaPlayer2", "Raise", NULL, NULL, G_DBUS_CALL_FLAGS_NO_AUTO_START, 2000, NULL, NULL, NULL);
}
static void style_changed(GtkStyleContext *style, gpointer data)
{ (void)style; render(data, -1); }
static void dispose(GObject *object)
{
    NowPlaying *self = (NowPlaying *)object;
    if (self->timer) { g_source_remove(self->timer); self->timer = 0; }
    g_clear_object(&self->proxy);
    G_OBJECT_CLASS(now_playing_parent_class)->dispose(object);
}
static void finalize(GObject *object)
{
    NowPlaying *self = (NowPlaying *)object;
    g_clear_object(&self->art);
    g_clear_object(&self->style);
    g_free(self->text);
    g_free(self->art_uri);
    G_OBJECT_CLASS(now_playing_parent_class)->finalize(object);
}
static void now_playing_class_init(NowPlayingClass *klass)
{
    klass->get_image = get_image;
    klass->get_menu = get_menu;
    klass->get_accessible_desc = get_desc;
    G_OBJECT_CLASS(klass)->dispose = dispose;
    G_OBJECT_CLASS(klass)->finalize = finalize;
}
static void now_playing_init(NowPlaying *self)
{
    self->image = GTK_IMAGE(gtk_image_new());
    self->menu = GTK_MENU(gtk_menu_new());
    self->heading = gtk_menu_item_new_with_label("Rhythmbox");
    gtk_widget_set_sensitive(self->heading, FALSE);
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), self->heading);
    GtkWidget *open = gtk_menu_item_new_with_label("Open Rhythmbox");
    g_signal_connect(open, "activate", G_CALLBACK(open_player), self);
    gtk_menu_shell_append(GTK_MENU_SHELL(self->menu), open);
    gtk_widget_show_all(GTK_WIDGET(self->menu));
    gtk_widget_show(GTK_WIDGET(self->image));
    self->style = gtk_style_context_new();
    GtkWidgetPath *path = gtk_widget_path_new();
    gtk_widget_path_append_type(path, GTK_TYPE_WINDOW);
    gtk_widget_path_iter_set_name(path, -1, "UnityPanelWidget");
    gtk_style_context_set_path(self->style, path);
    gtk_style_context_add_class(self->style, "gnome-panel-menu-bar");
    gtk_style_context_add_class(self->style, "unity-panel");
    gtk_widget_path_free(path);
    self->text = g_strdup("Rhythmbox");
    g_signal_connect(self->style, "changed", G_CALLBACK(style_changed), self);
    render(self, -1);
    g_object_set(self, INDICATOR_OBJECT_DEFAULT_VISIBILITY, FALSE, NULL);
    g_dbus_proxy_new_for_bus(G_BUS_TYPE_SESSION, G_DBUS_PROXY_FLAGS_DO_NOT_AUTO_START,
        NULL, PLAYER, OBJECT, INTERFACE, NULL, ready, g_object_ref(self));
    self->timer = g_timeout_add(80, tick, self);
}
IndicatorObject *now_playing_new(NowPlayingHovered hovered, gpointer panel)
{
    NowPlaying *self = g_object_new(now_playing_get_type(), NULL);
    self->hit_test = hovered;
    self->panel = panel;
    return INDICATOR_OBJECT(self);
}
