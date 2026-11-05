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
  const source=await readFile(new URL('../.millennium/Dist/index.js',import.meta.url),'utf8');
  const react=await readFile('/tmp/wired-ui-deps/node_modules/react/umd/react.development.js','utf8');
  const reactDOM=await readFile('/tmp/wired-ui-deps/node_modules/react-dom/umd/react-dom.development.js','utf8');
  const fixture=`<!doctype html><html><head><meta charset="utf-8"></head><body><div data-wired-playbar></div><main data-wired-downloads-page><div id="steam-existing">Steam queue untouched</div></main><script>${react}<\/script><script>${reactDOM}</script><script>
window.SP_REACT=React;window.SP_REACTDOM=ReactDOM;
const h=React.createElement;
window.MILLENNIUM_API={
ToggleField:({label,checked,onChange})=>h('label',null,label,h('input',{type:'checkbox',checked,onChange:e=>onChange(e.target.checked)})),
DialogButton:({children,...props})=>h('button',props,children),
Field:({label,description,children})=>h('article',null,h('h4',null,label),h('p',null,description),children),
ProgressBarWithInfo:({nProgress,indeterminate,sOperationText,sTimeRemaining})=>h('div',null,h('progress',{value:indeterminate?undefined:nProgress,max:1,'data-sdk-progress':true}),h('span',null,sOperationText),h('span',null,sTimeRemaining)),
ModalRoot:({children})=>h('div',{'data-modal':true},children),
ConfirmModal:({strTitle,onOK})=>h('div',null,strTitle,h('button',{onClick:onOK},'Apply')),
showModal:element=>{const host=document.createElement('div');document.body.append(host);const root=ReactDOM.createRoot(host);root.render(element);return {Close:()=>{root.unmount();host.remove()}}},
findClass:()=>null
};
window.calls=[];window.tasks=[];window.job={id:'one',action:'download',appid:123,name:'Example <img src=x>',status:'working',message:'Downloading depot',percent:25,bytes:256,total:1024,bytes_estimated:true,speed:128,prompt:null};
window.SteamClient={Installs:{OpenInstallWizard:ids=>calls.push({method:'InstallWizard',ids})},Browser:{OpenURL:url=>calls.push({method:'OpenURL',url})}};
window.Millennium={AddWindowCreateHook:()=>{},callServerMethod:async(plugin,method,args)=>{
const payload=JSON.parse(args.payload_json);method=payload.method;args=payload.args;calls.push({method,args});
if(method==='GetLuaToolsAuthStatus')return {configured:false,status:'disconnected'};
if(method==='StartLuaToolsLogin')return {success:true,auth_url:'https://db.lua.tools/auth/v1/authorize?provider=discord'};
if(method==='CloudStatus')return {installed:true,provider:'local',sync_activity:false,providers:{local:{authenticated:false},folder:{settings:{sync_folder_path:''}},gdrive:{},onedrive:{},r2:{settings:{}},s3:{settings:{}}}};
if(method==='CloudAuthorize')return {auth_url:'https://accounts.google.com/oauth',status:'waiting'};
if(method==='CloudAuthPoll')return {status:'waiting'};
if(method==='GetSettings')return {api_list:[],accela_settings:{morrenus_api_key:'',max_downloads:16}};
if(method==='SaveSettings'){if(window.failSave)throw Error('Disk write failed');return {success:true};}
if(method==='StartTask'){if(args.action==='manifest_import')window.added=true;const result=args.action==='cloud_apps'?{accounts:[{id:42,name:'Example'}],apps:[{appid:123,account:42,files:1,size:1024}]}:args.action==='cloud_apply'?{success:true,restarting:true}:args.action==='fixes_catalog'?{name:'Example',fixes:[{id:'12345678-1234-1234-1234-123456789012',title:'Example Fix',hasFix:true,hasManifest:false}]}:{message:'Fix applied.'};const task={id:'task'+tasks.length,action:args.action,status:'done',result};tasks.push(task);return {success:true,job_id:task.id};}
if(method==='GetStatus')return JSON.stringify({current:job,jobs:[job,...tasks],queue:[]});
if(method==='GetIntegrationState')return {slssteam:{installed:true},cloudredirect:{installed:true},apps:{123:{added:window.added??true,installed:true}}};
if(method==='Pause'){job.status='paused';return {success:true};}
if(method==='Resume'){job.status='working';return {success:true};}
if(method==='Cancel'){job.status='cancelled';return {success:true};}
return {success:true};
}};
</script><script>${source}<\/script></body></html>`;
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id){const item=pending.get(message.id);if(item){pending.delete(message.id);message.error?item.reject(Error(message.error.message)):item.resolve(message.result);}return;}
    if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text);
    if(message.method==='Fetch.requestPaused')void call('Fetch.fulfillRequest',{requestId:message.params.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'text/html; charset=utf-8'}],body:Buffer.from(fixture).toString('base64')});
  };
  await call('Runtime.enable');await call('Page.enable');await call('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
  await call('Page.navigate',{url:'https://steamloopback.host/app/123/'});
  async function evaluate(expression){const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value;}
  const click=label=>evaluate(`(()=>{const el=[...document.querySelectorAll('button')].find(e=>e.textContent===${JSON.stringify(label)});if(!el)throw Error('Missing button '+${JSON.stringify(label)});el.click();return true;})()`);
  await until(()=>evaluate(`Boolean(document.querySelector('[data-sdk-progress]'))`),'Native Downloads section missing');
  assert.equal(await evaluate(`document.querySelector('[data-sdk-progress]').value`),0.25);
  assert.equal(await evaluate(`document.querySelectorAll('[data-wired-native] img').length`),0);
  assert.equal(await evaluate(`document.getElementById('steam-existing').textContent`),'Steam queue untouched');
  await click("Pause");await until(()=>evaluate(`Boolean([...document.querySelectorAll('button')].find(e=>e.textContent==='Resume'))`),'Paused state missing');
  await click("Resume");await until(()=>evaluate(`job.status==='working'&&Boolean([...document.querySelectorAll('button')].find(e=>e.textContent==='Pause'))`),'Resume failed');
  await evaluate(`job.percent=75;job.bytes=768`);
  await until(()=>evaluate(`document.querySelector('[data-sdk-progress]').value===0.75`),'Live progress failed');
  await evaluate(`document.querySelector('[data-wired-downloads-page]').remove();const page=document.createElement('main');page.dataset.wiredDownloadsPage='';document.body.append(page)`);
  await until(()=>evaluate(`Boolean(document.querySelector('[data-wired-downloads-page] [data-sdk-progress]'))`),'Route remount failed');
  assert.equal(await evaluate(`document.querySelectorAll('[data-sdk-progress]').length`),1);
  await click("Cancel");await until(()=>evaluate(`!document.querySelector('[data-sdk-progress]')`),'Cancel state failed');
  assert.equal(await evaluate(`calls.find(c=>c.method==='Cancel').args.job_id`),'one');
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('button')].find(e=>e.textContent==='Install via Steam'))`),'Install action missing');
  await click("Install via Steam");await until(()=>evaluate(`calls.some(c=>c.method==='InstallWizard')`),'Native install wizard missing');
  assert.deepEqual(await evaluate(`calls.find(c=>c.method==='InstallWizard').ids`),[123]);
  await evaluate(`window.added=false;Wired.refresh()`);
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('button')].find(e=>e.textContent==='Add to library'))`),'Add action missing');
  await click("Add to library");
  await until(()=>evaluate(`calls.some(c=>c.method==='StartTask'&&c.args.action==='manifest_import')&&Boolean([...document.querySelectorAll('button')].find(e=>e.textContent==='Install via Steam'))`),'Library addition did not finish');
  assert.equal(await evaluate(`calls.filter(c=>c.method==='InstallWizard').length`),1,'Adding must not open installation');
  assert.equal(await evaluate(`calls.some(c=>c.method==='StartTask'&&c.args.action==='download')`),false,'Adding must not start ACCELA');
  await evaluate(`const host=document.createElement('div');host.id='settings-test';document.body.append(host);ReactDOM.createRoot(host).render(window.MILLENNIUM_SIDEBAR_NAVIGATION_PANELS['wired-millennium'].content)`);
  await until(()=>evaluate(`Boolean(document.querySelector('#settings-test input[type="password"]'))`),'Hubcap field missing');
  await evaluate(`const input=document.querySelector('#settings-test input[type="password"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'test-key');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))`);
  assert.equal(await evaluate(`Boolean([...document.querySelectorAll('#settings-test button')].find(e=>/Save.*Hubcap|Save options/.test(e.textContent)))`),false,'No redundant save buttons');
  await until(()=>evaluate(`calls.some(c=>c.method==='SaveSettings')`),'Hubcap save missing');
  assert.equal(await evaluate(`JSON.parse(calls.find(c=>c.method==='SaveSettings').args.settings_json).accela_settings.morrenus_api_key`),'test-key');
  await evaluate(`const toggle=[...document.querySelectorAll('#settings-test label')].find(node=>node.textContent==='Sushi').querySelector('input');toggle.click()`);
  await until(()=>evaluate(`calls.filter(c=>c.method==='SaveSettings').some(c=>JSON.parse(c.args.settings_json).providers?.sushi===false)`),'Provider toggle must persist immediately');
  assert.equal(await evaluate(`JSON.parse(calls.filter(c=>c.method==='SaveSettings').at(-1).args.settings_json).accela_settings.morrenus_api_key`),'test-key','Toggle must preserve the latest key');
  assert.ok(await evaluate(`document.querySelector('[data-wired-settings]').getBoundingClientRect().height<650`),'Default provider settings should remain compact');
  await evaluate(`{window.failSave=true;const input=document.querySelector('#settings-test input[type=password]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'unsaved-key');input.dispatchEvent(new Event('input',{bubbles:true}))}`);
  await until(()=>evaluate(`document.querySelector('#settings-test [role=status]')?.textContent.includes('Could not apply changes: Disk write failed')`),'Persistence failure must be visible');
  await evaluate(`{window.failSave=false;const input=document.querySelector('#settings-test input[type=password]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'test-key');input.dispatchEvent(new Event('input',{bubbles:true}))}`);
  await until(()=>evaluate(`document.querySelector('#settings-test [role=status]')?.textContent==='Changes applied'`),'Editing again must recover from a persistence failure');
  await click('Sign in to lua.tools');
  await until(()=>evaluate(`calls.some(c=>c.method==='OpenURL'&&c.url.includes('provider=discord'))`),'Login browser did not open');
  assert.equal(await evaluate(`document.querySelector('#settings-test').textContent.includes('Complete Discord login')`),true);
  await click('Tools');
  await evaluate(`document.querySelector('#settings-test details').open=true`);
  await evaluate(`const article=[...document.querySelectorAll('#settings-test article')].find(node=>node.querySelector('h4')?.textContent==='Package AppID');const appInput=article.querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(appInput,'123');appInput.dispatchEvent(new Event('input',{bubbles:true}))`);
  await click('lua.tools fixes');
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('[data-modal]')].find(node=>node.textContent.includes('Example Fix')))`),'Fix catalogue missing');
  await click("Apply fix");
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('button')].find(node=>node.textContent==='Apply'))`),'Fix confirmation missing');
  await click('Apply');
  await until(()=>evaluate(`calls.some(c=>c.method==='StartTask'&&c.args.action==='fix_apply')`),'Fix was not queued');
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('[data-modal]')].find(node=>node.textContent.includes('Fix applied.')))`),'Fix result missing');
  await click('Cloud');
  await until(()=>evaluate(`Boolean([...document.querySelectorAll('#settings-test button')].find(node=>node.textContent==='Google Drive'))`),'Cloud provider settings missing');
  await click("Synced folder");
  await evaluate(`(()=>{const article=[...document.querySelectorAll('#settings-test article')].find(node=>node.querySelector('h4')?.textContent==='Synced folder');const field=article.querySelector('input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'/tmp/wired-fixture-folder');field.dispatchEvent(new Event('input',{bubbles:true}));const toggle=[...document.querySelectorAll('#settings-test label')].find(node=>node.textContent==='Sync achievements and playtime');toggle.querySelector('input').click()})()`);
  assert.equal(await evaluate(`calls.some(c=>c.method==='StartTask'&&c.args.action==='cloud_apply')`),false,'Cloud edits must stay in draft');
  await click("Save and restart");
  await until(()=>evaluate(`calls.some(c=>c.method==='StartTask'&&c.args.action==='cloud_apply')`),'Cloud save missing');
  const cloudRequest=await evaluate(`JSON.parse(calls.find(c=>c.method==='StartTask'&&c.args.action==='cloud_apply').args.args_json)`);
  assert.equal(cloudRequest.provider,'folder');assert.equal(cloudRequest.sync_activity,true);assert.equal(cloudRequest.sync_folder_path,'/tmp/wired-fixture-folder');
  assert.deepEqual(errors,[]);console.log('UI smoke OK: native controls, progress, Hubcap save, lua.tools login, fixes, CloudRedirect draft and native achievement sync');

}finally{if(ws)ws.close();browser.kill('SIGTERM');await new Promise(resolve=>browser.once('exit',resolve));await rm(directory,{recursive:true,force:true,maxRetries:3,retryDelay:100});}
