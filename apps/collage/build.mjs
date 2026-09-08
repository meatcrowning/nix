import { build } from 'esbuild';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const { version, dependencies } = JSON.parse(await readFile('package.json', 'utf8'));
const libraryPath = 'dist/bundles/mediabunny.cjs';
const integrity = createHash('sha256').update(await readFile(`node_modules/mediabunny/${libraryPath}`)).digest('hex');
const header = `// ==UserScript==
// @name         ldg collage
// @namespace    ldg-collage
// @version      ${version}
// @description  Image and fixed-frame-rate video collages, entirely in your browser
// @match        https://boards.4chan.org/*/thread/*
// @match        https://boards.4channel.org/*/thread/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @require      https://cdn.jsdelivr.net/npm/mediabunny@${dependencies.mediabunny}/${libraryPath}#sha256=${integrity}
// @connect      i.4cdn.org
// @connect      files.catbox.moe
// @connect      litter.catbox.moe
// @connect      uguu.se
// @run-at       document-idle
// ==/UserScript==
// Selection workflow inspired by https://rentry.org/yueessiz,
// https://rentry.org/ldgcollage and https://rentry.org/ldgcollage_v2.
// Media processing stays in your browser; no server or external application.
// Mediabunny ${dependencies.mediabunny} (MPL-2.0) is loaded separately by the userscript manager.
// Library source: https://github.com/Vanilagy/mediabunny
// Collage source: https://github.com/meatcrowning/nix/tree/main/apps/collage/src`;
await build({ entryPoints: ['src/ui.js'], bundle: true, minify: false,
  target: ['chrome106', 'firefox130', 'safari16.4'], format: 'iife',
  outfile: 'collage.user.js', banner: { js: header }, legalComments: 'inline' });
