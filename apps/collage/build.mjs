import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';
const header = `// ==UserScript==
// @name         ldg collage
// @namespace    ldg-collage
// @version      2.2.0
// @description  Image and fixed-frame-rate video collages, entirely in your browser
// @match        https://boards.4chan.org/*/thread/*
// @match        https://boards.4channel.org/*/thread/*
// @grant        GM_xmlhttpRequest
// @connect      i.4cdn.org
// @connect      files.catbox.moe
// @connect      litter.catbox.moe
// @connect      uguu.se
// @run-at       document-idle
// ==/UserScript==
// Selection workflow inspired by https://rentry.org/yueessiz,
// https://rentry.org/ldgcollage and https://rentry.org/ldgcollage_v2.
// New implementation. No runtime CDN, server, or external application.
// Bundles unmodified Mediabunny 1.55.7 (MPL-2.0), source available at
// https://www.npmjs.com/package/mediabunny/v/1.55.7 and
// https://github.com/Vanilagy/mediabunny.
/* ${await readFile('node_modules/mediabunny/LICENSE', 'utf8')} */`;
await build({ entryPoints: ['src/ui.js'], bundle: true, minify: true,
  target: ['chrome106', 'firefox130', 'safari16.4'], format: 'iife',
  outfile: 'collage.user.js', banner: { js: header }, legalComments: 'inline' });
