// Shared bridge and state. This file does not draw a standalone launcher or window.
(() => {
  if (window.Wired) return;
  const listeners=new Set(), completions=new Map(), interests=new Set();
  let snapshot={current:null,jobs:[],queue:[]}, integration=null, polling=false, timer, lastRefresh=0, refreshing=false;
  const terminal=job=>['done','error','cancelled'].includes(job.status);
  async function rpc(method,args={}) {
    const raw=await Millennium.callServerMethod('wired-millennium','WiredRPC',{payload_json:JSON.stringify({method,args})});
    const value=typeof raw==='string'?JSON.parse(raw):raw;
    if(value?.success===false)throw Error(value.error||"Operation refused");
    return value;
  }
  function notify(){for(const listener of listeners)try{listener();}catch(error){console.error('[Wired]',error);}}
  async function refresh(ids=Array.from(interests)){
    if(refreshing)return integration;
    refreshing=true;
    try{integration=await rpc('GetIntegrationState',{appids_json:JSON.stringify(ids)});lastRefresh=Date.now();notify();return integration;}finally{refreshing=false;}
  }
  async function poll(){
    if(!polling)return;
    try{
      snapshot=await rpc('GetStatus');
      for(const job of snapshot.jobs){
        if(terminal(job)&&completions.has(job.id)){
          const resolve=completions.get(job.id);completions.delete(job.id);resolve(job);
          if(['manifest_import','integration_remove','cloud_update'].includes(job.action))refresh().catch(console.error);
        }
      }
      notify();
      if(interests.size&&Date.now()-lastRefresh>5000)refresh().catch(console.error);
    }catch(error){console.error("[Wired] Unavailable status",error);}
    if(polling)timer=setTimeout(poll,1000);
  }
  window.Wired={
    rpc, getSnapshot:()=>snapshot, getIntegration:()=>integration,
    subscribe(callback){listeners.add(callback);return()=>listeners.delete(callback);},
    watch(appid){if(!interests.has(String(appid))){interests.add(String(appid));refresh().catch(console.error);}},
    refresh,
    async start(action,args={}){
      const response=await rpc('StartTask',{action,args_json:JSON.stringify(args)});
      return response.job_id;
    },
    async run(action,args={}){
      const id=await this.start(action,args);
      const existing=snapshot.jobs.find(job=>job.id===id&&terminal(job));
      const job=existing||await new Promise(resolve=>completions.set(id,resolve));
      if(job.status!=='done')throw Error(job.message||"Operation canceled");
      return job.result;
    },
    async addToLibrary(appid){
      const result=await this.run('manifest_import',{appid:Number(appid)});
      await refresh();
      return result;
    },
    async removeFromLibrary(appid){
      const result=await this.run('integration_remove',{appid:Number(appid)});
      await refresh();
      return result;
    },
    async install(appid){
      await this.addToLibrary(appid);
      return this.nativeInstall(appid);
    },
    openFixes(appid){return rpc('OpenFixes',{appid:Number(appid)});},
    nativeInstall(appid){
      if(window.SteamClient?.Installs?.OpenInstallWizard)window.SteamClient.Installs.OpenInstallWizard([Number(appid)]);
      else window.location.href='steam://install/'+Number(appid);
    },
    downloads(){
      if(window.SteamClient?.Browser?.OpenURL)window.SteamClient.Browser.OpenURL('steam://nav/downloads');
      else window.location.href='steam://nav/downloads';
    },
    destroy(){polling=false;clearTimeout(timer);listeners.clear();}
  };
  polling=true;poll();
})();
