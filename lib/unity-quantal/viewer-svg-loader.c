#define GDK_PIXBUF_ENABLE_BACKEND
#include <gdk-pixbuf/gdk-pixbuf-io.h>
#include <librsvg/rsvg.h>
typedef struct {
    RsvgHandle *svg;
    GdkPixbufModuleSizeFunc size;
    GdkPixbufModulePreparedFunc prepared;
    GdkPixbufModuleUpdatedFunc updated;
    gpointer user;
} Load;
static gpointer begin(GdkPixbufModuleSizeFunc size, GdkPixbufModulePreparedFunc prepared,
                      GdkPixbufModuleUpdatedFunc updated, gpointer user, GError **error) {
    (void)error;
    Load *load = g_new0(Load, 1);
    load->svg = rsvg_handle_new(); load->size = size;
    load->prepared = prepared; load->updated = updated; load->user = user;
    return load;
}
static gboolean increment(gpointer pointer, const guchar *bytes, guint count, GError **error) {
    Load *load = pointer;
    return rsvg_handle_write(load->svg, bytes, count, error);
}
static gboolean stop(gpointer pointer, GError **error) {
    Load *load = pointer;
    gboolean ok = rsvg_handle_close(load->svg, error);
    if (ok) {
        GdkPixbuf *pixbuf = rsvg_handle_get_pixbuf(load->svg);
        int width = gdk_pixbuf_get_width(pixbuf), height = gdk_pixbuf_get_height(pixbuf);
        if (load->size) load->size(&width, &height, load->user);
        if (width > 32767 || height > 32767 ||
            (width > 0 && height > 0 && (guint64)width*height > 64*1024*1024)) {
            g_set_error_literal(error, GDK_PIXBUF_ERROR, GDK_PIXBUF_ERROR_INSUFFICIENT_MEMORY, "SVG thumbnail exceeds the rendering limit");
            g_object_unref(pixbuf);
            g_object_unref(load->svg); g_free(load);
            return FALSE;
        }
        if (width > 0 && height > 0 && (width != gdk_pixbuf_get_width(pixbuf) || height != gdk_pixbuf_get_height(pixbuf))) {
            GdkPixbuf *scaled = gdk_pixbuf_scale_simple(pixbuf, width, height, GDK_INTERP_BILINEAR);
            g_object_unref(pixbuf); pixbuf = scaled;
        }
        if (pixbuf && width > 0 && height > 0) {
            if (load->prepared) load->prepared(pixbuf, NULL, load->user);
            if (load->updated) load->updated(pixbuf, 0, 0, width, height, load->user);
        }
        g_clear_object(&pixbuf);
    }
    g_object_unref(load->svg); g_free(load);
    return ok;
}
G_MODULE_EXPORT void fill_vtable(GdkPixbufModule *module) {
    module->begin_load = begin; module->load_increment = increment; module->stop_load = stop;
}
G_MODULE_EXPORT void fill_info(GdkPixbufFormat *info) {
    static GdkPixbufModulePattern signatures[] = {{" <svg", "*    ", 100}, {" <!DOCTYPE svg", "*             ", 100}, {NULL,NULL,0}};
    static char *mimes[] = {"image/svg+xml", "image/svg", "image/svg-xml", "image/vnd.adobe.svg+xml", "text/xml-svg", "image/svg+xml-compressed", NULL};
    static char *extensions[] = {"svg", "svgz", "svg.gz", NULL};
    info->name = "svg"; info->signature = signatures; info->description = "SVG (isolated renderer)";
    info->mime_types = mimes; info->extensions = extensions;
    info->flags = GDK_PIXBUF_FORMAT_SCALABLE | GDK_PIXBUF_FORMAT_THREADSAFE;
    info->license = "GPL";
}
