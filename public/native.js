// Native Steam components are provided by Millennium's SDK, not bundled copies.
(async () => {
  await window.WiredI18n?.ready;
  const W=window.Wired, A=window.MILLENNIUM_API, R=window.SP_REACT, D=window.SP_REACTDOM;
  if(!W||!A||!R||!D||!A.DialogButton||!A.Field){console.error("[Wired] Native SDK unavailable");return;}
  const t=window.WiredI18n?.t||((text)=>text), name='wired-millennium';
  const textProps=['label','description','title','aria-label','sOperationText','sTimeRemaining','strTitle','strDescription','strOKButtonText','strCancelButtonText','strMiddleButtonText'];
  function h(type,props,...children){
    const localized=props?{...props}:props;
    if(localized)for(const key of textProps)if(typeof localized[key]==='string')localized[key]=t(localized[key]);
    return R.createElement(type,localized,...children.map(child=>typeof child==='string'?t(child):child));
  }
  const Button=A.DialogButton, Primary=A.DialogButtonPrimary||Button, Field=A.Field;
  const roots=new Map(), documents=new Set();let stopped=false,promptId=null,lastError=null;
  function useWired(){const [,redraw]=R.useState(0);R.useEffect(()=>W.subscribe(()=>redraw(x=>x+1)),[]);return W.getSnapshot();}
  function report(error){lastError=String(error.message||error);showMessage("Unable to complete",lastError);}
  function showMessage(title,text){
    if(A.ConfirmModal&&A.showModal)A.showModal(h(A.ConfirmModal,{strTitle:title,strDescription:text,bAlertDialog:true,strOKButtonText:'OK'}));
    else console.error('[Wired]',title,text);
  }
  const action=fn=>()=>Promise.resolve().then(fn).catch(report);
  function NativeProgress({job}){
    const percentage=Number.isFinite(job.percent)?job.percent:job.total?100*job.bytes/job.total:null;
    const progressProps={nProgress:Math.max(0,Math.min(1,(percentage||0)/100)),indeterminate:percentage===null};
    const Progress=A.ProgressBarWithInfo||A.ProgressBarItem||A.ProgressBar;
    return h(Field,{label:job.name||`App ${job.appid||''}`,description:job.message,childrenLayout:'below'},
      h('div',null,
        Progress?h(Progress,{...progressProps,sOperationText:job.message,sTimeRemaining:job.total?`${job.bytes_estimated?'≈ ':''}${formatBytes(job.bytes)} / ${formatBytes(job.total)}${job.status==='working'&&job.speed>0?' · ≈ '+formatBytes(job.speed)+'/s':''}`:undefined}):h('progress',{max:100,value:percentage??undefined}),
        h('div',{style:{display:'flex',gap:'8px',flexWrap:'wrap'}},
          job.status==='paused'?h(Button,{onClick:action(()=>W.rpc('Resume'))},"Resume"):h(Button,{disabled:!['working'].includes(job.status),onClick:action(()=>W.rpc('Pause'))},"Pause"),
          h(Button,{disabled:['done','cancelled','error'].includes(job.status),onClick:action(()=>W.rpc('Cancel',{job_id:job.id}))},"Cancel"),
          h(Button,{onClick:action(()=>openGame(job.appid))},"Game page"))));
  }
  function formatBytes(value){let n=Number(value)||0,index=0;const units=['B','KB','MB','GB','TB'];while(n>=1024&&index<4){n/=1024;index++;}return `${n.toFixed(index?1:0)} ${units[index]}`;}
  function openGame(appid){if(appid)window.SteamClient?.Browser?.OpenURL?.('steam://nav/games/details/'+Number(appid));}
  function DownloadsSection(){
    const state=useWired();
    const jobs=state.jobs.filter(job=>job.action==='download'&&job.status!=='cancelled');
    if(!jobs.length)return null;
    return h('section',{'aria-label':'Integrated engine downloads'},
      h(A.DialogSubHeader||'h3',null,'ACCELA downloads'),
      ...jobs.map(job=>h(NativeProgress,{key:job.id,job})));
  }
  function AppActions({appid}){
    const state=useWired();R.useEffect(()=>{W.watch(appid);},[appid]);
    const integration=W.getIntegration();const app=integration?.apps?.[String(appid)];
    const busy=state.jobs.some(job=>Number(job.appid)===Number(appid)&&!['done','error','cancelled'].includes(job.status));
    const client=integration?.slssteam?.installed;
    function menu(event){
      if(!A.showContextMenu||!A.Menu||!A.MenuItem)return;
      const items=[
        ["Install via Steam",()=>app?.added?W.nativeInstall(appid):W.install(appid),!client||busy],
        ["Install with ACCELA",()=>W.start('download',{appid:Number(appid)}),busy],
        ['View downloads',()=>W.downloads(),false],
        ...(app?.added&&app?.installed?[["lua.tools fixes",()=>openFixes(appid),busy]]:[]),
        ["Restore pre-patch files",()=>restoreFix(appid),busy],
        ["Status of cloud saves",async()=>{const value=await W.rpc('CloudStatus');showMessage('CloudRedirect',"Provider:"+value.provider+' · '+(value.authenticated?"Connected":value.provider==='local'?"Local only":"Account not connected")+' · '+(value.sync_activity?'Achievements and playtime synced':"Activity Sync Disabled"));},false],
        ["Remove library integration",()=>confirmRemove(appid),!app?.managed||busy]
      ];
      A.showContextMenu(h(A.Menu,{label:"Installation and cloud"},...items.map(([label,fn,disabled])=>h(A.MenuItem,{key:label,disabled,onSelected:action(fn)},label))),event.currentTarget);
    }
    return h('div',{style:{display:'flex',gap:'8px',alignItems:'center',flexWrap:'wrap'}},
      h(Button,{disabled:busy||!client,onClick:action(()=>app?.added?W.nativeInstall(appid):W.addToLibrary(appid)),title:client?(app?.added?"Install via Steam":"Add to library without installing"):'Install slsteam-moon using the Wired installer'},busy?"Preparing…":app?.added?"Install via Steam":"Add to library"),
      h(Button,{onClick:menu,'aria-label':"Manage installation and cloud"},'Gerenciar'),
      app?.managed?h(Button,{disabled:busy,onClick:()=>confirmRemove(appid)},'Remove'):null);
  }
  function confirmRemove(appid){
    if(!A.ConfirmModal||!A.showModal)return;
    A.showModal(h(A.ConfirmModal,{strTitle:"Remove integration?",strDescription:"Removes managed script only. Game files and saves will be preserved.",strOKButtonText:"Remove",strCancelButtonText:"Cancel",onOK:action(()=>W.removeFromLibrary(appid))}));
  }
  function Text({label,value,onChange,password=false}){
    const Component=A.TextField;
    return h(Field,{label,childrenLayout:'below'},Component?h(Component,{value:value??'',type:password?'password':'text',onChange:event=>onChange(event?.target?.value??event) }):h('input',{value:value??'',type:password?'password':'text',onChange:event=>onChange(event.target.value)}));
  }
  function openFixes(appid){
    if(!A.showModal||!A.ModalRoot)return;
    A.showModal(h(FixesPanel,{appid:Number(appid)}),undefined,{strTitle:"lua.tools fixes"});
  }
  function restoreFix(appid){
    if(!A.showModal||!A.ConfirmModal)return;
    A.showModal(h(A.ConfirmModal,{strTitle:"Restore previous files?",strDescription:"Restores original files backed up before applying a Wired fix. Close the game first.",strOKButtonText:"Restore",onOK:action(async()=>{const result=await W.run('fix_restore',{appid:Number(appid)});showMessage("Correction",result.message);})}));
  }
  function FixesPanel({appid}){
    const snapshot=useWired();const progress=snapshot.current;
    const [game,setGame]=R.useState(null),[message,setMessage]=R.useState("Loading catalog…"),[busy,setBusy]=R.useState(false);
    R.useEffect(()=>{let alive=true;W.run('fixes_catalog',{appid}).then(value=>{if(alive){setGame(value);setMessage(value.fixes.length?"Select a fix. Close the game before applying.":"No fixes published for this game.");}}).catch(err=>{if(alive)setMessage(String(err.message||err));});return()=>{alive=false;};},[appid]);
    async function run(fix,operation){
      if(operation==='fix_apply'&&A.ConfirmModal&&A.showModal){
        A.showModal(h(A.ConfirmModal,{strTitle:'Apply '+fix.title+'?',strDescription:"Replaces files in this game installation and backs up the originals. Close the game first.",strOKButtonText:'Aplicar',onOK:()=>execute(fix,operation)}));
      }else await execute(fix,operation);
    }
    async function execute(fix,operation){setBusy(true);setMessage("Applying fix…");try{const result=await W.run(operation,{appid,fix_id:fix.id});setMessage(result.message||'Manifest added.');}catch(err){setMessage(String(err.message||err));}finally{setBusy(false);}}
    return h(A.ModalRoot,null,h(A.DialogHeader||'h2',null,game?.name||"lua.tools fixes"),h(A.DialogBody||'div',null,
      h(Field,{label:message,description:busy&&progress?.appid===appid?`${progress.message||''} ${progress.total?formatBytes(progress.bytes)+' / '+formatBytes(progress.total):''}`:undefined}),...(game?.fixes||[]).map(fix=>h(Field,{key:fix.id,label:fix.title,description:fix.requiresPreparation?"Requires hypervisor preparation, not yet integrated.":fix.description,childrenLayout:'below'},
        fix.hasFix?h(Button,{disabled:busy||fix.requiresPreparation,onClick:()=>run(fix,'fix_apply')},"Apply fix"):null,
        fix.hasManifest?h(Button,{disabled:busy,onClick:()=>run(fix,'fix_manifest')},"Add manifest"):null)),
      h(Button,{disabled:busy,onClick:()=>restoreFix(appid)},"Restore previous files")));
  }
  function LuaToolsAccount(){
    const [account,setAccount]=R.useState(null),[error,setError]=R.useState(''),[busy,setBusy]=R.useState(false);
    R.useEffect(()=>{let alive=true;const poll=()=>W.rpc('GetLuaToolsAuthStatus').then(value=>{if(alive)setAccount(value);}).catch(err=>{if(alive)setError(String(err.message||err));});poll();const timer=setInterval(poll,2000);return()=>{alive=false;clearInterval(timer);};},[]);
    async function login(){
      setBusy(true);setError('');
      try{const result=await W.rpc('StartLuaToolsLogin');setAccount({status:'waiting',configured:false});
        if(window.SteamClient?.System?.OpenInSystemBrowser)window.SteamClient.System.OpenInSystemBrowser(result.auth_url);
        else if(window.SteamClient?.Browser?.OpenURL)window.SteamClient.Browser.OpenURL(result.auth_url);
        else window.open(result.auth_url,'_blank','noopener');
      }catch(err){setError(String(err.message||err));}finally{setBusy(false);}
    }
    const pending=['waiting','authenticating'].includes(account?.status);
    return h(Field,{label:"lua.tools account (Luie)",description:error||account?.error||(pending?"Complete Discord login in the browser and return to Steam.":account?.configured?"Connected:"+account.account:"Sign in to use lua.tools manifests."),childrenLayout:'below'},
      h('div',{style:{display:'flex',gap:'8px'}},
        !account?.configured&&!pending?h(Button,{disabled:busy,onClick:login},'Sign in to lua.tools'):null,
        pending?h(Button,{onClick:action(async()=>{await W.rpc('CancelLuaToolsLogin');setAccount(await W.rpc('GetLuaToolsAuthStatus'));})},"Cancel login"):null,
        account?.configured?h(Button,{onClick:action(async()=>{await W.rpc('LogoutLuaTools');setAccount(await W.rpc('GetLuaToolsAuthStatus'));})},'Sign out of lua.tools'):null));
  }
  function CloudSettings(){
    const [view,setView]=R.useState('connection'),[page,setPage]=R.useState(0);
    const [applied,setApplied]=R.useState(null),[draft,setDraft]=R.useState(null),[message,setMessage]=R.useState(''),[busy,setBusy]=R.useState(false),[auth,setAuth]=R.useState(null),[inventory,setInventory]=R.useState({accounts:[],apps:[]}),[account,setAccount]=R.useState(null),[remote,setRemote]=R.useState([]);
    const labels={local:"Local only",folder:"Synced folder",gdrive:'Google Drive',onedrive:'OneDrive',r2:'Cloudflare R2',s3:"S3 compatible"};
    function makeDraft(value){return {provider:value.provider,sync_activity:value.sync_activity,settings:Object.fromEntries(Object.entries(value.providers).map(([key,item])=>[key,{...(item.settings||{})}])),sign_out_provider:null};}
    async function reload(){const value=await W.rpc('CloudStatus');setApplied(value);setDraft(makeDraft(value));setRemote([]);}
    R.useEffect(()=>{let alive=true;W.rpc('CloudStatus').then(value=>{if(alive){setApplied(value);setDraft(makeDraft(value));}}).catch(err=>{if(alive)setMessage(String(err.message||err));});W.run('cloud_apps').then(value=>{if(alive){setInventory(value);setAccount(value.accounts[0]?.id??null);}}).catch(err=>{if(alive)setMessage(String(err.message||err));});return()=>{alive=false;};},[]);
    R.useEffect(()=>{if(!auth)return;let alive=true;const timer=setInterval(()=>W.rpc('CloudAuthPoll').then(value=>{if(!alive)return;if(value.status==='done'){setAuth(null);setMessage("Login completed. Click Save and Restart to apply.");W.rpc('CloudStatus').then(setApplied).catch(report);}else if(['error','timeout','idle'].includes(value.status)){setAuth(null);setMessage(value.error||'Sign-in ended.');}}).catch(err=>{if(alive){setAuth(null);setMessage(String(err.message||err));}}),1000);return()=>{alive=false;clearInterval(timer);};},[auth]);
    if(!draft||!applied)return h(Field,{label:message||"Loading cloud…"});
    if(!applied.installed)return h(Field,{label:"CloudRedirect not installed",description:'Update the component using the Wired installer.'});
    const provider=draft.provider,settings=draft.settings[provider]||{};
    const change=(key,value)=>setDraft({...draft,settings:{...draft.settings,[provider]:{...settings,[key]:value}}});
    const dirty=JSON.stringify(draft)!==JSON.stringify(makeDraft(applied))||Object.values(applied.providers).some(item=>item.pending);
    async function login(){setBusy(true);setMessage('');try{const value=await W.rpc('CloudAuthorize',{provider});setAuth(provider);if(window.SteamClient?.System?.OpenInSystemBrowser)window.SteamClient.System.OpenInSystemBrowser(value.auth_url);else window.SteamClient?.Browser?.OpenURL?.(value.auth_url);setMessage("Complete browser login and return to Steam.");}catch(err){setMessage(String(err.message||err));}finally{setBusy(false);}}
    async function commit(migrate){
      setBusy(true);setMessage(migrate?"Migrating data and preparing to restart Steam…":"Saving and preparing to restart Steam…");
      const request={provider,sync_activity:draft.sync_activity,sign_out_provider:draft.sign_out_provider,migrate};
      if(provider==='folder')request.sync_folder_path=settings.sync_folder_path||'';
      if(['r2','s3'].includes(provider)){request.credentials={...settings};delete request.credentials.has_secret;}
      try{await W.run('cloud_apply',request);setMessage('Restarting Steam…');}catch(err){setMessage(String(err.message||err));}finally{setBusy(false);}
    }
    function save(){
      if(applied.provider!=='local'&&provider!=='local'&&applied.provider!==provider&&A.showModal&&A.ConfirmModal){
        A.showModal(h(A.ConfirmModal,{strTitle:"Migrate data from the cloud?",strDescription:"Copy data from current provider before switching? The origin will be preserved.",strOKButtonText:'Migrate and restart',strMiddleButtonText:'Switch without migrating',strCancelButtonText:"Cancel",onOK:()=>commit(true),onMiddleButton:()=>commit(false)}));
      }else commit(false);
    }
    async function loadRemote(){setBusy(true);try{const value=await W.run('cloud_remote',{account});setRemote(value.appids||[]);setMessage("Updated cloud list.");}catch(err){setMessage(String(err.message||err));}finally{setBusy(false);}}
    const local=inventory.apps.filter(item=>item.account===account),ids=Array.from(new Set([...local.map(item=>item.appid),...remote])).sort((a,b)=>a-b);
    const navigation=h('div',{role:'tablist','aria-label':'Cloud settings',style:{display:'flex',gap:'0.5em'}},...[['connection','Connection'],['games','Saved games']].map(([value,label])=>h(Button,{key:value,role:'tab','aria-selected':view===value,onClick:()=>setView(value)},label)));
    if(view==='games')return h('div',null,navigation,
      h(Field,{label:'Steam account',childrenLayout:'below'},h('div',{style:{display:'flex',gap:'0.5em',flexWrap:'wrap'}},...inventory.accounts.map(item=>h(Button,{key:item.id,disabled:busy||item.id===account,onClick:()=>{setAccount(item.id);setRemote([]);setPage(0);}},item.name||String(item.id))))),
      h(Button,{disabled:busy||dirty||account===null||provider==='local',onClick:loadRemote},'Refresh cloud list'),
      dirty?h(Field,{label:'Apply your connection changes before querying the provider.'}):null,
      ...ids.slice(page*5,page*5+5).map(id=>{const item=local.find(value=>value.appid===id);return h(Field,{key:id,label:window.appStore?.GetAppOverviewByAppID?.(id)?.display_name||'App '+id,description:item?formatBytes(item.size):'No local copy'},h(Button,{onClick:()=>openGame(id)},'Game page'));}),
      ids.length>5?h('div',null,h(Button,{disabled:page===0,onClick:()=>setPage(page-1)},'Previous'),h(Button,{disabled:(page+1)*5>=ids.length,onClick:()=>setPage(page+1)},'Next')):null,
      message?h(Field,{label:message}):null);
    return h('div',null,navigation,
      h(A.DialogSubHeader||'h3',null,'Cloud saves and achievements'),
      h(Field,{label:"Provider",description:"Changes only take effect upon saving and restarting.",childrenLayout:'below'},h('div',{style:{display:'flex',gap:'8px',flexWrap:'wrap'}},...Object.entries(labels).map(([value,label])=>h(Button,{key:value,disabled:busy||Boolean(auth)||value===provider,onClick:()=>setDraft({...draft,provider:value})},label)))),
      ['gdrive','onedrive'].includes(provider)?h(Field,{label:labels[provider],description:applied.providers[provider]?.pending?'Sign-in ready to apply.':applied.providers[provider]?.authenticated?"Account connected.":"Log in to your account.",childrenLayout:'below'},
        !applied.providers[provider]?.authenticated&&!applied.providers[provider]?.pending?h(Button,{disabled:busy||Boolean(auth),onClick:login},'Sign in to '+labels[provider]):null,
        applied.providers[provider]?.authenticated||applied.providers[provider]?.pending?h(Button,{disabled:busy,onClick:()=>{setDraft({...draft,provider:'local',sign_out_provider:provider});setMessage("Account will be disconnected when saving and restarting.");}},'Disconnect'):null):null,
      provider==='folder'?h(Text,{label:"Synced folder",value:settings.sync_folder_path,onChange:value=>change('sync_folder_path',value)}):null,
      ['r2','s3'].includes(provider)?h('div',{style:{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(14em,1fr))',columnGap:'1em'}},
        ...[['account_id','R2 account ID'],['access_key_id','Access key ID'],['secret_access_key','Secret access key'],['bucket','Bucket'],['endpoint','Endpoint']].filter(([key])=>provider==='r2'||key!=='account_id').map(([key,label])=>h(Text,{key,label:label+(key==='secret_access_key'&&settings.has_secret?' (saved; leave blank to keep)':''),password:key==='secret_access_key',value:settings[key],onChange:value=>change(key,value)}))):null,
      ['r2','s3'].includes(provider)?h('details',null,h('summary',null,'Advanced connection options'),
        ...[['region','Region'],['key_prefix','Key prefix'],['ca_cert_path','CA certificate path']].filter(([key])=>provider==='s3'||key==='key_prefix').map(([key,label])=>h(Text,{key,label,value:settings[key],onChange:value=>change(key,value)})),
        ...(provider==='s3'&&A.ToggleField?['sign_payload','allow_insecure_http','allow_insecure_tls'].map(key=>h(A.ToggleField,{key,label:{sign_payload:'Sign S3 payload',allow_insecure_http:'Allow HTTP endpoint',allow_insecure_tls:'Allow TLS without validation'}[key],checked:Boolean(settings[key]),onChange:value=>change(key,value)})):[])):null,
      A.ToggleField?h(A.ToggleField,{label:'Sync achievements and playtime',description:"Syncs native Steam achievements and game time with the same save provider.",checked:draft.sync_activity,onChange:value=>setDraft({...draft,sync_activity:value})}):null,
      h(Button,{disabled:busy||Boolean(auth)||!dirty,onClick:save},"Save and restart"),
      dirty?h(Button,{disabled:busy,onClick:action(async()=>{await W.rpc('CloudDiscard');setAuth(null);await reload();setMessage("Changes discarded.");})},"Discard changes"):null,
      message?h(Field,{label:message}):null);
  }

  function Settings(){
    const [tab,setTab]=R.useState('providers');
    useWired();
    const [config,setConfig]=R.useState(null),[message,setMessage]=R.useState(''),[zip,setZip]=R.useState(''),[appid,setAppid]=R.useState(''),[sourceIndex,setSourceIndex]=R.useState(-1);
    const current=R.useRef(null),revision=R.useRef(0),pending=R.useRef(Promise.resolve()),timer=R.useRef(null);
    R.useEffect(()=>{W.rpc('GetSettings').then(value=>{current.current=value;setConfig(value);}).catch(report);W.refresh().catch(report);return()=>{clearTimeout(timer.current);if(current.current&&revision.current)persist(current.current,revision.current);};},[]);
    const integration=W.getIntegration();
    R.useEffect(()=>{if(/^\d+$/.test(appid))W.watch(Number(appid));},[appid]);
    function persist(value,version){
      pending.current=pending.current.catch(()=>{}).then(()=>W.rpc('SaveSettings',{settings_json:JSON.stringify(value)})).then(()=>{if(revision.current===version)setMessage('Changes applied');}).catch(error=>{if(revision.current===version)setMessage('Could not apply changes: '+String(error.message||error));});
      return pending.current;
    }
    function update(patch,immediate=false){
      const next={...current.current,...patch};current.current=next;setConfig(next);const version=++revision.current;
      clearTimeout(timer.current);setMessage('Applying changes…');
      if(immediate)persist(next,version);else timer.current=setTimeout(()=>persist(next,version),450);
    }
    if(!config)return h(Field,{label:'Loading settings…'});
    const change=(key,value,immediate=false)=>update({accela_settings:{...current.current.accela_settings,[key]:value}},immediate);
    const Toggle=A.ToggleField;
    const toggle=(key,label,description)=>Toggle?h(Toggle,{key,label,description,checked:Boolean(config.accela_settings[key]),onChange:value=>change(key,value,true)}):null;
    const tabs=[['providers','Providers'],['downloads','Downloads'],...(integration?.cloudredirect?.installed?[['cloud','Cloud']]:[]),['tools','Tools']];
    const navigation=h('div',{role:'tablist','aria-label':'Wired settings',style:{display:'flex',gap:'0.5em',flexWrap:'wrap',marginBottom:'0.75em'}},...tabs.map(([value,label])=>h(Button,{key:value,role:'tab','aria-selected':tab===value,onClick:()=>setTab(value)},label)));
    let content;
    if(tab==='cloud')content=h(CloudSettings);
    else if(tab==='providers')content=h('div',null,
      h(Field,{label:'Manifest providers',description:'Enabled providers are tried automatically in order. Changes apply automatically.'}),
      h(LuaToolsAccount),
      Toggle?h(Toggle,{label:'Hubcap (Sadie)',description:'Uses your API key. Tried first when enabled.',checked:config.providers?.hubcap??true,onChange:value=>update({providers:{...current.current.providers,hubcap:value}},true)}):null,
      h(Text,{label:'Hubcap API key',password:true,value:config.accela_settings.morrenus_api_key,onChange:value=>change('morrenus_api_key',value)}),
      ...[['lua_tools','lua.tools (Luie)'],['sushi','Sushi'],['ryuu','Ryuu (HTTP)']].map(([key,label])=>Toggle?h(Toggle,{key,label,checked:config.providers?.[key]??key!=='ryuu',onChange:value=>update({providers:{...current.current.providers,[key]:value}},true)}):null));
    else if(tab==='downloads')content=h('div',null,
      h(Field,{label:'ACCELA engine',description:'Prepared automatically when a download needs it.'}),
      h(Text,{label:'Parallel downloads (1–128)',value:String(config.accela_settings.max_downloads??16),onChange:value=>{if(/^\d+$/.test(value)&&Number(value)>=1&&Number(value)<=128)change('max_downloads',Number(value));}}),
      toggle('use_steamless','Run Steamless after installation'),toggle('auto_apply_goldberg','Apply Goldberg after installation'),toggle('generate_achievements','Generate Goldberg achievements'),
      h(Field,{label:'Steam downloads',description:'Adding a game never installs it. Start installation from your Steam library.'},h(Button,{onClick:action(()=>W.downloads())},'Open downloads')));
    else content=h('div',null,
      h(Field,{label:'Components',description:'SLSsteam: '+(integration?.slssteam?.installed?'Installed':'Missing')+' · CloudRedirect: '+(integration?.cloudredirect?.installed?'Installed':'Missing')},h(Button,{onClick:action(async()=>{await W.run('cloud_update');setMessage('CloudRedirect updated. Restart Steam to load it.');})},'Update CloudRedirect')),
      h('details',null,h('summary',null,'Local package'),h(Text,{label:'Package AppID',value:appid,onChange:setAppid}),h(Text,{label:'Local ZIP path',value:zip,onChange:setZip}),
        h(Button,{disabled:!zip||!/^\d+$/.test(appid),onClick:action(()=>W.run('manifest_import',{appid:Number(appid),zip_path:zip}))},'Add to library'),
        integration?.apps?.[String(Number(appid))]?.added&&integration?.apps?.[String(Number(appid))]?.installed?h(Button,{onClick:()=>openFixes(appid)},'lua.tools fixes'):null),
      h('details',null,h('summary',null,'Custom sources'),...config.api_list.map((entry,index)=>h(Field,{key:index,label:entry.name||'Unnamed source',childrenLayout:'below'},
        Toggle?h(Toggle,{label:'Enabled',checked:entry.enabled!==false,onChange:value=>update({api_list:current.current.api_list.map((item,i)=>i===index?{...item,enabled:value}:item)},true)}):null,
        h(Button,{onClick:()=>setSourceIndex(index)},'Edit'),h(Button,{onClick:()=>update({api_list:current.current.api_list.filter((_,i)=>i!==index)},true)},'Remove'))),
        h(Button,{onClick:()=>setSourceIndex(config.api_list.length)},'Add source')),
      sourceIndex>=0?h(SourceEditor,{key:sourceIndex,entry:config.api_list[sourceIndex],onCancel:()=>setSourceIndex(-1),onCommit:entry=>{const list=[...current.current.api_list];list[sourceIndex]=entry;update({api_list:list},true);setSourceIndex(-1);}}):null);
    return h('section',{'data-wired-settings':true,dir:window.WiredI18n?.direction||'ltr'},navigation,h('div',{role:'tabpanel',style:{maxWidth:'54em'}},content),message?h('p',{role:'status','aria-live':'polite'},message):null);
  }
  function SourceEditor({entry,onCancel,onCommit}){
    const [draft,setDraft]=R.useState(entry||{name:'',url:'',api_key:'',enabled:true});
    const change=(key,value)=>setDraft({...draft,[key]:value});
    const valid=draft.url.startsWith('https://')&&draft.url.includes('<appid>');
    return h('div',null,h(Text,{label:'Source name',value:draft.name,onChange:value=>change('name',value)}),h(Text,{label:'HTTPS URL containing <appid>',value:draft.url,onChange:value=>change('url',value)}),h(Text,{label:'API key',password:true,value:draft.api_key,onChange:value=>change('api_key',value)}),h(Button,{disabled:!valid,onClick:()=>onCommit(draft)},'Save source'),h(Button,{onClick:onCancel},'Cancel'));
  }
  function Prompt({job,prompt}){
    const [answer,setAnswer]=R.useState(prompt.multiple?(prompt.default||[]):prompt.kind==='confirm'?true:prompt.default||'');
    const [error,setError]=R.useState('');
    const respond=async(cancel)=>{
      try{await W.rpc('ReplyPrompt',{job_id:job.id,prompt_id:prompt.id,answer_json:JSON.stringify(answer),cancel});modal?.Close();}
      catch(err){setError(String(err.message||err));}
    };
    return h(A.ModalRoot,{onCancel:()=>respond(true)},
      h(A.DialogHeader||'h2',null,prompt.title),
      h(A.DialogBody||'div',null,
        ...prompt.choices.map(choice=>prompt.multiple&&A.ToggleField?h(A.ToggleField,{key:choice.value,label:choice.label,checked:answer.includes(String(choice.value)),onChange:checked=>setAnswer(checked?[...answer,String(choice.value)]:answer.filter(v=>v!==String(choice.value)))}):h(Button,{key:choice.value,onClick:()=>setAnswer(String(choice.value))},choice.label+(answer===String(choice.value)?' ✓':''))),
        !prompt.choices.length&&prompt.kind!=='confirm'?h(Text,{label:"Destiny",value:answer,onChange:setAnswer}):null,
        error?h(Field,{label:error}):null),
      h(A.DialogFooter||'div',null,h(Primary,{onClick:()=>respond(false)},"Confirm"),h(Button,{onClick:()=>respond(true)},"Cancel")));
  }
  let modal;
  W.subscribe(()=>{
    const job=W.getSnapshot().current,prompt=job?.prompt;
    if(!prompt){if(promptId)modal?.Close();promptId=null;return;}
    if(promptId===prompt.id||!A.showModal||!A.ModalRoot)return;
    promptId=prompt.id;
    modal=A.showModal(h(Prompt,{job,prompt}),undefined,{strTitle:prompt.title,bNeverPopOut:true});
  });
  function findByClass(doc,name){const cls=A.findClass?.(name);return cls?doc.getElementsByClassName(cls)[0]:null;}
  function currentApp(doc){
    const location=window.MainWindowBrowserManager?.m_lastLocation?.pathname||doc.location.pathname;
    const match=location.match(/\/app\/(\d+)/);if(match)return Number(match[1]);
    return null;
  }
  function mount(doc,key,host,element){
    const existing=roots.get(key);
    if(existing?.node?.isConnected&&existing.host===host){if(existing.value!==element?.key){existing.root.render(element);existing.value=element.key;}return;}
    if(existing){existing.root.unmount();existing.node.remove();}
    if(!host){roots.delete(key);return;}
    const node=doc.createElement('div');node.dataset.wiredNative=key;host.append(node);
    const root=D.createRoot(node);root.render(element);roots.set(key,{root,node,host,value:element.key});
  }
  function scan(){
    if(stopped)return;
    for(const doc of documents){
      if(!doc.defaultView||doc.defaultView.closed)continue;
      const id=currentApp(doc);
      const host=id?(findByClass(doc,'PlayBar')||doc.querySelector('[data-wired-playbar], [class*="appdetailsplaysection_PlayBar"]')):null;
      mount(doc,'app-'+documentId(doc),host,id?h(AppActions,{key:String(id),appid:id}):null);
      const page=findByClass(doc,'DownloadsPage')||doc.querySelector('[data-wired-downloads-page], [class*="downloads_DownloadsPage"]');
      mount(doc,'downloads-'+documentId(doc),page,page?h(DownloadsSection,{key:'downloads'}):null);
    }
    for(const [key,value] of roots)if(!value.node.isConnected){value.root.unmount();roots.delete(key);}
  }
  const ids=new WeakMap();let sequence=0;function documentId(doc){if(!ids.has(doc))ids.set(doc,++sequence);return ids.get(doc);}
  function attach(doc){if(doc?.documentElement){documents.add(doc);scan();}}
  attach(document);Millennium.AddWindowCreateHook?.(popup=>{try{attach(popup?.window?.document);}catch{}});
  const interval=setInterval(scan,750);
  const props={title:'Wired',icon:h('svg',{viewBox:'0 0 24 24',width:20,height:20},h('path',{fill:'currentColor',d:'M6 18a4 4 0 0 1 0-8 6 6 0 0 1 11.7-1A4.5 4.5 0 1 1 18 18H6z'})),content:h(Settings)};
  (window.PLUGIN_LIST||={})[name]={...props,__millennium_internal_plugin_name_do_not_use_or_change__:name,
    OpenFixes:appid=>{openFixes(Number(appid));return JSON.stringify({success:true});},
    RuntimeProbe:()=>JSON.stringify({documents:documents.size,version:'0.7.0',entries:Array.from(roots.values()).filter(v=>v.node.isConnected).length,native:true,lastError}),
    onDismount(){stopped=true;clearInterval(interval);for(const value of roots.values()){value.root.unmount();value.node.remove();}roots.clear();W.destroy();}};
  (window.MILLENNIUM_SIDEBAR_NAVIGATION_PANELS||={})[name]=props;
  window.MILLENNIUM_BACKEND_IPC?.postMessage(1,{pluginName:name});
})();
