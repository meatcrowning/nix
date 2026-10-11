/* A compromised or crashing renderer must not control allocation or lifetime. */
#ifdef FAKE_WORKER
#include <stdint.h>
#include <stdio.h>
int main(void) {
    int mode = getchar();
    uint32_t header[] = {0x31564753, 32, 16};
    if (mode == 0) header[0] = 0;
    if (mode == 1) header[1] = UINT32_MAX;
    fwrite(header, sizeof header, 1, stdout);
    return fflush(stdout) != 0; /* Deliberately truncate a valid-sized response. */
}
#else
#include <librsvg/rsvg.h>
int main(void) {
    for (guint mode = 0; mode < 3; mode++) {
        guint8 *input = g_malloc0(256*1024);
        input[0] = mode;
        RsvgHandle *svg = rsvg_handle_new();
        GError *error = NULL;
        g_assert_true(rsvg_handle_write(svg, input, 256*1024, &error));
        g_assert_false(rsvg_handle_close(svg, &error));
        g_assert_nonnull(error);
        g_clear_error(&error);
        g_object_unref(svg);
        g_free(input);
    }
    g_print("PASS: invalid, oversized and truncated renderer replies; broken input pipe\n");
}
#endif
