const { chromium, firefox, webkit } = await import(process.env.COLLAGE_PLAYWRIGHT || 'playwright-core');
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
const watchdog = setTimeout(() => { console.error('test timed out'); browser?.close(); }, 90000);
try {
  const bundle = await build({ stdin: { contents: "export * from './src/engine.js'; export {Output, BufferTarget, WebMOutputFormat, Mp4OutputFormat, CanvasSource} from 'mediabunny';", resolveDir: process.cwd() }, bundle: true, write: false,
    format: 'iife', globalName: 'CollageEngine' });
  const engine = process.env.COLLAGE_ENGINE || 'chromium';
  const driver = {chromium, firefox, webkit}[engine];
  if (!driver) throw new Error('invalid COLLAGE_ENGINE');
  const browserPath = process.env.COLLAGE_BROWSER || (process.env.PLAYWRIGHT_BROWSERS_PATH ? undefined
    : execFileSync('which', [engine], {encoding:'utf8'}).trim());
  browser = await driver.launch({ executablePath: browserPath, headless: true,
    ...(engine === 'chromium' ? {args: ['--disable-gpu', '--no-first-run', '--disable-background-networking', '--disable-extensions', '--disable-dev-shm-usage']} : {}) });
  console.log('browser',engine,browser.version());
  const page = await browser.newPage();
  console.log('isolated page created');
  if(process.env.COLLAGE_CPU_RATE) {
    if(engine!=='chromium') throw new Error('CPU throttling requires Chromium');
    const cdp=await page.context().newCDPSession(page);
    await cdp.send('Emulation.setCPUThrottlingRate',{rate:Number(process.env.COLLAGE_CPU_RATE)});
    console.log('CPU throttle',process.env.COLLAGE_CPU_RATE);
  }
  page.on('console',message=>console.log('page:',message.text()));
  await page.route('**/*', route => route.request().url().startsWith('blob:') ? route.continue()
    : route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>isolated collage test</title>' }));
  await page.goto('http://localhost/');
  await page.addScriptTag({ content: bundle.outputFiles[0].text });
  const result = await page.evaluate(async () => {
    const E = CollageEngine;
    const makeImage = async color => { const {canvas,ctx}=E.canvas(320,240); ctx.fillStyle=color;ctx.fillRect(0,0,320,240);return E.canvasBlob(canvas,'image/png'); };
    const red = await makeImage('#d03030'), gray = await makeImage('#808080');
    const iframe=document.createElement('iframe');document.body.append(iframe);
    const foreign=new iframe.contentWindow.Blob([await red.arrayBuffer()],{type:red.type});
    const normalized=E.normalizeBlob(foreign);iframe.remove();
    if(!(normalized instanceof Blob) || normalized.size!==red.size) throw new Error('cross-realm blob');
    const opts = { edge:320, duration:1, fps:30, maxBytes:1_000_000 };
    const probes=[];
    const fallback=await E.selectCodec('webm',320,240,1_000_000,async (c,o)=>{probes.push([c,o]);return c==='vp9';});
    if(fallback!=='vp9' || probes.length!==2 || probes.some(([,o])=>o.latencyMode!=='quality' || o.hardwareAcceleration!=='no-preference')) throw new Error('codec probing');
    if(await E.selectCodec('mp4',320,240,1_000_000,async c=>c==='avc')!=='avc') throw new Error('mp4 probing');
    let unavailable=false;
    try {await E.selectCodec('webm',320,240,1_000_000,async()=>false);} catch(e) {unavailable=e.message.includes('try mp4');}
    if(!unavailable) throw new Error('unsupported format error');
    const array = async r => ({...r, blob:undefined, bytes:Array.from(new Uint8Array(await r.blob.arrayBuffer()))});
    console.log('image export');
    const still = await E.exportCollage([red,gray],{...opts,format:'png'});
    if((await E.exportCollage([red],{...opts,format:'auto'})).extension!=='jpg') throw new Error('automatic image format');
    const supported={};
    for(const format of ['webm','mp4']) {
      try {supported[format]=await E.selectCodec(format,212,318,7_040_000);} catch(e) {console.log(format,e.message);}
    }
    if(!supported.webm && !supported.mp4) {
      let rejected=false;
      try {await E.exportCollage([red],opts);} catch(e) {rejected=/cannot encode|no WebCodecs/.test(e.message);}
      if(!rejected) throw new Error('missing codec not rejected');
      return {still:await array(still),videoUnavailable:true};
    }
    opts.format=supported.webm ? 'webm' : 'mp4';
    console.log('video export',opts.format);
    const video = await E.exportCollage([red,gray], opts);
    console.log('mp4 export');
    let mp4, mp4Unavailable;
    try {await E.selectCodec('mp4',212,318,7_040_000);} catch(e) {mp4Unavailable=e.message;}
    if(!mp4Unavailable) mp4=await E.exportCollage([red,gray], {...opts,format:'mp4'});
    const pattern=E.canvas(320,240), target=new E.BufferTarget();
    console.log('source fixture');
    const out=new E.Output({format:opts.format==='webm' ? new E.WebMOutputFormat() : new E.Mp4OutputFormat(),target});
    const source=new E.CanvasSource(pattern.canvas,{codec:supported[opts.format],bitrate:1_000_000,latencyMode:'quality'});
    out.addVideoTrack(source,{frameRate:10}); await out.start();
    for(let i=0;i<4;i++) {pattern.ctx.fillStyle=['#101010','#808080','#e0e0e0','#d03030'][i];pattern.ctx.fillRect(0,0,320,240);await source.add(i/10,0.1);}
    source.close();await out.finalize();const input=new Blob([target.buffer],{type:`video/${opts.format}`});
    const delayed = await E.exportCollage([input], {...opts,format:supported.webm ? 'auto' : 'mp4',duration:2}, undefined, () => {
      // Deliberately miss the real-time frame budget; output must stay CFR.
      const stop = performance.now()+40; while(performance.now()<stop) {}
    });
    console.log('cancellation');
    const ac = new AbortController(); let cancelled=false;
    try { await E.exportCollage([input], {...opts,duration:2}, ac.signal, t => {
      if(t.includes('frame 3/')) ac.abort(new DOMException('cancelled','AbortError'));
    }); } catch { cancelled=ac.signal.aborted; }
    const mixed = await E.exportCollage([input,input,red,gray],{...opts,edge:1280,fps:60});
    if((await E.exportCollage([input],{...opts,format:'png'})).extension!=='png') throw new Error('explicit image override');
    if(mixed.frames!==60 || mixed.fps!==60 || Math.max(mixed.width,mixed.height)<1278)
      throw new Error('requested output settings changed');
    let sizeRejected=false;
    try { E.options({...opts,maxBytes:1}); } catch { sizeRejected=true; }
    const withHeader = E.layout([{width:640,height:100},{width:320,height:240},{width:240,height:320}],640,1,true);
    if(withHeader.placements[0].width!==withHeader.width || withHeader.placements[1].y<withHeader.placements[0].height) throw new Error('header layout');
    const encoder=globalThis.VideoEncoder; globalThis.VideoEncoder=undefined;
    let unsupported=false;
    try {await E.exportCollage([red],opts);} catch(e) {unsupported=e.message.includes('no WebCodecs');}
    const withoutEncoder=await E.exportCollage([red],{...opts,format:'jpeg'});
    globalThis.VideoEncoder=encoder;
    return {still:await array(still),video:await array(video),delayed:await array(delayed),mixed:await array(mixed),mp4:mp4 && await array(mp4),mp4Unavailable,cancelled,sizeRejected,unsupported,imageFallback:withoutEncoder.blob.type==='image/jpeg'};
  });
  if(!result.videoUnavailable) {
    assert(result.cancelled); assert(result.sizeRejected);assert(result.unsupported);assert(result.imageFallback);
  }
  console.log('mp4',result.mp4 ? 'supported' : result.mp4Unavailable || 'unavailable');
  for (const name of ['still','video','delayed','mixed','mp4'].filter(name=>result[name])) {
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
  await page.goto('http://localhost/');
  await page.addScriptTag({ content:await readFile('collage.user.js','utf8') });
  await page.locator('#ldg-collage-v2').getByRole('button',{name:'collage',exact:true}).click();
  const ui=page.locator('#ldg-collage-v2');
  assert.equal(await ui.locator('#advanced').getAttribute('open'),null);
  assert(await ui.getByLabel('scale',{exact:true}).isVisible());
  assert(await ui.getByLabel('aspect ratio',{exact:true}).isVisible());
  assert(!(await ui.getByLabel('output',{exact:true}).isVisible()));
  await ui.getByRole('button',{name:'collage',exact:true}).click();
  assert(!(await ui.locator('#panel').isVisible()));
  await ui.getByRole('button',{name:'collage',exact:true}).click();
  await ui.locator('summary').click();
  await page.locator('#ldg-collage-v2').getByLabel('add files').setInputFiles(join(dir,'still.png'));
  await page.locator('#ldg-collage-v2').getByLabel('output',{exact:true}).selectOption('mp4');
  assert(await page.locator('#ldg-collage-v2').getByLabel('fps',{exact:true}).isEnabled());
  await page.locator('#ldg-collage-v2').getByLabel('output',{exact:true}).selectOption('png');
  await ui.getByLabel('scale',{exact:true}).selectOption('640');
  await ui.getByLabel('aspect ratio',{exact:true}).selectOption('0.5625');
  await ui.locator('summary').click();
  await page.locator('#ldg-collage-v2').getByRole('button',{name:'create collage'}).click();
  await page.locator('#ldg-collage-v2').getByRole('link',{name:/save collage/}).waitFor();
  await ui.getByRole('button',{name:'preview collage 1'}).click();
  assert(await ui.getByRole('dialog',{name:'collage preview',exact:true}).isVisible());
  assert(await ui.locator('#panel').evaluate(el=>el.inert));
  await ui.getByRole('button',{name:'close preview'}).press('Escape');
  assert(!(await ui.locator('#preview').isVisible()));
  assert(!(await ui.locator('#panel').evaluate(el=>el.inert)));
  if(result.video && result.video.extension==='webm') {
    await ui.locator('summary').click();
    await ui.getByLabel('add files').setInputFiles(join(dir,'delayed.webm'));
    await ui.getByLabel('header image').setInputFiles(join(dir,'still.png'));
    await ui.getByLabel('output',{exact:true}).selectOption('auto');
    await ui.getByLabel('fps',{exact:true}).selectOption('24');
    await ui.getByLabel('seconds',{exact:true}).fill('1');
    await ui.getByLabel('limit (MB)',{exact:true}).fill('0.5');
    await ui.getByLabel('collages',{exact:true}).fill('2');
    await ui.locator('summary').click();
    await ui.getByRole('button',{name:'create collage'}).click();
    const second=ui.getByRole('link',{name:/save collage 2/});
    await second.waitFor();
    assert((await second.getAttribute('download')).endsWith('.webm'));
    assert((await second.innerText()).includes('24 frames at 24 fps'));
    assert((await ui.getByRole('link',{name:/save collage 1/}).getAttribute('download')).endsWith('.jpg'));
    await ui.getByRole('button',{name:'preview collage 2'}).click();
    assert(await ui.locator('#preview video').isVisible());
    assert(await ui.locator('#preview video').evaluate(v=>v.controls && v.muted));
    await ui.getByRole('button',{name:'close preview'}).click();
    assert.equal(await ui.locator('#preview video').count(),0);
  }
  await ui.getByRole('button',{name:'close collage',exact:true}).click();
  assert(!(await ui.locator('#panel').isVisible()));
  console.log(result.videoUnavailable ? 'UI image export passed; video unavailable in this browser build'
    : 'UI image export, slow export, looping, cancellation, frame counts and timestamps passed');
} finally { clearTimeout(watchdog); await browser?.close(); await rm(dir,{recursive:true,force:true}); }
