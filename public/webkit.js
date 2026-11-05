// Place a native-looking action beside the app's Community Hub link.
(async () => {
  await window.WiredI18n?.ready;
  const t=window.WiredI18n?.t||((text)=>text);
  const W=window.Wired;if(!W)return;
  let current=null,root=null,message=null,removeButton=null,wrapper=null,drmBadge=null,reference=null,layoutChanges=[],cleanup=()=>{},busy=false;
  const terminal=job=>['done','cancelled','error'].includes(job.status);
  function communityLink(appid){
    const links=Array.from(document.querySelectorAll('a[href]'));
    return links.find(link=>{
      try{const url=new URL(link.getAttribute('href'),location.href);return /^(?:www\.)?steamcommunity\.com$/i.test(url.hostname)&&new RegExp('^/app/'+appid+'/?$').test(url.pathname);}
      catch{return false;}
    })||links.find(link=>{try{const url=new URL(link.getAttribute('href'),location.href);return Boolean(link.closest('.apphub_HeaderStandardTop'))&&/^(?:www\.)?steamcommunity\.com$/i.test(url.hostname)&&/^\/app\/\d+\/?$/.test(url.pathname);}catch{return false;}});
  }
  function unmount(){cleanup();drmBadge?.remove();drmBadge=null;for(const [node,key,before,applied] of layoutChanges){if(node.style.getPropertyValue(key)===applied){if(before)node.style.setProperty(key,before);else node.style.removeProperty(key);}}layoutChanges=[];wrapper?.remove();root?.remove();message?.remove();removeButton?.remove();root=null;message=null;removeButton=null;wrapper=null;reference=null;busy=false;}
  function mount(){
    const match=location.pathname.match(/^\/(?:app|games)\/(\d+)(?:\/|$)/);
    const appid=match?Number(match[1]):null;
    const anchor=appid?communityLink(appid):null;
    if(root&&(!root.isConnected||current!==appid||reference!==anchor||wrapper?.previousElementSibling!==anchor))unmount();
    if(root){wrapper?.updateDenuvo?.();return;}
    if(!anchor||!appid)return;
    current=appid;reference=anchor;W.watch(appid);
    const button=anchor.cloneNode(true);root=button;button.dataset.wiredStore=String(appid);
    for(const node of [button,...button.querySelectorAll('*')]){
      node.removeAttribute('id');
      for(const attribute of Array.from(node.attributes))if(attribute.name.startsWith('on'))node.removeAttribute(attribute.name);
    }
    for(const attribute of ['target','download','aria-controls','aria-describedby','aria-labelledby','data-tooltip-text','data-ds-appid'])button.removeAttribute(attribute);
    button.href='#';button.setAttribute('role','button');button.setAttribute('aria-label','Add wire');
    const label=button.querySelector('span')||button;label.replaceChildren(document.createTextNode(t('Add wire')));
    const status=document.createElement('span');message=status;status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.hidden=true;
    const remove=button.cloneNode(true);removeButton=remove;delete remove.dataset.wiredStore;remove.dataset.wiredRemove=String(appid);remove.setAttribute('aria-label','Remove');(remove.querySelector('span')||remove).textContent=t('Remove');
    const fixes=button.cloneNode(true);delete fixes.dataset.wiredStore;fixes.dataset.wiredFixes=String(appid);fixes.setAttribute('aria-label','Fixes');fixes.title=t('lua.tools fixes for this game');(fixes.querySelector('span')||fixes).textContent=t('Fixes');
    const group=document.createElement('div');wrapper=group;group.dataset.wiredActions=String(appid);group.style.display='contents';
    const notice=button.cloneNode(false);delete notice.dataset.wiredStore;notice.removeAttribute('href');drmBadge=notice;notice.dataset.wiredDenuvo=String(appid);notice.setAttribute('role','note');notice.setAttribute('aria-label','Uses Denuvo');notice.title=t('Denuvo reported on the official Steam page');
    const badgeLabel=document.createElement('span');badgeLabel.textContent='Denuvo';notice.append(badgeLabel);
    const buttons=group;group.append(button,remove,status);anchor.after(group);
    function layout(node,key,value){if(!node)return;let record=layoutChanges.find(item=>item[0]===node&&item[1]===key);if(!record){record=[node,key,node.style.getPropertyValue(key),value];layoutChanges.push(record);}record[3]=value;if(node.style.getPropertyValue(key)!==value)node.style.setProperty(key,value);}
    const originalButtonStyle=getComputedStyle(anchor);
    const originalButtonGap=(parseFloat(originalButtonStyle.marginLeft)||0)+(parseFloat(originalButtonStyle.marginRight)||0);
    for(const element of [anchor,button,remove,fixes,notice]){layout(element,'margin-left','0px');layout(element,'margin-right','0px');}
    const actionRow=anchor.parentElement;
    layout(actionRow,'display','inline-flex');layout(actionRow,'align-items','center');layout(actionRow,'flex-wrap','wrap');
    const header=anchor.closest('.apphub_HeaderStandardTop');
    if(header&&getComputedStyle(header).display.includes('flex')){
      layout(header,'align-items','center');layout(header,'flex-wrap','wrap');layout(header,'flex-direction','row');layout(header,'justify-content','flex-start');
      layout(actionRow,'display','contents');
      layout(status,'order','40');layout(status,'font-size','0.7em');layout(status,'flex','0 1 auto');layout(status,'min-width','0px');layout(status,'max-width','26em');layout(status,'overflow','hidden');layout(status,'text-overflow','ellipsis');layout(status,'white-space','nowrap');
      for(const node of actionRow.children){if(node!==anchor&&node!==group)layout(node,'order','30');}
      for(const node of [button,fixes,remove])layout(node,'order','10');
      const title=header.querySelector('.apphub_AppName');
      if(title){layout(title,'order','-20');layout(title,'flex','0 1 auto');layout(title,'min-width','0px');layout(title,'max-width','100%');layout(title,'overflow-wrap','anywhere');}
    }
    layout(actionRow,'max-width','100%');layout(actionRow,'min-width','0px');layout(actionRow,'height','auto');layout(actionRow,'overflow','visible');
    for(const element of [anchor,button,remove,fixes,notice]){layout(element,'flex-shrink','0');layout(element,'white-space','nowrap');}
    const headerPadding=header?{left:parseFloat(getComputedStyle(header).paddingLeft)||0,right:parseFloat(getComputedStyle(header).paddingRight)||0}:null;
    function themeSpacing(){
      const override=layoutChanges.find(item=>item[0]===actionRow&&item[1]==='column-gap');
      if(override){if(override[2])actionRow.style.columnGap=override[2];else actionRow.style.removeProperty('column-gap');}
      let gap=parseFloat(getComputedStyle(actionRow).columnGap);
      if(!(gap>0)){
        const nativeRow=Array.from(document.querySelectorAll('.queue_actions_ctn, .steamdb-buttons, .game_purchase_action_bg')).find(node=>node!==actionRow&&parseFloat(getComputedStyle(node).columnGap)>0);
        gap=nativeRow?parseFloat(getComputedStyle(nativeRow).columnGap):0;
      }
      if(!(gap>0))gap=originalButtonGap;
      if(!(gap>0))gap=parseFloat(getComputedStyle(anchor).fontSize)*.4||6;
      layout(actionRow,'column-gap',gap+'px');layout(actionRow,'row-gap',gap+'px');
      if(header){
        layout(header,'column-gap',gap+'px');layout(header,'row-gap',gap+'px');
        // Themes may absolutely position wishlist/follow/ignore over the title row.
        // Reserve their measured width rather than letting flex items flow beneath.
        const bounds=header.getBoundingClientRect();let left=headerPadding.left,right=headerPadding.right;
        for(const controls of document.querySelectorAll('.queue_overflow_ctn')){
          const position=getComputedStyle(controls).position,rect=controls.getBoundingClientRect();
          if(!['absolute','fixed'].includes(position)||!rect.width||rect.bottom<=bounds.top||rect.top>=bounds.bottom)continue;
          if(rect.left>=bounds.left+bounds.width/2&&rect.left<bounds.right)right=Math.max(right,bounds.right-rect.left+gap);
          else if(rect.right>bounds.left&&rect.right<=bounds.left+bounds.width/2)left=Math.max(left,rect.right-bounds.left+gap);
        }
        layout(header,'box-sizing','border-box');layout(header,'padding-left',left+'px');layout(header,'padding-right',right+'px');
      }
    }
    function updateDenuvo(){
      themeSpacing();
      if(header){
        const title=header.querySelector('.apphub_AppName');if(title)layout(title,'order','-20');
        for(const node of header.children)if(node!==title&&node!==actionRow&&/^Proton\s*:/i.test(node.textContent.trim()))layout(node,'order','30');
        for(const node of actionRow.children)if(node!==anchor&&node!==group&&node!==notice)layout(node,'order','30');
        for(const node of [button,fixes,remove])layout(node,'order','10');
      }
      const official=Array.from(document.querySelectorAll('.DRM_notice, .game_area_drm_notice')).find(node=>node!==notice&&!group.contains(node)&&/denuvo/i.test(node.textContent));
      // Button geometry and fonts come from Community Hub; warning colors come
      // from Steam's DRM notice in the current theme, never a fixed palette.
      for(const element of [button,remove,fixes,notice])if(element.className!==anchor.className)element.className=anchor.className;
      for(const element of [button,remove,fixes,notice]){for(const attribute of ['title','aria-label']){const value=element.getAttribute(attribute);if(value&&t(value)!==value)element.setAttribute(attribute,t(value));}}
      if(official){
        const theme=getComputedStyle(official);
        const transparent=theme.backgroundColor==='transparent'||/rgba\([^)]*,\s*0\s*\)/.test(theme.backgroundColor);
        const background=transparent?'color-mix(in srgb, '+theme.color+' 25%, transparent)':theme.backgroundColor;
        if(notice.style.getPropertyValue('background')!==background)notice.style.setProperty('background',background,'important');
        const geometry=getComputedStyle(anchor);
        notice.style.setProperty('border-radius',geometry.borderRadius);
        notice.style.setProperty('min-height',anchor.getBoundingClientRect().height+'px');
        notice.style.setProperty('box-sizing','border-box');
        if(notice.style.color!==theme.color)notice.style.setProperty('color',theme.color,'important');
        notice.style.cursor='default';badgeLabel.style.setProperty('background','transparent','important');badgeLabel.style.setProperty('color','inherit','important');
        if(notice.nextElementSibling!==anchor)anchor.before(notice);
      }else notice.remove();
    }
    group.updateDenuvo=updateDenuvo;updateDenuvo();
    function show(text){const compact=text.startsWith("Providers did not return a valid package.")?"Providers did not return a valid package.":text;if(status.textContent!==compact)status.textContent=t(compact);status.title=t(text);status.hidden=!text;}
    function update(){
      if(root!==button)return;
      updateDenuvo();
      const app=W.getIntegration()?.apps?.[String(appid)];
      const job=W.getSnapshot().jobs.slice().reverse().find(job=>Number(job.appid)===appid&&!terminal(job));
      const disabled=busy||Boolean(job)||Boolean(app?.added);
      button.setAttribute('aria-disabled',String(disabled));
      const eligible=Boolean(app?.added&&app?.installed);
      if(eligible&&button.nextElementSibling!==fixes)button.after(fixes);else if(!eligible)fixes.remove();
      fixes.setAttribute('aria-disabled',String(busy||Boolean(job)));
      const beforeRemove=eligible?fixes:button;
      if(app?.managed&&remove.previousElementSibling!==beforeRemove)beforeRemove.after(remove);
      else if(!app?.managed)remove.remove();
      remove.hidden=!app?.managed;remove.setAttribute('aria-disabled',String(busy||Boolean(job)));remove.title=t('Remove from library; Game files and saves will be preserved');
      button.title=t(busy||job?"Preparing game…":app?.added?"Game added to library. Install from the library whenever you want.":"Add this game via Wired");
      const text=app?.added?'Added wire':busy||job?'Adding…':'Add wire';if(label.textContent!==t(text))label.textContent=t(text);
      if(job)show(job.message||"Preparing…");
    }
    async function activate(event){
      event.preventDefault();event.stopPropagation();
      if(button.getAttribute('aria-disabled')==='true')return;
      busy=true;show('');update();
      try{await W.addToLibrary(appid);show("Added to library.");}
      catch(error){show(String(error.message||error));}
      finally{if(root===button){busy=false;update();}}
    }
    fixes.addEventListener('click',async event=>{event.preventDefault();event.stopPropagation();if(fixes.getAttribute('aria-disabled')==='true')return;const app=W.getIntegration()?.apps?.[String(appid)];if(!app?.added||!app?.installed)return;try{await W.openFixes(appid);}catch(error){show(String(error.message||error));}});
    remove.addEventListener('click',async event=>{event.preventDefault();event.stopPropagation();if(remove.getAttribute('aria-disabled')==='true')return;busy=true;show('');update();try{await W.removeFromLibrary(appid);show("Removed from library. Files and saves preserved.");}catch(error){show(String(error.message||error));}finally{if(root===button){busy=false;update();}}});
    button.addEventListener('click',activate);
    button.addEventListener('keydown',event=>{if(event.key===' '){event.preventDefault();button.click();}});
    const unsubscribe=W.subscribe(update);
    const resize=()=>{if(root===button)updateDenuvo();};
    window.addEventListener('resize',resize);
    const observer=typeof ResizeObserver==='function'?new ResizeObserver(resize):null;
    if(header)observer?.observe(header);
    cleanup=()=>{unsubscribe();observer?.disconnect();window.removeEventListener('resize',resize);};update();
  }
  let pending=false;new MutationObserver(()=>{if(!pending){pending=true;setTimeout(()=>{pending=false;mount();},150);}}).observe(document.documentElement,{childList:true,subtree:true});mount();
})();
