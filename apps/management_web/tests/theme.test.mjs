import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync(new URL('../static/theme.js',import.meta.url),'utf8');

// Exercise the actual head script before and after the shell has mounted.
function page(storage=new Map(),{denied=false,ready=false}={}){
  let mounted=ready,onReady,onClick;
  const root=new Map(),attrs=new Map(),label={textContent:''};
  const button={setAttribute:(key,value)=>attrs.set(key,value),
    querySelector:selector=>{assert.equal(selector,'.theme-label');return label;},
    addEventListener:(name,callback)=>{assert.equal(name,'click');onClick=callback;}};
  vm.runInNewContext(source,{
    window:{localStorage:{getItem:key=>{if(denied)throw new Error('disabled');return storage.get(key);},
      setItem:(key,value)=>{if(denied)throw new Error('disabled');storage.set(key,value);}}},
    document:{readyState:ready?'complete':'loading',
      documentElement:{setAttribute:(key,value)=>{assert.equal(key,'data-theme');root.set(key,value);}},
      getElementById:id=>{assert.equal(id,'theme-toggle');return mounted?button:null;},
      addEventListener:(name,callback,options)=>{assert.equal(name,'DOMContentLoaded');assert.equal(options.once,true);onReady=callback;}}
  });
  return {root,attrs,label,mount:()=>{mounted=true;onReady();},click:()=>onClick()};
}

test('first visit stays light; toggle exposes target action and persists the preference',()=>{
  const storage=new Map(),p=page(storage);
  assert.equal(p.root.get('data-theme'),'light');
  assert.equal(storage.size,0);
  p.mount();
  assert.equal(p.attrs.get('aria-pressed'),'false');
  assert.equal(p.attrs.get('aria-label'),'切换到深蓝主题');
  p.click();
  assert.equal(p.root.get('data-theme'),'dark');
  assert.equal(p.label.textContent,'深蓝主题');
  assert.equal(p.attrs.get('aria-label'),'切换到浅色主题');
  assert.equal(p.attrs.get('title'),'切换到浅色主题');
  assert.equal(p.attrs.get('aria-pressed'),'true');
  assert.deepEqual([...storage],[['fishery.ui.theme','dark']]);
  const refreshed=page(storage);
  assert.equal(refreshed.root.get('data-theme'),'dark');
  refreshed.mount();refreshed.click();
  assert.equal(refreshed.label.textContent,'浅色主题');
  assert.equal(storage.get('fishery.ui.theme'),'light');
});

test('saved dark preference is applied before the button exists',()=>{
  const p=page(new Map([['fishery.ui.theme','dark']]));
  assert.equal(p.root.get('data-theme'),'dark');
  assert.equal(p.attrs.size,0);
  p.mount();
  assert.equal(p.attrs.get('aria-pressed'),'true');
  assert.equal(p.label.textContent,'深蓝主题');
});

test('invalid persisted values are not interpreted as CSS or HTML',()=>{
  for(const value of ['system','DARK','<script>bad</script>',null]){
    const p=page(new Map([['fishery.ui.theme',value]]));p.mount();
    assert.equal(p.root.get('data-theme'),'light');
    assert.equal(p.label.textContent,'浅色主题');
  }
});

test('blocked storage still allows this tab to switch in either direction',()=>{
  const p=page(new Map(),{denied:true});p.mount();
  p.click();assert.equal(p.root.get('data-theme'),'dark');
  p.click();assert.equal(p.root.get('data-theme'),'light');
});

test('script also mounts after the document is ready without rerendering the application',()=>{
  const p=page(new Map(),{ready:true});
  p.click();assert.equal(p.root.get('data-theme'),'dark');
  assert.equal(p.attrs.get('aria-pressed'),'true');
});
