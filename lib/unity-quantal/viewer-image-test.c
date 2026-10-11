/* Exercise the actual EOG load/transform/save path without a desktop. */
#include "config.h"
#include "eog-image.h"
#include "eog-image-save-info.h"
#include "eog-transform.h"
#include <glib/gstdio.h>

static EogImage *load(const char *path, int width, int height)
{
    GFile *file = g_file_new_for_path(path);
    EogImage *image = eog_image_new_file(file);
    GError *error = NULL;
    if (!eog_image_load(image, EOG_IMAGE_DATA_IMAGE, NULL, &error))
        g_error("%s: %s", path, error->message);
    int w, h;
    eog_image_get_size(image, &w, &h);
    g_assert_cmpint(w, ==, width);
    g_assert_cmpint(h, ==, height);
    g_object_unref(file);
    return image;
}

int main(int argc, char **argv)
{
    g_assert_cmpint(argc, ==, 2);
    xmp_init();
    const char *formats[] = {"png", "jpeg", "bmp", "tiff", "ico", "gif", "svg", "pnm", "xpm", "tga"};
    for (guint i = 0; i < G_N_ELEMENTS(formats); i++) {
        gchar *path = g_strdup_printf("%s/input.%s", argv[1], formats[i]);
        EogImage *image = load(path, 32, 16);
        if (i < 2) {
            EogTransform *turn = eog_transform_rotate_new(90);
            eog_image_transform(image, turn, NULL);
            g_object_unref(turn);
            EogImageSaveInfo *source = eog_image_save_info_new_from_image(image);
            GError *error = NULL;
            g_assert_true(eog_image_save_by_info(image, source, &error));
            g_assert_no_error(error);
            EogImage *reopened = load(path, 16, 32);
            g_object_unref(reopened);
            g_object_unref(source);
        }
        g_object_unref(image);
        g_free(path);
    }
    gchar *animation_path = g_build_filename(argv[1], "animation.gif", NULL);
    EogImage *animation = load(animation_path, 32, 16);
    eog_image_data_ref(animation);
    g_assert_true(eog_image_is_animation(animation));
    g_assert_true(eog_image_start_animation(animation));
    gboolean advanced = FALSE;
    gint64 deadline = g_get_monotonic_time() + G_TIME_SPAN_SECOND;
    while (g_get_monotonic_time() < deadline && !advanced) {
        while (g_main_context_iteration(NULL, FALSE)) {}
        GdkPixbuf *frame = eog_image_get_pixbuf(animation);
        advanced = gdk_pixbuf_get_pixels(frame)[1] == 255;
        g_object_unref(frame);
        g_usleep(1000);
    }
    g_assert_true(advanced);
    gpointer weak = animation;
    g_object_add_weak_pointer(G_OBJECT(animation), &weak);
    eog_image_data_unref(animation);
    g_object_unref(animation);
    deadline = g_get_monotonic_time() + G_TIME_SPAN_SECOND;
    while (weak && g_get_monotonic_time() < deadline) {
        while (g_main_context_iteration(NULL, FALSE)) {}
        g_usleep(1000);
    }
    g_assert_null(weak);
    g_free(animation_path);
    gchar *path = g_build_filename(argv[1], "corrupt.png", NULL);
    g_file_set_contents(path, "\211PNG\r\n\032\n", 8, NULL);
    GFile *file = g_file_new_for_path(path);
    EogImage *image = eog_image_new_file(file);
    GError *error = NULL;
    g_assert_false(eog_image_load(image, EOG_IMAGE_DATA_IMAGE, NULL, &error));
    g_assert_nonnull(error);
    g_clear_error(&error);
    g_object_unref(image);
    g_object_unref(file);
    g_free(path);
    xmp_terminate();
    g_print("PASS: ten formats, native PNG/JPEG rotate/save/reopen, animation and pending-timer teardown, corrupt input\n");
}
