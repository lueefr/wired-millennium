import assert from 'node:assert/strict';
import {readFile,readdir} from 'node:fs/promises';
import vm from 'node:vm';
const base=new URL('../locales/',import.meta.url),catalogs={};
for(const file of await readdir(base))if(file.endsWith('.json')&&file!=='languages.json')catalogs[file.slice(0,-5)]=JSON.parse(await readFile(new URL(file,base),'utf8'));
const languages=JSON.parse(await readFile(new URL('languages.json',base),'utf8'));
const source=await readFile(new URL('../public/i18n.js',import.meta.url),'utf8');
async function host({steam,persisted,html='en',search='',cookie=''}={}){
  const window={WIRED_LOCALES:catalogs,WIRED_LANGUAGES:languages};
  if(persisted)window.Millennium={callServerMethod:async()=>JSON.stringify({language:persisted})};
  if(steam)window.SteamClient={Settings:{GetCurrentLanguage:async()=>steam}};
  vm.runInNewContext(source,{window,document:{cookie,documentElement:{lang:html}},location:{search},URLSearchParams,setTimeout,clearTimeout});
  await window.WiredI18n.ready;return window.WiredI18n;
}
const brazil=await host({steam:'brazilian',html:'en'});
assert.equal(brazil.language,'pt-BR');assert.equal(brazil.t('Providers'),catalogs['pt-BR'].Providers);assert.notEqual(brazil.t('Providers'),'Providers');
assert.equal((await host({steam:'english',html:'pt-BR',search:'?l=german'})).language,'en','Steam client must take precedence');
assert.equal((await host({search:'?l=tchinese'})).language,'zh-TW');
assert.equal((await host({cookie:'Steam_Language=latam'})).language,'es-419');
assert.equal((await host({steam:'arabic'})).direction,'rtl');
assert.equal((await host({steam:'unknown-language'})).language,'en');
assert.equal(brazil.t('Unknown upstream error'),'Unknown upstream error');
assert.equal(brazil.t(123),123);
assert.equal((await host({persisted:'brazilian',html:'en',search:'?l=german'})).language,'pt-BR','Persisted Steam setting must win in isolated store contexts');
assert.equal(brazil.t('Apply Example?'),catalogs['pt-BR']['Apply {0}?'].replace('{0}','Example'));
assert.equal(brazil.t('Connected:Example'),catalogs['pt-BR']['Connected:{0}'].replace('{0}','Example'));
for(const [steam,locale] of Object.entries(languages))assert.equal((await host({steam})).language,locale);
console.log(`Localization OK: ${Object.keys(languages).length} Steam language mappings, client precedence, store fallback, RTL and English fallback`);
