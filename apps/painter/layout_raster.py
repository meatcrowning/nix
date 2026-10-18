"""Quantal SVG rasterization with grayscale text on a transparent surface.

The pixbuf SVG loader inherits fontconfig's LCD subpixel antialiasing, which
leaves coloured fringes when the transparent result is composited by GTK.
Old librsvg can override Cairo font options through fontconfig. Render the
white lettering into an alpha-only mask so LCD colour channels cannot leak
into the composited image; keep coloured guides and reference images intact.
"""
from copy import deepcopy
from xml.etree import ElementTree as ET
from ctypes import CDLL, CFUNCTYPE, c_void_p, c_char_p, c_int, c_uint, c_size_t, c_double, string_at
from gi.repository import GdkPixbuf

# Quantal librsvg resolves embedded image links by the conventional prefix.
ET.register_namespace('', 'http://www.w3.org/2000/svg')
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')


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
_source = _bind(_cairo, 'cairo_set_source_rgba', None, c_void_p, c_double, c_double, c_double, c_double)
_mask = _bind(_cairo, 'cairo_mask_surface', None, c_void_p, c_void_p, c_double, c_double)
_render = _bind(_rsvg, 'rsvg_handle_render_cairo', c_int, c_void_p, c_void_p)
_unref = _bind(_gobject, 'g_object_unref', None, c_void_p)
_Write = CFUNCTYPE(c_int, c_void_p, c_void_p, c_uint)
_png = _bind(_cairo, 'cairo_surface_write_to_png_stream', c_int, c_void_p, _Write, c_void_p)


def _layers(svg):
    scene = ET.fromstring(svg)
    lettering = deepcopy(scene)
    def prune(node, text_only):
        for child in list(node):
            tag = child.tag.rsplit('}', 1)[-1]
            if tag == 'defs':
                continue
            if (text_only and tag not in ('g', 'text')) or (not text_only and tag == 'text'):
                node.remove(child)
            elif tag == 'g':
                prune(child, text_only)
    prune(scene, False)
    prune(lettering, True)
    return ET.tostring(scene), ET.tostring(lettering)


def _draw(svg, context):
    handle = _new(svg, len(svg), None)
    if not handle:
        raise ValueError('Invalid layout SVG')
    try:
        if not _render(handle, context):
            raise ValueError('Could not render layout SVG')
    finally:
        _unref(handle)


def rasterize(svg, width, height):
    scene, lettering = _layers(svg)
    surface = _surface(0, width, height)  # CAIRO_FORMAT_ARGB32
    mask = _surface(2, width, height)  # CAIRO_FORMAT_A8
    text_context = _create(mask)
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
        _set_options(text_context, options)
        _draw(scene, context)
        _draw(lettering, text_context)
        _source(context, 1, 1, 1, 1)
        _mask(context, mask, 0, 0)
        if _png(surface, write, None):
            raise ValueError('Could not render layout SVG')
    finally:
        _destroy_options(options)
        _destroy(context)
        _destroy_surface(surface)
        _destroy(text_context)
        _destroy_surface(mask)
    loader = GdkPixbuf.PixbufLoader.new_with_type('png')
    loader.write(b''.join(chunks))
    loader.close()
    return loader.get_pixbuf()
