"""Quantal SVG rasterization with grayscale text on a transparent surface.

The pixbuf SVG loader inherits fontconfig's LCD subpixel antialiasing, which
leaves coloured fringes when the transparent result is composited by GTK.
Use the same librsvg renderer with explicit Cairo font options instead.
"""
from ctypes import CDLL, CFUNCTYPE, c_void_p, c_char_p, c_int, c_uint, c_size_t, string_at
from gi.repository import GdkPixbuf


def _bind(lib, name, result, *args):
    fn = getattr(lib, name)
    fn.restype, fn.argtypes = result, args
    return fn


_cairo = CDLL('libcairo.so.2')
_rsvg = CDLL('librsvg-2.so.2')
_gobject = CDLL('libgobject-2.0.so.0')
_surface = _bind(_cairo, 'cairo_image_surface_create', c_void_p, c_int, c_int, c_int)
_create = _bind(_cairo, 'cairo_create', c_void_p, c_void_p)
_options = _bind(_cairo, 'cairo_font_options_create', c_void_p)
_antialias = _bind(_cairo, 'cairo_font_options_set_antialias', None, c_void_p, c_int)
_set_options = _bind(_cairo, 'cairo_set_font_options', None, c_void_p, c_void_p)
_destroy_options = _bind(_cairo, 'cairo_font_options_destroy', None, c_void_p)
_destroy = _bind(_cairo, 'cairo_destroy', None, c_void_p)
_destroy_surface = _bind(_cairo, 'cairo_surface_destroy', None, c_void_p)
_new = _bind(_rsvg, 'rsvg_handle_new_from_data', c_void_p, c_char_p, c_size_t, c_void_p)
_render = _bind(_rsvg, 'rsvg_handle_render_cairo', c_int, c_void_p, c_void_p)
_unref = _bind(_gobject, 'g_object_unref', None, c_void_p)
_Write = CFUNCTYPE(c_int, c_void_p, c_void_p, c_uint)
_png = _bind(_cairo, 'cairo_surface_write_to_png_stream', c_int, c_void_p, _Write, c_void_p)


def rasterize(svg, width, height):
    handle = _new(svg, len(svg), None)
    if not handle:
        raise ValueError('Invalid layout SVG')
    surface = _surface(0, width, height)  # CAIRO_FORMAT_ARGB32
    context = _create(surface)
    options = _options()
    chunks = []
    @_Write
    def write(_closure, data, length):
        chunks.append(string_at(data, length))
        return 0
    try:
        _antialias(options, 2)  # CAIRO_ANTIALIAS_GRAY
        _set_options(context, options)
        if not _render(handle, context) or _png(surface, write, None):
            raise ValueError('Could not render layout SVG')
    finally:
        _destroy_options(options)
        _destroy(context)
        _destroy_surface(surface)
        _unref(handle)
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(b''.join(chunks))
    loader.close()
    return loader.get_pixbuf()
