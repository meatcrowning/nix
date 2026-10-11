/* Modern Cairo/HarfBuzz over Quantal's unmodified FreeType 2.4.10 renderer.
 * New variable/colour font capabilities are absent, as they were in 2012.
 * The two private prefixes below are pinned to Ubuntu's 2.4.10 build with
 * FT_CONFIG_OPTION_OLD_INTERNALS; never reuse this adapter with another ABI.
 */
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_MULTIPLE_MASTERS_H
#include FT_COLOR_H
#include FT_FONT_FORMATS_H
#include <string.h>

typedef struct {
    FT_UShort reserved1;
    FT_Short reserved2;
    FT_Matrix transform_matrix;
    FT_Vector transform_delta;
} QuantalFaceInternal;
typedef struct { FT_Memory memory; } QuantalLibrary;

void FT_Get_Transform(FT_Face face, FT_Matrix *matrix, FT_Vector *delta)
{
    if (!face) return;
    const QuantalFaceInternal *internal = (const void *)face->internal;
    if (matrix) *matrix = internal->transform_matrix;
    if (delta) *delta = internal->transform_delta;
}

FT_Error FT_Done_MM_Var(FT_Library library, FT_MM_Var *master)
{
    if (!library) return FT_Err_Invalid_Library_Handle;
    FT_Memory memory = ((QuantalLibrary *)library)->memory;
    if (master) memory->free(memory, master);
    return FT_Err_Ok;
}

/* This was only renamed; the original implementation has identical semantics. */
extern const char *FT_Get_X11_Font_Format(FT_Face face);
const char *FT_Get_Font_Format(FT_Face face) { return FT_Get_X11_Font_Format(face); }
void FT_Set_Default_Properties(FT_Library library) { (void)library; }

FT_Error FT_Get_Var_Blend_Coordinates(FT_Face face, FT_UInt count, FT_Fixed *coords)
{ (void)face; (void)count; (void)coords; return FT_Err_Unimplemented_Feature; }
FT_Error FT_Get_Var_Design_Coordinates(FT_Face face, FT_UInt count, FT_Fixed *coords)
{ (void)face; (void)count; (void)coords; return FT_Err_Unimplemented_Feature; }
FT_Error FT_Set_Named_Instance(FT_Face face, FT_UInt index)
{ (void)face; return index ? FT_Err_Unimplemented_Feature : FT_Err_Ok; }
FT_Error FT_Palette_Data_Get(FT_Face face, FT_Palette_Data *data)
{ (void)face; if (data) memset(data, 0, sizeof(*data)); return FT_Err_Unimplemented_Feature; }
FT_Error FT_Palette_Select(FT_Face face, FT_UShort index, FT_Color **colors)
{ (void)face; (void)index; if (colors) *colors = NULL; return FT_Err_Unimplemented_Feature; }
FT_Error FT_Palette_Set_Foreground_Color(FT_Face face, FT_Color color)
{ (void)face; (void)color; return FT_Err_Unimplemented_Feature; }
FT_Bool FT_Get_Color_Glyph_Layer(FT_Face face, FT_UInt glyph, FT_UInt *layer,
                               FT_UInt *color, FT_LayerIterator *iterator)
{ (void)face; (void)glyph; (void)layer; (void)color; (void)iterator; return 0; }
FT_Bool FT_Get_Color_Glyph_Paint(FT_Face face, FT_UInt glyph, FT_Color_Root_Transform root,
                               FT_OpaquePaint *paint)
{ (void)face; (void)glyph; (void)root; (void)paint; return 0; }
FT_Bool FT_Get_Color_Glyph_ClipBox(FT_Face face, FT_UInt glyph, FT_ClipBox *box)
{ (void)face; (void)glyph; (void)box; return 0; }
FT_Bool FT_Get_Colorline_Stops(FT_Face face, FT_ColorStop *stop, FT_ColorStopIterator *iterator)
{ (void)face; (void)stop; (void)iterator; return 0; }
FT_Bool FT_Get_Paint_Layers(FT_Face face, FT_LayerIterator *iterator, FT_OpaquePaint *paint)
{ (void)face; (void)iterator; (void)paint; return 0; }
FT_Bool FT_Get_Paint(FT_Face face, FT_OpaquePaint opaque, FT_COLR_Paint *paint)
{ (void)face; (void)opaque; (void)paint; return 0; }
