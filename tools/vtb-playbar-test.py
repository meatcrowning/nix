#!/usr/bin/env python3
"""Compile the real titlebar geometry and wheel handlers without a compositor.

No display, IPC, seat, audio, or user preferences are accessed. Only the
compositor-facing types and state are stubbed; layout and seek maths come from
vtbDeco.cpp so compact/noncompact and all four edges exercise the shipped code.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] / 'home/prog/hyprvtb/vtbDeco.cpp').read_text()


def function(signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end] + '\n'


code = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>
struct Vector2D { double x, y; };
struct CBox {
    double x=0,y=0,w=0,h=0;
    CBox round() const { return *this; }
};
struct SVtbAppButton { bool bottom=false, sep=false; bool isSep() const { return sep; } };
struct SVtbAppReg { bool playbar=true, footerBottom=false; std::vector<SVtbAppButton> buttons; };
namespace Cfg { bool value=true; bool compact() { return value; } }
enum class eBarSide { LEFT,RIGHT,TOP,BOTTOM };
eBarSide side=eBarSide::TOP;
eBarSide barSide() { return side; }
int cellSize() { return 20; }
int totalBarW() { return Cfg::compact()?24:48; }
int innerColX() { return 2; }
namespace IPointer { struct SAxisEvent { double delta; int deltaDiscrete; }; }
'''
for name in ('VTB_PAD', 'VTB_CELL_GAP', 'VTB_SEP_H', 'VTB_PLAYBAR_RESERVE',
             'VTB_PLAYBAR_MIN', 'VTB_PLAYBAR_SCROLL', 'VTB_PLAYBAR_DETENT',
             'VTB_PLAYBAR_DETENT120', 'VTB_PLAYBAR_ECHO_EPS'):
    code += re.search(r'^static constexpr [^\n]*\b' + name + r'\s*=.*?;', source, re.M)[0] + '\n'
for signature in ('static bool barVertical()', 'static Vector2D barLocalToGlobal(',
                  'static Vector2D globalToBarLocal(', 'static CBox barLocalToDevice(',
                  'static double appGroupHCompact(', 'static double appGroupTopCompact(',
                  'template <typename F>\nstatic void walkAppLayout(', 'static double bottomGroupH('):
    code += function(signature)
code += r'''
struct CVtbDeco {
    SVtbAppReg registration;
    int m_iFooterTextH=18;
    double m_playbarScrollAcc=0, position=.5;
    bool appReg(SVtbAppReg& out) { out=registration; return true; }
    int titleTopEff() { return 144; }
    bool playbarTrackLocal(const SVtbAppReg&,double,double,CBox&);
    double titleEndLocal(double);
    double playbarFrac(const SVtbAppReg&) { return position; }
    void playbarSeekTo(double value) { position=value; }
    void damageEntire() {}
    void playbarScrollBy(const SVtbAppReg&,const IPointer::SAxisEvent&);
};
'''
for signature in ('bool CVtbDeco::playbarTrackLocal(', 'double CVtbDeco::titleEndLocal(',
                  'void CVtbDeco::playbarScrollBy('):
    code += function(signature)
code += r'''
bool near(double a,double b) { return std::abs(a-b)<1e-9; }
int main() {
    CVtbDeco deco;
    auto& reg=deco.registration;
    reg.buttons.resize(12);
    reg.buttons[3].sep=true;
    reg.buttons.back().bottom=true;
    for (auto edge : {eBarSide::LEFT,eBarSide::RIGHT,eBarSide::TOP,eBarSide::BOTTOM}) {
        side=edge;
        for (double length : {440.,480.,800.,1400.}) {
            CBox track;
            assert(deco.playbarTrackLocal(reg,length,1,track));
            assert(track.h>=VTB_PLAYBAR_MIN && track.h<=VTB_PLAYBAR_RESERVE);
            assert(deco.titleEndLocal(length)+VTB_CELL_GAP<=track.y);
            double first=length;
            walkAppLayout(reg.buttons,length,[&](size_t,double y){first=std::min(first,y);});
            assert(track.y+track.h+VTB_PAD<=first);
            for(double scale : {1.,1.25,2.}) {
                const auto pixels=barLocalToDevice({0,0,500,500},track.x,track.y,track.w,track.h,scale);
                assert(near(barVertical()?pixels.h:pixels.w,track.h*scale));
            }
            for(double fraction : {0.,.25,.5,1.}) {
                const CBox window={50,60,900,700};
                auto global=barLocalToGlobal(window,track.x+track.w/2,track.y+track.h*fraction);
                auto local=globalToBarLocal(window,global);
                assert(near((local.y-track.y)/track.h,fraction));
            }
        }
        deco.position=.5; deco.m_playbarScrollAcc=0;
        deco.playbarScrollBy(reg,{-15,-120});
        assert(near(deco.position,barVertical()?.45:.55));
        deco.playbarScrollBy(reg,{15,120});
        assert(near(deco.position,.5));
        for(int i=0;i<20;i++) deco.playbarScrollBy(reg,{-.75,0});
        assert(near(deco.position,barVertical()?.45:.55));
        for(int i=0;i<100;i++) deco.playbarScrollBy(reg,{-15,-120});
        assert(near(deco.position,barVertical()?0:1));
        deco.playbarScrollBy(reg,{15,120});
        assert(near(deco.position,barVertical()?.05:.95));
    }
    CBox track;
    assert(!deco.playbarTrackLocal(reg,200,1,track)); // no overlap when controls fill the bar
    reg.playbar=false;
    assert(!deco.playbarTrackLocal(reg,800,1,track));
    assert(near(deco.titleEndLocal(800),appGroupTopCompact(reg.buttons,800)-VTB_PAD));
    reg.playbar=true;
    Cfg::value=false;
    for(bool footerBottom : {false,true}) {
        reg.footerBottom=footerBottom;
        assert(deco.playbarTrackLocal(reg,800,1,track));
        double appBottom=VTB_PAD;
        walkAppLayout(reg.buttons,800,[&](size_t i,double y) {
            if(!reg.buttons[i].bottom)
                appBottom=std::max(appBottom,y+(reg.buttons[i].isSep()?VTB_SEP_H:cellSize()));
        });
        assert(near(track.y,appBottom+VTB_PAD+(footerBottom?0:20)));
        assert(near(track.y+track.h,800-bottomGroupH(reg.buttons)-VTB_PAD-(footerBottom?20:0)));
        assert(near(deco.titleEndLocal(800),798));
    }
    std::cout<<"PASS compact seekbar/title/button separation, four-edge transforms, wheel direction, fractional accumulation, rails, and noncompact geometry\n";
}
'''
with tempfile.TemporaryDirectory(prefix='vtb-playbar-') as tmp:
    cpp = Path(tmp) / 'test.cpp'
    exe = Path(tmp) / 'test'
    cpp.write_text(code)
    subprocess.run([os.environ.get('CXX','g++'), '-std=c++23', '-Wall', '-Wextra', str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
