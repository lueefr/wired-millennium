// Offline Chromium smoke test via CDP; no npm dependencies and no Steam requests.
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const directory=await mkdtemp(join(tmpdir(),'wired-ui-'));
const browser=spawn(process.env.CHROMIUM||'chromium',['--headless=new','--no-sandbox','--disable-gpu','--disable-background-networking','--no-first-run','--remote-debugging-port=0',`--user-data-dir=${directory}`,'about:blank'],{stdio:'ignore'});
let ws;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(fn,message){for(let n=0;n<150;n++){const result=await fn();if(result)return result;await delay(100);}throw Error(message);}
try{
  const port=await until(async()=>{try{return (await readFile(join(directory,'DevToolsActivePort'),'utf8')).split('\n')[0];}catch{return null;}},'Chromium did not start');
  const pages=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
  let sequence=0;const pending=new Map();const errors=[];
  const call=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
  const source=await readFile(new URL('../public/webkit.js',import.meta.url),'utf8');
  const fixture=`<!doctype html><html><head><style>
  body{font-family:sans-serif}.apphub_HeaderStandardTop{display:flex;flex-direction:row-reverse;gap:12px}.apphub_AppName{font-size:28px;line-height:34px}.apphub_OtherSiteInfo{column-gap:6px}.theme-community{margin-left:2px;margin-right:2px;display:inline-block;box-sizing:border-box;background:rgb(30,60,80);color:rgb(130,200,240);border-radius:6px;font-size:14px;line-height:34px;text-decoration:none}.theme-community>span{display:block;padding:0 12px}.DRM_notice{background:rgb(90,76,44);color:rgb(220,195,130)}.alternate .apphub_OtherSiteInfo{column-gap:11px}.alternate .theme-community{background:rgb(40,50,60);color:rgb(210,220,230)}.alternate .DRM_notice{background:rgb(110,90,70);color:rgb(240,220,180)}
  </style></head><body><header class="apphub_HeaderStandardTop"><div class="apphub_OtherSiteInfo"><a id="community" class="theme-community btnv6_blue_hoverfade btn_medium" href="https://steamcommunity.com/app/123/" target="_blank"><span>Community Hub</span></a><span id="proton">Proton: Gold</span></div><div class="apphub_AppName">Monster Hunter Wilds</div></header><script>
  window.calls=[];window.listeners=new Set();window.added=false;window.installed=false;window.resolveInstall=null;
  window.Wired={watch:id=>calls.push(['watch',id]),getIntegration:()=>({apps:{123:{added,managed:added,installed}}}),getSnapshot:()=>({jobs:[]}),subscribe:cb=>{listeners.add(cb);return()=>listeners.delete(cb)},addToLibrary:id=>{calls.push(['addToLibrary',id]);return new Promise(resolve=>resolveInstall=resolve)},removeFromLibrary:async id=>{calls.push(['remove',id]);added=false;for(const cb of listeners)cb()},openFixes:async id=>calls.push(['fixes',id]),nativeInstall:id=>calls.push(['nativeInstall',id])};
  <\/script><script>${source}<\/script></body></html>`;
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id){const item=pending.get(message.id);if(item){pending.delete(message.id);message.error?item.reject(Error(message.error.message)):item.resolve(message.result);}return;}
    if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);
    if(message.method==='Fetch.requestPaused')void call('Fetch.fulfillRequest',{requestId:message.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/html; charset=utf-8'}],body:Buffer.from(fixture).toString('base64')});
  };
  await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await call('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
  await call('Page.navigate',{url:'https://store.steampowered.com/app/123/'});
  async function evaluate(expression){const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;}
  await until(()=>evaluate(`Boolean(document.querySelector('[data-wired-store]'))`),'Add wire missing');
  assert.equal(await evaluate(`document.querySelector('[data-wired-store]').textContent`),'Add wire');
  assert.equal(await evaluate(`document.getElementById('community').nextElementSibling.dataset.wiredActions`),'123');
  assert.equal(await evaluate(`document.querySelector('[data-wired-store]').className`),'theme-community btnv6_blue_hoverfade btn_medium');
  assert.equal(await evaluate(`document.querySelector('[data-wired-store]').hasAttribute('id')`),false);
  await evaluate(`document.querySelector('[data-wired-store]').click();document.querySelector('[data-wired-store]').click()`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c[0]==='addToLibrary')`),[['addToLibrary',123]]);
  assert.equal(await evaluate(`document.querySelector('[data-wired-store]').textContent`),'Adding…');
  await evaluate(`resolveInstall();added=true;for(const cb of listeners)cb()`);
  await until(()=>evaluate(`document.querySelector('[data-wired-store]').textContent==='Added wire'`),'Added state missing');
  await evaluate(`document.querySelector('[data-wired-store]').click()`);
  assert.equal(await evaluate(`calls.some(c=>c[0]==='nativeInstall')`),false);
  assert.equal(await evaluate(`calls.filter(c=>c[0]==='addToLibrary').length`),1);
  assert.equal(await evaluate(`!document.querySelector('[data-wired-denuvo]')`),true);
  await evaluate(`const drm=document.createElement('div');drm.className='DRM_notice native-theme';drm.textContent='Incorporates 3rd-party DRM: Denuvo Anti-tamper';document.body.append(drm)`);
  await until(()=>evaluate(`Boolean(document.querySelector('[data-wired-denuvo]'))`),'Denuvo notice missing');
  assert.equal(await evaluate(`document.querySelector('[data-wired-denuvo]').textContent`),'Denuvo');
  assert.equal(await evaluate(`document.querySelector('[data-wired-denuvo]').nextElementSibling.id`),'community');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('[data-wired-denuvo]')).backgroundColor`),'rgb(90, 76, 44)');
  assert.equal(await evaluate(`document.querySelector('[data-wired-denuvo]').tagName`),'A');
  await evaluate(`document.querySelector('.DRM_notice').style.background='transparent'`);
  await until(()=>evaluate(`getComputedStyle(document.querySelector('[data-wired-denuvo]')).backgroundColor!=='rgba(0, 0, 0, 0)'`),'Denuvo needs a visible background with transparent DRM notices');
  await evaluate(`document.querySelector('.DRM_notice').style.removeProperty('background')`);
  const bounds=await evaluate(`(()=>{const nodes=['.apphub_AppName','[data-wired-denuvo]','#community','[data-wired-store]'].map(sel=>document.querySelector(sel).getBoundingClientRect());return nodes.map(rect=>({left:rect.left,right:rect.right,center:rect.y+rect.height/2}))})()`);
  assert.ok(bounds.every(rect=>Math.abs(rect.center-bounds[0].center)<1),'Header must align on one row');
  assert.ok(Math.abs(bounds[2].left-bounds[1].right-6)<1,'Denuvo uses theme gap');
  assert.ok(Math.abs(bounds[3].left-bounds[2].right-6)<1,'Add uses theme gap');
  assert.equal(await evaluate(`Boolean(document.querySelector('[data-wired-fixes]'))`),false,'Not installed: no fixes');
  await evaluate(`installed=true;for(const cb of listeners)cb()`);
  await until(()=>evaluate(`Boolean(document.querySelector('[data-wired-fixes]'))`),'Installed and added: fixes missing');
  await evaluate(`document.querySelector('[data-wired-fixes]').click()`);
  assert.deepEqual(await evaluate(`calls.filter(c=>c[0]==='fixes')`),[['fixes',123]]);
  await evaluate(`document.body.classList.add('alternate');for(const cb of listeners)cb()`);
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.apphub_OtherSiteInfo')).columnGap`),'11px');
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('[data-wired-denuvo]')).backgroundColor`),'rgb(110, 90, 70)');
  await evaluate(`document.querySelector('.DRM_notice:not([data-wired-denuvo])').remove()`);
  await until(()=>evaluate(`!document.querySelector('[data-wired-denuvo]')`),'Unknown DRM must be hidden');
  assert.equal(await evaluate(`document.querySelector('[data-wired-remove]').hidden`),false);
  await evaluate(`document.querySelector('[data-wired-remove]').click()`);
  await until(()=>evaluate(`document.querySelector('[data-wired-store]').textContent==='Add wire'`),'Remove did not reset add state');
  assert.deepEqual(await evaluate(`calls.filter(c=>c[0]==='remove')`),[['remove',123]]);
  assert.equal(await evaluate(`Boolean(document.querySelector('[data-wired-fixes]'))`),false,'Installed but not added: no fixes');
  assert.equal(await evaluate(`calls.some(c=>c[0]==='nativeInstall')`),false);
  await call('Emulation.setDeviceMetricsOverride',{width:1100,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.querySelector('.apphub_AppName').textContent='DRAGON BALL XENOVERSE 2 - FUTURE SAGA Chapter 4';document.querySelector('.apphub_OtherSiteInfo').style.height='34px';for(const cb of listeners)cb()`);
  const longTitle=await evaluate(`(()=>{const button=document.querySelector('[data-wired-store]'),r=button.getBoundingClientRect();return {visible:r.width>0&&r.height>0,right:r.right,width:innerWidth}})()`);
  assert.ok(longTitle.visible&&longTitle.right<=longTitle.width,'Long titles must keep Add wire visible within the viewport');
  await call('Emulation.setDeviceMetricsOverride',{width:1249,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.querySelector('.apphub_AppName').textContent='DRAGON BALL XENOVERSE 2';Wired.addToLibrary=async()=>{throw Error('Providers did not return a valid package. Check the lua.tools login or Hubcap key in Wired settings.')};document.querySelector('[data-wired-store]').click()`);
  await until(()=>evaluate(`document.querySelector('[role=status]').textContent==='Providers did not return a valid package.'`),'Error should be compact');
  const ordered=await evaluate(`['.apphub_AppName','#community','[data-wired-store]','#proton','[role=status]'].map(sel=>{const r=document.querySelector(sel).getBoundingClientRect();return {x:r.x,y:r.y+r.height/2}})`);
  assert.ok(ordered.every((r,i)=>!i||r.x>ordered[i-1].x),'Title, buttons, Proton and message must follow the reference order');
  assert.ok(ordered.every(r=>Math.abs(r.y-ordered[0].y)<1),'Compact error must not push the title to another row');
  await evaluate(`const old=document.getElementById('community');const replacement=old.cloneNode(true);replacement.className='new-theme';old.replaceWith(replacement)`);
  await until(()=>evaluate(`document.querySelector('[data-wired-store]').className==='new-theme'`),'Theme remount failed');
  assert.equal(await evaluate(`document.querySelectorAll('[data-wired-store]').length`),1);
  assert.equal(await evaluate(`listeners.size`),1);
  await evaluate(`history.pushState({},'', '/app/456/');document.getElementById('community').href='https://steamcommunity.com/app/456/'`);
  await until(()=>evaluate(`document.querySelector('[data-wired-store]')?.dataset.wiredStore==='456'`),'App navigation failed');
  assert.equal(await evaluate(`document.querySelectorAll('[data-wired-store]').length`),1);
  await evaluate(`history.pushState({},'', '/app/789/');document.getElementById('community').href='https://steamcommunity.com/app/456/'`);
  await until(()=>evaluate(`document.querySelector('[data-wired-store]')?.dataset.wiredStore==='789'`),'DLC must use its own AppID even with base-game community link');
  await evaluate(`const proton=document.createElement('span');proton.id='late-proton';proton.textContent='Proton: Pending';document.querySelector('.apphub_OtherSiteInfo').append(proton)`);
  await until(()=>evaluate(`getComputedStyle(document.getElementById('late-proton')).order==='30'`),'Late Proton badge must retain order');
  await call('Emulation.setDeviceMetricsOverride',{width:1249,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.querySelector('.apphub_AppName').textContent='DRAGON BALL XENOVERSE 2 - FUTURE SAGA Chapter 4';const controls=document.createElement('div');controls.className='queue_overflow_ctn';controls.style.cssText='position:absolute;right:8px;top:8px;width:80px;height:34px';controls.textContent='☆ ♧';document.body.append(controls)`);
  await until(()=>evaluate(`parseFloat(getComputedStyle(document.querySelector('header')).paddingRight)>=80`),'Header must reserve native toolbar width');
  assert.equal(await evaluate(`(()=>{const icons=document.querySelector('.queue_overflow_ctn').getBoundingClientRect();return ['.apphub_AppName','#community','[data-wired-store]','#late-proton'].every(sel=>{const r=document.querySelector(sel).getBoundingClientRect();return r.right<=icons.left||r.top>=icons.bottom||r.bottom<=icons.top;})})()`),true,'Long titles and actions must not overlap native icons');
  assert.deepEqual(errors,[]);console.log('Store UI OK: Add wire beside Community Hub, inherited theme, add without installing, Remove, inline Denuvo, theme spacing/colors, Fixes only for added and installed games');

}finally{if(ws)ws.close();browser.kill('SIGTERM');await new Promise(resolve=>browser.once('exit',resolve));await rm(directory,{recursive:true,force:true,maxRetries:3,retryDelay:100});}
