/* The GTK 3.6 implementation multiplies signed dimensions before allocating
 * its surface. Validate geometry before asking the historical Cairo allocator
 * for a surface. Keep the original premultiplication and channel ordering.
 * Rebuilt into GDK so internal calls cannot bypass this implementation.
 */
#include <cairo.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <stdint.h>

void gdk_cairo_set_source_pixbuf(cairo_t *cr, const GdkPixbuf *pixbuf,
                                double x, double y)
{
    g_return_if_fail(cr != NULL && GDK_IS_PIXBUF(pixbuf));
    int width = gdk_pixbuf_get_width(pixbuf);
    int height = gdk_pixbuf_get_height(pixbuf);
    int channels = gdk_pixbuf_get_n_channels(pixbuf);
    g_return_if_fail(channels == 3 || channels == 4);
    if (width <= 0 || height <= 0 || width > 32767 || height > 32767 ||
        (uint64_t)width * height > 64 * 1024 * 1024) {
        cairo_surface_t *invalid = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, -1, -1);
        cairo_set_source_surface(cr, invalid, 0, 0);
        cairo_surface_destroy(invalid);
        return;
    }
    cairo_surface_t *surface = cairo_image_surface_create(
        channels == 4 ? CAIRO_FORMAT_ARGB32 : CAIRO_FORMAT_RGB24, width, height);
    if (cairo_surface_status(surface) == CAIRO_STATUS_SUCCESS) {
        const unsigned char *src = gdk_pixbuf_read_pixels(pixbuf);
        unsigned char *dst = cairo_image_surface_get_data(surface);
        int src_stride = gdk_pixbuf_get_rowstride(pixbuf);
        int dst_stride = cairo_image_surface_get_stride(surface);
        for (int row = 0; row < height; row++) {
            const unsigned char *p = src + (size_t)row * src_stride;
            uint32_t *q = (uint32_t *)(dst + (size_t)row * dst_stride);
            for (int col = 0; col < width; col++, p += channels) {
                unsigned a = channels == 4 ? p[3] : 255;
                unsigned r = p[0] * a + 128, g = p[1] * a + 128, b = p[2] * a + 128;
                r = ((r >> 8) + r) >> 8;
                g = ((g >> 8) + g) >> 8;
                b = ((b >> 8) + b) >> 8;
                q[col] = (a << 24) | (r << 16) | (g << 8) | b;
            }
        }
        cairo_surface_mark_dirty(surface);
    }
    cairo_set_source_surface(cr, surface, x, y);
    cairo_surface_destroy(surface);
}
