#include <cairo.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <stdint.h>
#include <gdk/gdk.h>
void gdk_cairo_set_source_pixbuf(cairo_t *, const GdkPixbuf *, double, double);

int main(void)
{
    guchar pixels[] = {255, 0, 0, 128, 0, 255, 0, 255};
    GdkPixbuf *pixbuf = gdk_pixbuf_new_from_data(pixels, GDK_COLORSPACE_RGB,
                                               TRUE, 8, 2, 1, 8, NULL, NULL);
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, 2, 1);
    cairo_t *cr = cairo_create(surface);
    gdk_cairo_set_source_pixbuf(cr, pixbuf, 0, 0);
    cairo_paint(cr);
    cairo_surface_flush(surface);
    uint32_t *result = (uint32_t *)cairo_image_surface_get_data(surface);
    g_assert_cmphex(result[0], ==, 0x80800000);
    g_assert_cmphex(result[1], ==, 0xff00ff00);
    g_object_unref(pixbuf);
    /* Cairo must reject this geometry before touching the tiny backing store. */
    pixbuf = gdk_pixbuf_new_from_data(pixels, GDK_COLORSPACE_RGB,
                                     TRUE, 8, 70000, 70000, 280000, NULL, NULL);
    gdk_cairo_set_source_pixbuf(cr, pixbuf, 0, 0);
    g_assert_cmpint(cairo_status(cr), !=, CAIRO_STATUS_SUCCESS);
    g_object_unref(pixbuf);
    cairo_destroy(cr);
    cairo_surface_destroy(surface);
    g_setenv("GTK_PATH", "/viewer/private", TRUE);
    g_setenv("_UNITY_VIEWER_HOST_GTK_PATH", "set:/host/original", TRUE);
    g_setenv("_UNITY_VIEWER_HOST_LD_LIBRARY_PATH", "unset", TRUE);
    g_setenv("LD_LIBRARY_PATH", "/viewer/private", TRUE);
    GAppLaunchContext *context = g_object_new(GDK_TYPE_APP_LAUNCH_CONTEXT, NULL);
    gchar **environment = g_app_launch_context_get_environment(context);
    g_assert_cmpstr(g_environ_getenv(environment, "GTK_PATH"), ==, "/host/original");
    g_assert_null(g_environ_getenv(environment, "LD_LIBRARY_PATH"));
    g_assert_null(g_environ_getenv(environment, "_UNITY_VIEWER_HOST_GTK_PATH"));
    g_strfreev(environment);
    g_object_unref(context);
    g_print("PASS: original alpha conversion oversized surface rejection and clean child environment\n");
}
