import { chromium } from 'playwright-core';
import { build } from 'esbuild';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
if (process.env.DISPLAY || process.env.WAYLAND_DISPLAY || process.env.DBUS_SESSION_BUS_ADDRESS
  || process.env.QT_QPA_PLATFORM !== 'offscreen') throw new Error('run through test.sh');
const dir = await mkdtemp(join(tmpdir(), 'collage-test-'));
let browser;
try {
  const bundle = await build({ stdin: { contents: "export * from './src/engine.js'; export {Output, BufferTarget, WebMOutputFormat, CanvasSource} from 'mediabunny';", resolveDir: process.cwd() }, bundle: true, write: false,
    format: 'iife', globalName: 'CollageEngine' });
  const browserPath = process.env.COLLAGE_BROWSER || execFileSync('which', ['chromium'], {encoding:'utf8'}).trim();
  browser = await chromium.launch({ executablePath: browserPath, headless: true,
    args: ['--disable-gpu', '--no-first-run', '--disable-background-networking', '--disable-extensions', '--disable-dev-shm-usage'] });
  const page = await browser.newPage();
  await page.route('**/*', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>isolated collage test</title>' }));
  await page.goto('http://localhost/');
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  const result = await page.evaluate(async () => {
    const E = CollageEngine;
    const makeImage = async color => { const {canvas,ctx}=E.canvas(320,240); ctx.fillStyle=color;ctx.fillRect(0,0,320,240);return E.canvasBlob(canvas,'image/png'); };
    const red = await makeImage('#d03030'), gray = await makeImage('#808080');
    const opts = { edge:320, duration:1, fps:30, maxBytes:1_000_000 };
    const array = async r => ({...r, blob:undefined, bytes:Array.from(new Uint8Array(await r.blob.arrayBuffer()))});
    const still = await E.exportCollage([red,gray],{...opts,format:'png'});
    const video = await E.exportCollage([red,gray], opts);
    const pattern=E.canvas(320,240), target=new E.BufferTarget();
    const out=new E.Output({format:new E.WebMOutputFormat(),target});
    const source=new E.CanvasSource(pattern.canvas,{codec:'vp8',bitrate:1_000_000,latencyMode:'quality'});
    out.addVideoTrack(source,{frameRate:10}); await out.start();
    for(let i=0;i<4;i++) {pattern.ctx.fillStyle=['#101010','#808080','#e0e0e0','#d03030'][i];pattern.ctx.fillRect(0,0,320,240);await source.add(i/10,0.1);}
    source.close();await out.finalize();const input=new Blob([target.buffer],{type:'video/webm'});
    const delayed = await E.exportCollage([input], {...opts,duration:2}, undefined, () => {
      // Deliberately miss the real-time frame budget; output must stay CFR.
      const stop = performance.now()+40; while(performance.now()<stop) {}
    });
    const ac = new AbortController(); let cancelled=false;
    try { await E.exportCollage([input], {...opts,duration:2}, ac.signal, t => {
      if(t.includes('frame 3/')) ac.abort(new DOMException('cancelled','AbortError'));
    }); } catch { cancelled=ac.signal.aborted; }
    let sizeRejected=false;
    try { E.options({...opts,maxBytes:1}); } catch { sizeRejected=true; }
    const withHeader = E.layout([{width:640,height:100},{width:320,height:240},{width:240,height:320}],640,1,true);
    if(withHeader.placements[0].width!==withHeader.width || withHeader.placements[1].y<withHeader.placements[0].height) throw new Error('header layout');
    const encoder=globalThis.VideoEncoder; globalThis.VideoEncoder=undefined;
    let unsupported=false;
    try {await E.exportCollage([red],opts);} catch(e) {unsupported=e.message.includes('no WebCodecs');}
    const withoutEncoder=await E.exportCollage([red],{...opts,format:'jpeg'});
    globalThis.VideoEncoder=encoder;
    return {still:await array(still),video:await array(video),delayed:await array(delayed),cancelled,sizeRejected,unsupported,imageFallback:withoutEncoder.blob.type==='image/jpeg'};
  });
  assert(result.cancelled); assert(result.sizeRejected);assert(result.unsupported);assert(result.imageFallback);
  for (const name of ['still','video','delayed']) {
    const r=result[name], file=join(dir,`${name}.${r.extension}`);
    await writeFile(file,new Uint8Array(r.bytes));
    const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-show_format','-of','json',file],{encoding:'utf8'}));
    const s=probe.streams[0]; assert.equal(s.width,r.width);assert.equal(s.height,r.height);
    if(r.frames) {
      assert.equal(Number(s.nb_read_frames),r.frames);
      assert.equal(Number(probe.format.duration),r.duration);
      const frames=JSON.parse(execFileSync('ffprobe',['-v','error','-select_streams','v','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',file],{encoding:'utf8'})).frames;
      frames.forEach((f,i)=>assert(Math.abs(Number(f.best_effort_timestamp_time)-i/r.fps)<0.0011));
      if(name==='delayed') {
        const pixels=execFileSync('ffmpeg',['-v','error','-i',file,'-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'],{maxBuffer:1_000_000});
        const colors=[[16,16,16],[128,128,128],[224,224,224],[208,48,48]];
        for(let i=0;i<60;i++) for(let channel=0;channel<3;channel++)
          assert(Math.abs(pixels[i*3+channel]-colors[Math.floor(i/3)%4][channel])<=8,
            `source timing/colour mismatch at frame ${i}: ${pixels.subarray(i*3,i*3+3)}`);
      }
    }
    console.log(name, {bytes:r.bytes.length,width:s.width,height:s.height,frames:s.nb_read_frames,duration:probe.format.duration,color:s.color_space});
  }
  // Exercise the installed artifact's UI in an isolated page; no real-site requests.
  await page.addScriptTag({ content:await readFile('collage.user.js','utf8') });
  await page.locator('#ldg-collage-v2').getByRole('button',{name:'collage',exact:true}).click();
  await page.locator('#ldg-collage-v2').getByLabel('add files').setInputFiles(join(dir,'still.png'));
  await page.locator('#ldg-collage-v2').getByLabel('output',{exact:true}).selectOption('png');
  await page.locator('#ldg-collage-v2').getByRole('button',{name:'export selected'}).click();
  await page.locator('#ldg-collage-v2').getByRole('link',{name:/save collage/}).waitFor();
  console.log('UI image export, slow export, looping, cancellation, frame counts and timestamps passed');
} finally { await browser?.close(); await rm(dir,{recursive:true,force:true}); }
