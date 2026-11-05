// Catalogs are bundled at build time. Translation never sends user data online.
(() => {
  const catalogs=window.WIRED_LOCALES||{en:{}},languages=window.WIRED_LANGUAGES||{english:'en',brazilian:'pt-BR'};
  let language='en';
  function normalize(value){
    const input=String(value||'').replace('_','-');
    return languages[input.toLowerCase()]||Object.keys(catalogs).find(code=>code.toLowerCase()===input.toLowerCase())||Object.keys(catalogs).find(code=>code===input.split('-')[0])||'en';
  }
  function detect(){
    // Steam's setting takes precedence over the store's per-page language.
    return window.g_strLanguage||new URLSearchParams(location.search).get('l')||document.cookie.match(/(?:^|;\s*)Steam_Language=([^;]+)/)?.[1]||document.documentElement.lang||'english';
  }
  language=normalize(detect());
  const ready=(async()=>{
    let deadline;
    const resolveLanguage=async()=>{
      try{const value=await window.SteamClient?.Settings?.GetCurrentLanguage?.();if(value)return value;}catch{/* Fall through to the persisted Steam setting. */}
      try{
        if(window.Millennium?.callServerMethod){
          const raw=await window.Millennium.callServerMethod('wired-millennium','WiredRPC',{payload_json:JSON.stringify({method:'GetLanguage',args:{}})});
          return (typeof raw==='string'?JSON.parse(raw):raw)?.language;
        }
      }catch{/* The store fallback remains available while the backend starts. */}
      return null;
    };
    const value=await Promise.race([resolveLanguage(),new Promise(resolve=>{deadline=setTimeout(()=>resolve(null),2000);})]);
    clearTimeout(deadline);if(value)language=normalize(value);return language;
  })();
  const patterns=new Map();
  function templatePatterns(catalog){
    if(patterns.has(catalog))return patterns.get(catalog);
    const list=Object.keys(catalog).filter(key=>/\{\d+\}/.test(key)).map(key=>{
      const slots=[];let position=0,expression='^';
      for(const match of key.matchAll(/\{(\d+)\}/g)){expression+=key.slice(position,match.index).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(.+?)';slots.push(match[1]);position=match.index+match[0].length;}
      expression+=key.slice(position).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$';
      return {key,slots,regex:new RegExp(expression)};
    }).sort((a,b)=>b.key.length-a.key.length);patterns.set(catalog,list);return list;
  }
  function t(value,parameters={}){
    if(typeof value!=='string'||!value)return value;
    const catalog=catalogs[language]||catalogs.en;
    let result=catalog[value];
    if(result===undefined){
      const trimmed=value.trim();
      if(catalog[trimmed]!==undefined)result=value.replace(trimmed,catalog[trimmed]);
      else if(language!=='en'){
        for(const pattern of templatePatterns(catalog)){const match=pattern.regex.exec(value);if(match){result=catalog[pattern.key].replace(/\{(\d+)\}/g,(_,slot)=>{const captured=match[pattern.slots.indexOf(slot)+1];return catalog[captured]??captured;});break;}}
        const prefix=Object.keys(catalog).filter(key=>key.length>3&&value.startsWith(key)&&key!==value).sort((a,b)=>b.length-a.length)[0];
        if(result===undefined&&prefix)result=catalog[prefix]+value.slice(prefix.length);
      }
    }
    result=result??value;
    for(const [key,replacement] of Object.entries(parameters))result=result.replaceAll('{'+key+'}',String(replacement));
    return result;
  }
  window.WiredI18n={t,ready,normalize,get language(){return language;},get direction(){return language==='ar'?'rtl':'ltr';}};
})();
