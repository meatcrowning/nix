/* Original EOG's small RsvgHandle API, backed by a disposable renderer.
 * Only checked, fixed-layout pixels cross back into the historical font stack. */
#include <glib-object.h>
#include <gio/gio.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <cairo.h>
#include <stdint.h>
#include <math.h>
#include <signal.h>
#include <pthread.h>

typedef struct { GObject parent; GByteArray *data; GdkPixbuf *pixbuf; GdkPixbuf *scaled; } RsvgHandle;
typedef struct { GObjectClass parent; } RsvgHandleClass;
G_DEFINE_TYPE(RsvgHandle, rsvg_handle, G_TYPE_OBJECT)
static void rsvg_handle_finalize(GObject *object) {
    RsvgHandle *self = (RsvgHandle *)object;
    g_byte_array_unref(self->data);
    g_clear_object(&self->pixbuf);
    g_clear_object(&self->scaled);
    G_OBJECT_CLASS(rsvg_handle_parent_class)->finalize(object);
}
static void rsvg_handle_class_init(RsvgHandleClass *klass) {
    G_OBJECT_CLASS(klass)->finalize = rsvg_handle_finalize;
}
static void rsvg_handle_init(RsvgHandle *self) { self->data = g_byte_array_new(); }
RsvgHandle *rsvg_handle_new(void) { return g_object_new(rsvg_handle_get_type(), NULL); }
void rsvg_handle_set_base_uri(RsvgHandle *self, const char *uri) { (void)self; (void)uri; }
gboolean rsvg_handle_write(RsvgHandle *self, const guchar *data, gsize length, GError **error) {
    if (length > 32*1024*1024 - self->data->len) {
        g_set_error_literal(error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA, "SVG exceeds the rendering limit");
        return FALSE;
    }
    g_byte_array_append(self->data, data, length);
    return TRUE;
}
typedef struct { GOutputStream *stream; GByteArray *data; } Input;
static gpointer send_input(gpointer pointer) {
    sigset_t signals;
    sigemptyset(&signals); sigaddset(&signals, SIGPIPE);
    pthread_sigmask(SIG_BLOCK, &signals, NULL);
    Input *input = pointer;
    g_output_stream_write_all(input->stream, input->data->data, input->data->len, NULL, NULL, NULL);
    g_output_stream_close(input->stream, NULL, NULL);
    return NULL;
}
static gboolean receive(GInputStream *stream, void *buffer, gsize length) {
    gsize received = 0;
    return g_input_stream_read_all(stream, buffer, length, &received, NULL, NULL) && received == length;
}
static GdkPixbuf *render(RsvgHandle *self, int width, int height, GError **error) {
    GdkPixbuf *candidates[] = { self->pixbuf, self->scaled };
    for (guint i = 0; i < G_N_ELEMENTS(candidates); i++)
        if (candidates[i] && width == gdk_pixbuf_get_width(candidates[i]) && height == gdk_pixbuf_get_height(candidates[i]))
            return g_object_ref(candidates[i]);
    char w[32], h[32];
    g_snprintf(w, sizeof w, "%d", width); g_snprintf(h, sizeof h, "%d", height);
    GSubprocess *process = g_subprocess_new(G_SUBPROCESS_FLAGS_STDIN_PIPE | G_SUBPROCESS_FLAGS_STDOUT_PIPE,
                                           error, SVG_WORKER, w, h, NULL);
    if (!process) return NULL;
    Input input = {g_subprocess_get_stdin_pipe(process), self->data};
    GThread *writer = g_thread_new("svg-input", send_input, &input);
    GInputStream *stream = g_subprocess_get_stdout_pipe(process);
    guint32 header[3];
    guint32 *pixels = NULL;
    gboolean ok = receive(stream, header, sizeof header) && header[0] == 0x31564753 &&
        header[1] && header[2] && header[1] <= 32767 && header[2] <= 32767 &&
        (guint64)header[1]*header[2] <= 64*1024*1024;
    if (ok) {
        gsize size = (gsize)header[1]*header[2]*4;
        pixels = g_try_malloc(size);
        ok = pixels && receive(stream, pixels, size);
    }
    /* Bound output before allocating, even if the decoder is compromised.
     * There is exactly one response; kill its namespace after receiving it. */
    g_subprocess_force_exit(process);
    g_subprocess_wait(process, NULL, NULL);
    g_thread_join(writer);
    g_object_unref(process);
    if (!ok) {
        g_free(pixels);
        g_set_error_literal(error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA, "SVG rendering failed");
        return NULL;
    }
    GdkPixbuf *pixbuf = gdk_pixbuf_new(GDK_COLORSPACE_RGB, TRUE, 8, header[1], header[2]);
    if (pixbuf) {
        for (guint y = 0; y < header[2]; y++) {
            guchar *dst = gdk_pixbuf_get_pixels(pixbuf) + (gsize)y*gdk_pixbuf_get_rowstride(pixbuf);
            const guint32 *src = pixels + (gsize)y*header[1];
            for (guint x = 0; x < header[1]; x++, dst += 4) {
                guint p = src[x], a = p >> 24;
                dst[0] = a ? MIN(255, ((p >> 16)&255)*255/a) : 0;
                dst[1] = a ? MIN(255, ((p >> 8)&255)*255/a) : 0;
                dst[2] = a ? MIN(255, (p&255)*255/a) : 0;
                dst[3] = a;
            }
        }
    }
    g_free(pixels);
    if (!pixbuf)
        g_set_error_literal(error, G_IO_ERROR, G_IO_ERROR_NO_SPACE, "Not enough memory to render SVG");
    if (self->pixbuf && pixbuf) g_set_object(&self->scaled, pixbuf);
    return pixbuf;
}
gboolean rsvg_handle_close(RsvgHandle *self, GError **error) {
    g_clear_object(&self->pixbuf);
    g_clear_object(&self->scaled);
    self->pixbuf = render(self, 0, 0, error);
    return self->pixbuf != NULL;
}
GdkPixbuf *rsvg_handle_get_pixbuf(RsvgHandle *self) {
    return self->pixbuf ? g_object_ref(self->pixbuf) : NULL;
}
void gdk_cairo_set_source_pixbuf(cairo_t *, const GdkPixbuf *, double, double);
gboolean rsvg_handle_render_cairo(RsvgHandle *self, cairo_t *cr) {
    if (!self->pixbuf) return FALSE;
    double w = gdk_pixbuf_get_width(self->pixbuf), h = gdk_pixbuf_get_height(self->pixbuf);
    double x = 1, y = 0, xx = 0, yy = 1;
    cairo_user_to_device_distance(cr, &x, &y); cairo_user_to_device_distance(cr, &xx, &yy);
    double scale = MAX(hypot(x,y), hypot(xx,yy));
    cairo_surface_type_t type = cairo_surface_get_type(cairo_get_target(cr));
    if (type == CAIRO_SURFACE_TYPE_PDF || type == CAIRO_SURFACE_TYPE_PS || type == CAIRO_SURFACE_TYPE_SVG)
        scale *= 600.0/72.0;
    if (!isfinite(scale) || scale <= 0) return FALSE;
    scale = MIN(scale, MIN(32767.0/MAX(w,h), sqrt(64.0*1024*1024/(w*h))));
    GdkPixbuf *pixbuf = render(self, MAX(1,(int)floor(w*scale)), MAX(1,(int)floor(h*scale)), NULL);
    /* Keep the last validated image visible if a higher-resolution render
     * hits its resource limit; never retry with an unsandboxed SVG decoder. */
    if (!pixbuf) pixbuf = g_object_ref(self->pixbuf);
    cairo_save(cr);
    cairo_scale(cr, w/gdk_pixbuf_get_width(pixbuf), h/gdk_pixbuf_get_height(pixbuf));
    gdk_cairo_set_source_pixbuf(cr, pixbuf, 0, 0);
    cairo_paint(cr);
    cairo_restore(cr);
    g_object_unref(pixbuf);
    return TRUE;
}
