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
  const runtimeErrors=[];page.on('pageerror',e=>runtimeErrors.push(e.message));
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
    // VFR, fractional start offsets, final-frame hold and multiple loop boundaries.
    let live=0,peak=0;
    const offsets=[0,0.04,0.11,0.2], start=0.1234567;
    const reader=E.videoReader({start,duration:0.25},undefined,()=>{
      let i=0;return {async next(){if(i===offsets.length)return {done:true};live++;peak=Math.max(peak,live);let closed=false;return {value:{timestamp:start+offsets[i++],close(){if(closed)throw Error('double close');closed=true;live--;}}};},async return(){}};
    });
    try {for(let i=0;i<60;i++) {
      const sample=await reader.at(i,60), time=(i%15)/60;
      const expected=start+offsets.filter(t=>t<=time+1e-7).at(-1);
      if(Math.abs(sample.timestamp-expected)>1e-9)throw Error('VFR resampling/looping');
    }}finally{await reader.close();}
    if(live || peak>2)throw Error('video reader leaked or retained excess frames');
    for(const [text,expected] of [['2:3',2/3],['0.5',0.5],['3/7',3/7],['16 x 9',16/9],['.25',.25]])
      if(Math.abs(E.parseAspect(text)-expected)>1e-12) throw new Error('aspect parser');
    for(const bad of ['1/0','0','-1','Infinity','1:2:3','alert(1)']) {
      let rejected=false;try{E.parseAspect(bad);}catch{rejected=true;}if(!rejected)throw new Error('invalid ratio accepted');
    }
    const ratioLayout=E.layout([{width:320,height:240}],1280,3/7);
    if(Math.abs(ratioLayout.width/ratioLayout.height-3/7)>0.002)throw new Error('output aspect ratio');
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
    const shortAuto=await E.exportCollage([input],{...opts,duration:'auto'});
    if(shortAuto.frames!==12 || shortAuto.duration!==0.4)throw new Error('automatic short duration');
    const delayed = await E.exportCollage([input], {...opts,format:supported.webm ? 'auto' : 'mp4',duration:2}, undefined, () => {
      // Deliberately miss the real-time frame budget; output must stay CFR.
      const stop = performance.now()+40; while(performance.now()<stop) {}
    });
    const longestAuto=await E.exportCollage([input,delayed.blob],{...opts,duration:'auto'});
    if(longestAuto.frames!==60 || longestAuto.duration!==2)throw new Error('longest source duration');
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
    if(withHeader.placements[1].y<withHeader.placements[0].y+withHeader.placements[0].height) throw new Error('header layout');
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
  if(!result.videoUnavailable) {
    // A P-frame before a keyframe in presentation order can follow B-frames in
    // decode order. The former sparse lookup failed at precisely output frame 306.
    const bframes=join(dir,'bframes.mp4');
    execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=24:duration=12','-c:v','libx264','-threads','2','-x264-params','keyint=245:min-keyint=245:scenecut=0:bframes=3:b-adapt=0','-crf','18',bframes]);
    await page.evaluate(()=>{const el=document.createElement('input');el.type='file';el.id='regression';document.body.append(el);});
    await page.locator('#regression').setInputFiles(bframes);
    const regression=await page.evaluate(async()=>{
      const E=CollageEngine,file=document.querySelector('#regression').files[0];let m;
      try {m=await E.prepare(file);} catch(e) {
        if(e.message==='this browser cannot decode this video codec')return {unsupported:true};
        throw e;
      }
      const reader=E.videoReader(m);let checked=0;
      try {for(let i=0;i<360;i++) {
        const sample=await reader.at(i,30);
        if(Math.abs(sample.timestamp-Math.floor(i*24/30)/24)>1e-6)throw Error(`B-frame timing at output frame ${i+1}: ${sample.timestamp}`);
        checked++;
      }}finally{await reader.close();m.dispose();}
      const r=await E.exportCollage([file],{format:'webm',edge:320,aspect:4/3,duration:12,fps:30,maxBytes:2e6});
      return {checked,frames:r.frames,bytes:Array.from(new Uint8Array(await r.blob.arrayBuffer()))};
    });
    if(regression.unsupported) console.log('B-frame regression skipped: this browser build has no H.264 decoder');
    else {
      assert.equal(regression.checked,360); assert.equal(regression.frames,360);
      await writeFile(join(dir,'bframes.webm'),new Uint8Array(regression.bytes));
      const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-of','json',join(dir,'bframes.webm')],{encoding:'utf8'}));
      assert.equal(Number(probe.streams[0].nb_read_frames),360);
      console.log('B-frame boundary regression: 360 correctly sampled and encoded frames');
    }
  }
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
        const pixels=execFileSync('ffmpeg',['-v','error','-i',file,'-vf','crop=2:2:(iw-2)/2:(ih-2)/2,scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'],{maxBuffer:1_000_000});
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
  await page.evaluate(()=>{document.body.innerHTML='<div class="file" style="font:13px sans-serif"><div class="fileText">File: example.png (2.83 MB, 3344x2512)</div><a class="fileThumb" href="https://i.4cdn.org/g/0.png">thumbnail</a></div>';});
  const rowBefore=await page.locator('.fileText').boundingBox();
  await page.evaluate(()=>{for(let i=0;i<70;i++){const a=document.createElement('a');a.className='fileThumb';a.href=`https://i.4cdn.org/g/${i}.png`;document.body.append(a);}});
  await page.addScriptTag({ content:await readFile('collage.user.js','utf8') });
  assert.equal(await page.locator('.fileText [data-ldg-mark]').count(),1);
  assert.equal(await page.locator('.fileText [data-ldg-mark]').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(255, 255, 0)');
  assert.equal((await page.locator('.fileText').boundingBox()).height,rowBefore.height);
  // X/XT-style sauce links can exist before installation or arrive afterward.
  await page.evaluate(()=>{
    const file=document.createElement('div');file.className='file';file.id='extension-file';file.style.font='13px sans-serif';
    file.innerHTML='<div class="fileText"><span class="file-info">example.png (1 MB, 320x240)</span><span class="fileText-original" hidden>original</span> <a class="sauce" href="https://example.invalid/">google</a> <a class="sauce" href="https://example.invalid/y">yandex</a></div><a class="fileThumb" href="https://i.4cdn.org/g/0.png">thumbnail</a>';
    document.body.append(file);
  });
  await page.waitForFunction(()=>document.querySelector('#extension-file .file-info').nextSibling?.matches?.('[data-ldg-mark]'));
  assert.equal(await page.locator('#extension-file [data-ldg-mark]').count(),1);
  await page.evaluate(()=>{const info=document.querySelector('#extension-file .fileText');info.innerHTML='example.png (1 MB, 320x240) <a class="sauce" href="https://example.invalid/">google</a>';});
  await page.waitForFunction(()=>document.querySelector('#extension-file a.sauce').previousSibling?.matches?.('[data-ldg-mark]'));
  assert.equal(await page.locator('#extension-file [data-ldg-mark]').count(),1);
  assert.equal(await page.locator('#extension-file a.sauce').getAttribute('href'),'https://example.invalid/');
  await page.evaluate(()=>{const copy=document.querySelector('#extension-file').cloneNode(true);copy.id='extension-clone';document.body.append(copy);});
  await page.waitForFunction(()=>typeof document.querySelector('#extension-clone [data-ldg-mark]')?.onclick==='function');
  assert.equal(await page.locator('#extension-clone [data-ldg-mark]').count(),1);
  const downloads=[]; page.on('download',d=>downloads.push(d));
  await page.locator('#ldg-collage-v2').getByRole('button',{name:'collage',exact:true}).click();
  const ui=page.locator('#ldg-collage-v2');
  assert.equal(await ui.locator('#panel').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(32, 33, 36)');
  assert(['rgb(48, 49, 52)','rgb(65, 67, 72)'].includes(await ui.locator('#open').evaluate(el=>getComputedStyle(el).backgroundColor)));
  assert.equal(await ui.locator('#advanced').getAttribute('open'),null);
  assert(await ui.getByLabel('scale',{exact:true}).isVisible());
  assert(await ui.getByLabel('aspect ratio',{exact:true}).isVisible());
  assert(!(await ui.getByLabel('output',{exact:true}).isVisible()));
  await ui.getByRole('button',{name:'collage',exact:true}).click();
  assert(!(await ui.locator('#panel').isVisible()));
  await ui.getByRole('button',{name:'collage',exact:true}).click();
  await ui.locator('summary').click();
  await ui.getByRole('button',{name:'select all',exact:true}).click();
  await ui.getByRole('button',{name:'create collage'}).click();
  assert((await ui.locator('#message').innerText()).includes('at most 64'));
  await ui.locator('#panel').evaluate(el=>{el.scrollTop=el.scrollHeight;});
  const panelBounds=await ui.locator('#panel').boundingBox();
  for(const selector of ['#close','#message']) {
    const bounds=await ui.locator(selector).boundingBox();
    assert(bounds.y>=panelBounds.y && bounds.y+bounds.height<=panelBounds.y+panelBounds.height);
  }
  await ui.getByRole('button',{name:'select none',exact:true}).click();
  await page.locator('#ldg-collage-v2').getByLabel('add files').setInputFiles(join(dir,'still.png'));
  assert.equal(await ui.locator('.tile').count(),71);
  assert.equal(await ui.getByRole('button',{name:'move earlier'}).count(),0);
  await ui.getByLabel('gallery view').selectOption('selected');
  assert.equal(await ui.locator('.tile:visible').count(),1);
  await ui.getByRole('button',{name:'preview still.png',exact:true}).click();
  assert(await ui.getByRole('dialog',{name:'media preview',exact:true}).isVisible());
  await ui.locator('#preview img').click();
  assert(!(await ui.locator('#preview').isVisible()));
  await ui.locator('.tile:visible input').uncheck();
  assert.equal(await ui.locator('.tile:visible').count(),0);
  await ui.getByLabel('gallery view').selectOption('all');
  await ui.locator('.tile input').last().check();
  await ui.getByLabel('gallery view').selectOption('selected');
  await page.locator('#ldg-collage-v2').getByLabel('output',{exact:true}).selectOption('mp4');
  assert(await page.locator('#ldg-collage-v2').getByLabel('fps',{exact:true}).isEnabled());
  await page.locator('#ldg-collage-v2').getByLabel('output',{exact:true}).selectOption('png');
  await ui.getByLabel('scale',{exact:true}).evaluate(el=>{el.value='640';el.dispatchEvent(new Event('input',{bubbles:true}));});
  assert((await ui.locator('#scale-value').innerText()).includes('640px'));
  await ui.getByLabel('aspect ratio',{exact:true}).fill('3/7');
  // Disabled seconds must not invalidate image output.
  await ui.locator('#duration').evaluate(el=>{el.value='999';});
  await ui.locator('summary').click();
  const imageDownload=page.waitForEvent('download');
  await ui.getByRole('button',{name:'create collage'}).click();
  const savedImage=await imageDownload;
  assert(savedImage.suggestedFilename().endsWith('.png'));
  await savedImage.saveAs(join(dir,'ui.png'));
  assert.equal(await savedImage.failure(),null);
  assert.equal(await ui.locator('#results').count(),0);
  assert.equal(await ui.getByRole('link').count(),0);
  assert((await ui.locator('#message').innerText()).includes('download requested'));
  if(result.video && result.video.extension==='webm') {
    await ui.locator('summary').click();
    await ui.getByLabel('add files').setInputFiles(join(dir,'delayed.webm'));
    await ui.getByRole('button',{name:'preview delayed.webm',exact:true}).click();
    assert(await ui.locator('#preview video').isVisible());
    await ui.locator('#preview').click({position:{x:5,y:5}});
    assert(!(await ui.locator('#preview').isVisible()));
    await ui.getByLabel('header image').setInputFiles(join(dir,'still.png'));
    await ui.getByLabel('output',{exact:true}).selectOption('auto');
    await ui.getByLabel('fps',{exact:true}).selectOption('24');
    await ui.getByLabel('seconds',{exact:true}).fill('1');
    await ui.getByLabel('limit (MB)',{exact:true}).fill('0.5');
    await ui.getByLabel('collages',{exact:true}).fill('2');
    await ui.locator('summary').click();
    await ui.getByRole('button',{name:'create collage'}).click();
    await page.waitForFunction(()=>document.querySelector('#ldg-collage-v2').shadowRoot.querySelector('#message').textContent.includes('2 downloads requested'));
    for(let i=0;i<100 && downloads.length<3;i++) await new Promise(resolve=>setTimeout(resolve,50));
    assert.equal(downloads.length,3);
    assert(downloads[1].suggestedFilename().endsWith('.jpg'));
    assert(downloads[2].suggestedFilename().endsWith('.webm'));
    await downloads[2].saveAs(join(dir,'ui.webm'));
    assert.equal(await downloads[2].failure(),null);
    const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-count_frames','-show_streams','-of','json',join(dir,'ui.webm')],{encoding:'utf8'}));
    assert.equal(Number(probe.streams[0].nb_read_frames),24);
    // Nine actual video inputs now warn instead of failing; verify every dismissal path.
    await ui.getByRole('button',{name:'select none',exact:true}).click();
    await ui.locator('summary').click();
    const videoBytes=await readFile(join(dir,'delayed.webm'));
    await ui.getByLabel('add files').setInputFiles(Array.from({length:9},(_,i)=>({name:`large-${i}.webm`,mimeType:'video/webm',buffer:videoBytes})));
    await ui.getByLabel('collages',{exact:true}).fill('1');
    await ui.getByLabel('seconds',{exact:true}).fill('0.1');
    await ui.locator('summary').click();
    await ui.getByRole('button',{name:'create collage'}).click();
    await ui.getByRole('dialog',{name:'large video collage'}).waitFor();
    assert((await ui.locator('#warning-text').innerText()).includes('9 videos'));
    assert(await page.locator('#extension-file [data-ldg-mark]').isDisabled());
    await ui.getByRole('button',{name:'continue rendering',exact:true}).press('Escape');
    await page.waitForFunction(()=>document.querySelector('#ldg-collage-v2').shadowRoot.querySelector('#message').textContent==='cancelled');
    assert.equal(downloads.length,3);
    assert(await page.locator('#extension-file [data-ldg-mark]').isEnabled());
    for (const permanent of [false,true]) {
      await ui.getByRole('button',{name:'create collage'}).click();
      await ui.getByRole('dialog',{name:'large video collage'}).waitFor();
      if(permanent) await ui.getByLabel("don't warn me again").check();
      const downloaded=page.waitForEvent('download');
      await ui.getByRole('button',{name:'continue rendering',exact:true}).click();
      assert((await downloaded).suggestedFilename().endsWith('.webm'));
    }
    assert.equal(await page.evaluate(()=>localStorage.getItem('ldg-collage-hide-large-video-warning')),'true');
    const downloaded=page.waitForEvent('download');
    await ui.getByRole('button',{name:'create collage'}).click();
    await downloaded;
    assert(!(await ui.getByRole('dialog',{name:'large video collage'}).isVisible()));
  }
  await ui.getByLabel('gallery view').selectOption('all');
  await ui.locator('.tile input').first().check();
  await ui.getByRole('button',{name:'Clear imported',exact:true}).click();
  assert.equal(await ui.locator('.tile').count(),70);
  assert(await ui.locator('.tile input').first().isChecked());
  assert.equal(await ui.locator('#header').evaluate(el=>el.files.length),0);
  assert((await page.evaluate(()=>localStorage.getItem('ldg-collage-v2:/'))).includes('https://i.4cdn.org/g/0.png'));
  await ui.getByRole('button',{name:'close collage',exact:true}).click();
  assert(!(await ui.locator('#panel').isVisible()));
  console.log(result.videoUnavailable ? 'UI image export passed; video unavailable in this browser build'
    : 'UI image export, slow export, looping, cancellation, frame counts and timestamps passed');
  assert.deepEqual(runtimeErrors,[]);
} finally { clearTimeout(watchdog); await browser?.close(); await rm(dir,{recursive:true,force:true}); }
