#include <librsvg/rsvg.h>
#include <string.h>
static RsvgHandle *open_svg(const char *text, gboolean expected) {
    GError *error = NULL;
    RsvgHandle *svg = rsvg_handle_new();
    g_assert_true(rsvg_handle_write(svg, (const guint8 *)text, strlen(text), &error));
    g_assert_cmpint(rsvg_handle_close(svg, &error), ==, expected);
    if (expected) g_assert_no_error(error); else g_assert_nonnull(error);
    g_clear_error(&error);
    return svg;
}
int main(void) {
    RsvgHandle *svg = open_svg("<svg xmlns='http://www.w3.org/2000/svg' width='32' height='16'><rect width='32' height='16' fill='red' opacity='.5'/></svg>", TRUE);
    GdkPixbuf *pixels = rsvg_handle_get_pixbuf(svg);
    g_assert_cmpint(gdk_pixbuf_get_width(pixels), ==, 32);
    g_assert_cmpint(gdk_pixbuf_get_height(pixels), ==, 16);
    g_assert_cmpint(gdk_pixbuf_get_pixels(pixels)[0], ==, 255);
    g_assert_cmpint(gdk_pixbuf_get_pixels(pixels)[3], ==, 128);
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 64, 32);
    cairo_t *cr = cairo_create(surface);
    cairo_scale(cr, 2, 2);
    g_assert_true(rsvg_handle_render_cairo(svg, cr));
    g_assert_true(rsvg_handle_render_cairo(svg, cr)); /* cached render */
    cairo_destroy(cr); cairo_surface_destroy(surface);
    g_object_unref(pixels); g_object_unref(svg);
    svg = open_svg("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 32'><rect width='16' height='16' fill='red'/></svg>", TRUE);
    pixels = rsvg_handle_get_pixbuf(svg);
    g_assert_cmpint(gdk_pixbuf_get_width(pixels), ==, 64);
    g_assert_cmpint(gdk_pixbuf_get_height(pixels), ==, 32);
    g_object_unref(pixels); g_object_unref(svg);
    svg = open_svg("<svg", FALSE); g_object_unref(svg);
    svg = open_svg("<svg xmlns='http://www.w3.org/2000/svg' width='1e40' height='16'/>", FALSE); g_object_unref(svg);
    svg = open_svg("<svg xmlns='http://www.w3.org/2000/svg' width='32767' height='32767'/>", FALSE); g_object_unref(svg);
    svg = rsvg_handle_new();
    GError *error = NULL;
    guint8 byte = 0;
    g_assert_false(rsvg_handle_write(svg, &byte, 33*1024*1024, &error));
    g_assert_nonnull(error); g_clear_error(&error); g_object_unref(svg);
    /* An outside file is never bound into the renderer's namespace. */
    g_file_set_contents("/tmp/viewer-outside.svg", "<svg xmlns='http://www.w3.org/2000/svg' width='4' height='4'><rect width='4' height='4' fill='red'/></svg>", -1, NULL);
    svg = open_svg("<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' width='4' height='4'><image xlink:href='file:///tmp/viewer-outside.svg' width='4' height='4'/></svg>", TRUE);
    pixels = rsvg_handle_get_pixbuf(svg);
    g_assert_cmpint(gdk_pixbuf_get_pixels(pixels)[3], ==, 0);
    g_object_unref(pixels); g_object_unref(svg);
    g_print("PASS: SVG alpha, scaled rendering, corrupt and oversized inputs, outside file isolation\n");
}
