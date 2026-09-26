"""Typed access to the shared renderer ABI."""
import ctypes as C


def load_renderer(path):
    lib=C.CDLL(path)
    lib.gf_error.restype=C.c_char_p
    lib.gf_init.argtypes=[C.c_int,C.c_int]
    lib.gf_resize.argtypes=[C.c_int,C.c_int]
    lib.gf_frame.argtypes=[C.POINTER(C.c_float),C.c_long,C.c_uint]
    lib.gf_key.argtypes=[C.c_int]
    lib.gf_control_state.argtypes=[C.POINTER(C.c_long)]
    lib.gf_control_state.restype=None
    lib.gf_key.restype=lib.gf_close.restype=None
    lib.gf_set.argtypes=[C.c_char_p,C.c_double]
    lib.gf_get.argtypes=[C.c_char_p]
    lib.gf_get.restype=C.c_double
    lib.gf_get_interval.argtypes=[C.c_int]
    lib.gf_get_interval.restype=C.c_char_p
    lib.gf_set_interval.argtypes=[C.c_int,C.c_char_p]
    lib.gf_set_interval.restype=None
    lib.gf_choices.argtypes=[C.c_int]
    lib.gf_choices.restype=C.c_char_p
    lib.gf_selection.argtypes=[C.c_int]
    lib.gf_selection.restype=C.c_char_p
    lib.gf_select.argtypes=[C.c_int,C.c_char_p]
    lib.gf_preset_capture.restype=C.c_char_p
    lib.gf_preset_recall.argtypes=[C.c_int,C.c_char_p,C.c_long,C.c_int]
    lib.gf_preset_clear_particles.restype=None
    lib.gf_read.argtypes=[C.POINTER(C.c_ubyte),C.c_int,C.c_int]
    return lib
