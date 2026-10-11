#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_MULTIPLE_MASTERS_H
#include FT_COLOR_H
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv)
{
    assert(argc > 1);
    FT_Library library;
    assert(!FT_Init_FreeType(&library));
    FT_Int major, minor, patch;
    FT_Library_Version(library, &major, &minor, &patch);
    assert(major == 2 && minor == 4 && patch == 10);
    for (int font = 1; font < argc; ++font) {
        FT_Face face;
        assert(!FT_New_Face(library, argv[font], 0, &face));
#ifdef ADAPTER
        FT_Matrix matrix = {65536, 16384, -8192, 98304}, actual;
        FT_Vector delta = {17, -29}, actual_delta;
        FT_Set_Transform(face, &matrix, &delta);
        FT_Get_Transform(face, &actual, &actual_delta);
        assert(!memcmp(&matrix, &actual, sizeof(matrix)));
        assert(!memcmp(&delta, &actual_delta, sizeof(delta)));
        FT_Set_Transform(face, NULL, NULL);
        FT_Get_Transform(face, &actual, &actual_delta);
        assert(actual.xx == 65536 && actual.yy == 65536 && !actual.xy && !actual.yx);
        assert(!actual_delta.x && !actual_delta.y);
        FT_Palette_Data palette;
        memset(&palette, 255, sizeof(palette));
        assert(FT_Palette_Data_Get(face, &palette) == FT_Err_Unimplemented_Feature);
        assert(!palette.num_palettes && !palette.num_palette_entries);
        FT_OpaquePaint paint;
        assert(!FT_Get_Color_Glyph_Paint(face, 1, FT_COLOR_INCLUDE_ROOT_TRANSFORM, &paint));
        assert(FT_Get_Var_Design_Coordinates(face, 0, NULL) == FT_Err_Unimplemented_Feature);
        assert(!FT_Done_MM_Var(library, NULL));
#endif
        uint64_t hash = 1469598103934665603ULL;
        for (unsigned size = 9; size <= 26; ++size) {
            assert(!FT_Set_Pixel_Sizes(face, 0, size));
            for (unsigned c = 32; c <= 255; ++c) {
                for (unsigned mode = 0; mode < 2; ++mode) {
                    assert(!FT_Load_Char(face, c, mode ? FT_LOAD_TARGET_LCD : FT_LOAD_DEFAULT));
                    assert(!FT_Render_Glyph(face->glyph, mode ? FT_RENDER_MODE_LCD : FT_RENDER_MODE_NORMAL));
                    FT_Bitmap *bitmap = &face->glyph->bitmap;
                    for (unsigned y = 0; y < bitmap->rows; ++y)
                        for (unsigned x = 0; x < bitmap->width; ++x)
                            hash = (hash ^ bitmap->buffer[y * bitmap->pitch + x]) * 1099511628211ULL;
                }
            }
        }
        printf("%016lx\n", (unsigned long)hash);
        FT_Done_Face(face);
    }
    FT_Done_FreeType(library);
}
