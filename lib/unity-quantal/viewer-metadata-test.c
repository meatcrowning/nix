/* Split-input and malformed metadata regressions, run under ASan/UBSan. */
#include "config.h"
#include "eog-metadata-reader.h"
#include <string.h>
#include <zlib.h>

static void be32(GByteArray *b, guint32 n)
{
    n = GUINT32_TO_BE(n);
    g_byte_array_append(b, (guchar *)&n, 4);
}

static void chunk(GByteArray *b, const char *name, const guchar *data, guint n)
{
    be32(b, n);
    g_byte_array_append(b, (const guchar *)name, 4);
    g_byte_array_append(b, data, n);
    guint32 crc = crc32(0, (const Bytef *)name, 4);
    be32(b, crc32(crc, data, n));
}

static void parse(EogMetadataFileType type, const guchar *data, guint n,
                  guint step, gboolean expect_exif, gboolean expect_profile)
{
    EogMetadataReader *r = eog_metadata_reader_new(type);
    for (guint i = 0; i < n; i += step) {
        guint count = MIN(step, n - i);
        /* Exact allocations make overreads visible to the sanitizer. */
        guchar *part = g_memdup2(data + i, count);
        eog_metadata_reader_consume(r, part, count);
        g_free(part);
    }
    guchar *raw = NULL;
    guint length = 0;
    eog_metadata_reader_get_exif_chunk(r, &raw, &length);
    if (expect_exif) {
        g_assert_cmpuint(length, ==, 14);
        g_assert_cmpmem(raw, 6, "Exif\0\0", 6);
    }
    g_free(raw);
    cmsHPROFILE profile = eog_metadata_reader_get_icc_profile(r);
    if (expect_profile) g_assert_nonnull(profile);
    if (profile) cmsCloseProfile(profile);
    XmpPtr xmp = eog_metadata_reader_get_xmp_data(r);
    if (xmp) xmp_free(xmp);
    g_object_unref(r);
}

int main(void)
{
    const guchar jpeg[] = {255,216,255,225,0,16,'E','x','i','f',0,0,
                          'I','I',42,0,8,0,0,0,255,217};
    const guchar ihdr[] = {0,0,0,2,0,0,0,2,8,2,0,0,0};
    const guchar srgb[] = {0};
    const guchar chroma[] = {0,0,122,38,0,0,128,132,0,0,250,0,0,0,128,232,
                            0,0,117,48,0,0,234,96,0,0,58,152,0,0,23,112};
    const guchar gamma[] = {0,0,177,143};
    xmp_init();
    for (guint invalid = 0; invalid < 3; invalid++) {
        GByteArray *png = g_byte_array_new();
        g_byte_array_append(png, (const guchar *)"\211PNG\r\n\032\n", 8);
        chunk(png, "IHDR", ihdr, sizeof ihdr);
        chunk(png, "sRGB", srgb, sizeof srgb);
        chunk(png, "cHRM", chroma, sizeof chroma);
        chunk(png, "gAMA", gamma, sizeof gamma);
        if (invalid == 1) chunk(png, "iCCP", (const guchar *)"no-terminator", 13);
        if (invalid == 2) chunk(png, "iCCP", (const guchar *)"name\0", 5);
        chunk(png, "IEND", NULL, 0);
        for (guint step = 1; step < 128; step++) {
            parse(EOG_METADATA_PNG, png->data, png->len, step, FALSE, invalid == 0);
            parse(EOG_METADATA_JPEG, jpeg, sizeof jpeg, step, TRUE, FALSE);
        }
        for (guint n = 1; n < png->len; n++)
            parse(EOG_METADATA_PNG, png->data, n, 7, FALSE, FALSE);
        g_byte_array_unref(png);
    }
    for (guint n = 1; n < sizeof jpeg; n++)
        parse(EOG_METADATA_JPEG, jpeg, n, 1, FALSE, FALSE);
    /* APP2/ICC identifiers and the profile offset require at least 14 bytes. */
    for (guint n = 1; n <= 32; n++) {
        guchar icc[40] = {255,216,255,226,0,0};
        icc[5] = n + 2;
        memcpy(icc + 6, "ICC_PROFILE", MIN(n, 11));
        icc[n + 6] = 255;
        icc[n + 7] = 217;
        for (guint step = 1; step <= 16; step++)
            for (guint length = 6; length <= n + 8; length++)
                parse(EOG_METADATA_JPEG, icc, length, step, FALSE, FALSE);
    }
    xmp_terminate();
    g_print("PASS: split PNG/JPEG metadata, truncated chunks and bounded ICC names\n");
}
