#!/usr/bin/python2.7
"""List every settings key GNOME Tweak Tool 3.6 shows in the Unity session.

Runs inside the original runtime with a display. It loads the tool's tweak
groups exactly as the tool does and records each GSettings key its widgets
read, write or watch, plus the schemas it hides as missing. Prints JSON.
"""
from __future__ import print_function

import json
import logging
import sys

import gtweak
from gtweak.defs import GSETTINGS_SCHEMA_DIR, TWEAK_DIR, DATA_DIR, PKG_DATA_DIR, LOCALE_DIR
gtweak.GSETTINGS_SCHEMA_DIR = GSETTINGS_SCHEMA_DIR
gtweak.TWEAK_DIR = TWEAK_DIR
gtweak.DATA_DIR = DATA_DIR
gtweak.PKG_DATA_DIR = PKG_DATA_DIR
gtweak.LOCALE_DIR = LOCALE_DIR
gtweak.ENABLE_TEST = False
gtweak.APP_NAME = "gnome-tweak-tool"
gtweak.VERBOSE = False
logging.basicConfig(level=logging.CRITICAL)
import gettext
gettext.install(gtweak.APP_NAME, LOCALE_DIR, names=("gettext", "ngettext"))

from gi.repository import Gtk
import gtweak.gsettings as settings
from gtweak.tweakmodel import TweakModel

keys = set()
missing = set()
METHODS = ["get_value", "get_string", "get_boolean", "get_enum", "get_int", "get_double", "get_strv",
           "set_value", "set_string", "set_boolean", "set_enum", "set_int", "set_double", "set_strv",
           "get_range", "reset", "bind", "is_writable"]


def recorder(name):
    original = getattr(settings.GSettingsSetting, name)

    def record(self, key, *arguments, **options):
        keys.add((self.props.schema, key))
        return original(self, key, *arguments, **options)
    return record


for name in METHODS:
    setattr(settings.GSettingsSetting, name, recorder(name))
original_init = settings.GSettingsSetting.__init__


def init(self, schema_name, *arguments, **options):
    try:
        original_init(self, schema_name, *arguments, **options)
    except settings.GSettingsMissingError:
        missing.add(schema_name)
        raise
settings.GSettingsSetting.__init__ = init
original_connect = settings.GSettingsSetting.connect


def connect(self, signal, *arguments):
    if signal.startswith("changed::"):
        keys.add((self.props.schema, signal.split("::", 1)[1]))
    return original_connect(self, signal, *arguments)
settings.GSettingsSetting.connect = connect

model = TweakModel()
model.load_tweaks()
groups = []
for group in model.tweak_groups:
    groups.append(group.name)
    for tweak in group.tweaks:
        # Building a widget reads its current value.
        tweak.widget
json.dump({"keys": sorted("%s %s" % pair for pair in keys), "missing": sorted(missing), "groups": groups},
          sys.stdout, indent=1, sort_keys=True)
print()
