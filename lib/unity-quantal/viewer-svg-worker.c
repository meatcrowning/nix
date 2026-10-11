/* Kept out of the historical font process: librsvg owns a modern text stack. */
#include <librsvg/rsvg.h>
#include <cairo.h>
#include <glib.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <sys/resource.h>

int main(int argc, char **argv) {
    struct rlimit memory = {1024UL*1024*1024, 1024UL*1024*1024}, cpu = {10, 10};
    struct rlimit core = {0, 0}, files = {64, 64}, size = {32*1024*1024, 32*1024*1024};
    if (setrlimit(RLIMIT_AS, &memory) || setrlimit(RLIMIT_CPU, &cpu) ||
        setrlimit(RLIMIT_CORE, &core) || setrlimit(RLIMIT_NOFILE, &files) ||
        setrlimit(RLIMIT_FSIZE, &size)) return 1;
    if (argc != 3) return 1;
    GByteArray *input = g_byte_array_new();
    unsigned char block[16384];
    size_t n;
    while ((n = fread(block, 1, sizeof block, stdin))) {
        if (input->len + n > 32*1024*1024) return 1;
        g_byte_array_append(input, block, n);
    }
    GError *error = NULL;
    RsvgHandle *svg = rsvg_handle_new_from_data(input->data, input->len, &error);
    if (!svg) return 1;
    double w, h;
    if (!rsvg_handle_get_intrinsic_size_in_pixels(svg, &w, &h)) {
        /* Match the historical API's viewBox and percentage-size fallback. */
        RsvgDimensionData dimensions;
        rsvg_handle_get_dimensions(svg, &dimensions);
        w = dimensions.width; h = dimensions.height;
    }
    int width = atoi(argv[1]), height = atoi(argv[2]);
    if (!isfinite(w) || !isfinite(h) || w <= 0 || h <= 0 || w > 32767 || h > 32767) return 1;
    if (!width && !height) { width = (int)ceil(w); height = (int)ceil(h); }
    if (width <= 0 || height <= 0 || width > 32767 || height > 32767 ||
        (uint64_t)width * height > 64*1024*1024) return 1;
    cairo_surface_t *surface = cairo_image_surface_create(CAIRO_FORMAT_ARGB32, width, height);
    if (cairo_surface_status(surface)) return 1;
    cairo_t *cr = cairo_create(surface);
    RsvgRectangle viewport = {0, 0, width, height};
    if (!rsvg_handle_render_document(svg, cr, &viewport, &error)) return 1;
    cairo_surface_flush(surface);
    uint32_t header[] = {0x31564753, width, height};
    if (fwrite(header, sizeof header, 1, stdout) != 1) return 1;
    unsigned char *pixels = cairo_image_surface_get_data(surface);
    int stride = cairo_image_surface_get_stride(surface);
    for (int y = 0; y < height; y++)
        if (fwrite(pixels + (size_t)y * stride, 4, width, stdout) != (size_t)width) return 1;
    return fflush(stdout) != 0;
}
