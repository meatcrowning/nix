import React from 'react';
import pc from './logos/pc.svg';
import psx from './logos/psx.svg';
import ps2 from './logos/ps2.svg';
import psp from './logos/psp.svg';
import gc from './logos/gc.svg';
import gb from './logos/gb.svg';
import gba from './logos/gba.svg';
import nes from './logos/nes.svg';
import snes from './logos/snes.svg';
import n64 from './logos/n64.svg';

const logos = { PC: pc, PlayStation: psx, 'PlayStation 2': ps2, PSP: psp,
  'PlayStation Portable': psp, GameCube: gc, 'Game Boy': gb, 'Game Boy Advance': gba,
  NES: nes, 'Nintendo Entertainment System': nes, SNES: snes,
  'Super Nintendo Entertainment System': snes, 'Nintendo 64': n64, N64: n64 };
export function SystemIcon({ system }) {
  return logos[system] ? <img className="hlg-system-icon" src={logos[system]} alt="" aria-hidden="true" /> : null;
}
