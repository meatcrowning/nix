#!/usr/bin/env python3
"""Offscreen probe: does surfer's web font render crisp AND at the site's size?

Renders text into a <canvas> in a real offscreen QtWebEngine profile (surfer's
env: FONTCONFIG_FILE + the same chromium flags) and reads getImageData back.
Blur signature = GRAY FRACTION: pixels whose luma is neither near-black (ink)
nor near-white (paper). A pixel-exact aliased render has ~0 gray; a soft
grayscale-AA render has many. Chroma counted too (should be ~0 with lcd off).

The point of the table: the web TWIN family ("More Perfect DOS VGA (web)") is
a real installed face whose outlines/advances/metrics are pre-scaled 1.14x
(home/pkgs/desktop/font-files/scale-vga.py) — the font-file replacement for
the @font-face size-adjust alias that forced Chromium grayscale-AA. So each
twin@N row must come back like the plain@N*1.14 row beside it: SAME ink width
(size parity — a site's 16px reads at the proportional x-height) and 0 grey
(crisp — the antialias=false fontconfig pin reaches a real face). A grey
fraction of ~0.6-0.8 on a twin row means the pin is missing (see
home/pkgs/desktop/font.nix's 50-more-perfect-dos-vga-web-regular.conf).
"""
import os, sys, json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    flags + " --disable-features=AcceleratedVideoDecodeLinuxGL --disable-lcd-text").strip()

from PySide6.QtCore import QUrl, QTimer, QEventLoop
from PySide6.QtGui import QGuiApplication
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from PySide6.QtWebEngineCore import QWebEnginePage

QtWebEngineQuick.initialize()
app = QGuiApplication(sys.argv)

# twin@N must match plain@N*1.14: same ink (parity), 0 grey (crisp).
CASES = [
    ("plain@15",       '"More Perfect DOS VGA"', 15),
    ("plain@17.1",     '"More Perfect DOS VGA"', 17.1),   # 15 x 1.14
    ("plain@18.24",    '"More Perfect DOS VGA"', 18.24),  # 16 x 1.14
    ("plain@22.8",     '"More Perfect DOS VGA"', 22.8),   # 20 x 1.14
    ("twin@13.158",    '"More Perfect DOS VGA (web)"', 13.158),  # inherit: = plain@15
    ("twin@16",        '"More Perfect DOS VGA (web)"', 16),      # site 16px: = plain@18.24
    ("twin@20",        '"More Perfect DOS VGA (web)"', 20),      # site 20px: = plain@22.8
    ("DejaVuSans@15",  '"DejaVu Sans"', 15),   # smooth reference: high grey, no pin
    ("Botis@14",       '"Botis 4x6"', 14),     # 2nd pixel face: 0 grey on its 15px grid; soft off-grid (surfer.nix's AA carve-out)
]

page = QWebEnginePage()
loop = QEventLoop()
page.loadFinished.connect(lambda ok: loop.quit())
page.setHtml("<body style=margin:0;background:#fff><canvas id=c width=640 height=64></canvas>",
             QUrl("http://probe.local/"))
QTimer.singleShot(8000, loop.quit)
loop.exec()

def cj(js):
    r = {}
    l = QEventLoop()
    page.runJavaScript(js, 0, lambda v: (r.__setitem__('v', v), l.quit()))
    QTimer.singleShot(6000, l.quit)
    l.exec()
    return r.get('v')

def measure(fam, size):
    spec = "%spx %s" % (size, fam)
    cj("document.fonts.load(%s);" % json.dumps(spec))
    # small settle
    l = QEventLoop(); QTimer.singleShot(150, l.quit); l.exec()
    js = """(function(){
 var x=document.getElementById('c').getContext('2d');
 x.fillStyle='#fff';x.fillRect(0,0,640,64);
 x.textBaseline='top';x.fillStyle='#000';x.font=%s;
 x.fillText('Enclosing Ham 0123',2,8);
 var d=x.getImageData(0,0,640,64).data,ink=0,gray=0,chroma=0;
 for(var i=0;i<d.length;i+=4){
   var r=d[i],g=d[i+1],b=d[i+2];
   var L=0.299*r+0.587*g+0.114*b;
   if(Math.max(r,g,b)-Math.min(r,g,b)>10)chroma++;
   if(L>245){}else if(L<12)ink++;else gray++;
 }
 return JSON.stringify({ink:ink,gray:gray,chroma:chroma,font:x.font});
})()""" % json.dumps(spec)
    return cj(js)

print("%-18s %8s %6s %6s %7s %7s  %s" % ("case", "size", "ink", "gray", "grayF", "chroma", "resolvedFont"))
for label, fam, size in CASES:
    r = measure(fam, size)
    if not r:
        print("%-18s  NO RESULT" % label); continue
    o = json.loads(r)
    tot = o["ink"] + o["gray"]
    gf = o["gray"] / tot if tot else 0
    print("%-18s %8s %6d %6d %7.3f %7d  %s" % (
        label, str(size), o["ink"], o["gray"], gf, o["chroma"], o["font"]))
