// Offline DOM behavior harness using Node built-ins, exercising the actual page code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.attributes={};this.events={};this._text='';this.classes=new Set();
    this.classList={add:(c)=>this.classes.add(c),remove:(c)=>this.classes.delete(c),contains:(c)=>this.classes.has(c),toggle:(c,on)=>{const v=on??!this.classes.has(c);v?this.classes.add(c):this.classes.delete(c);return v;}};}
  set textContent(value){this._text=String(value??'');this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this._text='';this.children=[];this.append(...nodes);}
  setAttribute(k,v){this.attributes[k]=v;if(k==='href'){this.hash=v.startsWith('#')?v:'';}if(k==='value')this.value=v;}
  removeAttribute(k){delete this.attributes[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  contains(node){return this===node||this.children.some(c=>c.contains(node));}
  matches(selector){return selector.split(',').includes(this.tagName);}
  focus(){}
  close(){}
  showModal(){}
}
function fixture(oxygen=6.4){
  const time='2026-10-14T00:00:10+00:00';
  const window={start:'2026-10-14T00:00:00+00:00',end:time,duration_s:10};
  return {schema_version:1,application:'management-web-r1',data_mode:'simulator',devices:[{id:'sim-pond-1',name:'模拟池'}],
    monitoring:{source_kind:'simulator',source:'连续模拟器',quality:'valid',freshness:'fresh',connectivity:'online',aggregation:'window_mean',window,batch_id:'batch-1',observed_at:time,received_at:time,evaluated_at:time,findings:[],metrics:[
      {id:'temperature_c',label:'水温',value:26.4,unit:'°C',quality:'valid',valid_samples:10,sample_count:10},
      {id:'ph',label:'pH',value:7.5,unit:'',quality:'valid',valid_samples:10,sample_count:10},
      {id:'dissolved_oxygen_mg_l',label:'溶解氧',value:oxygen,unit:'mg/L',quality:'valid',valid_samples:10,sample_count:10}],trend:[]},
    cameras:[{id:'sim-pond-1',name:'模拟池视觉',source_kind:'simulator',status:'online',freshness:'fresh',observed_at:time,received_at:time,window,batch_id:'batch-1',stream_url:null,summary:{frames_processed:20,anomaly_counts:{suspected_lesion:3,surface_anomaly:2,suspected_dead:0},behavior_ratios:{normal_activity:.6,reduced_activity:.1,feeding:.2,feeding_anomaly:.1,unknown:0},length:{average_length_cm:null,length_sample_count:0,calibration:'uncalibrated'},visible_fish_count:8,model_version:'synthetic-v1'}}],
    events:[{id:'event-1',device:'sim-pond-1',severity:'warning',status:'pending',title:'疑似异常（模拟）',type:'视觉',source_kind:'simulator',occurred_at:time,batch_id:'batch-1',attachments:[]}],files:[],ai:{connected:false},connections:[{name:'监测数据',status:'online'}]};
}
function page(data=fixture()){
  const elements=new Map();const node=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const env=new Element(),skip=new Element();const timers=[];const events={};const requests=[];
  let current=data;
  const document={hidden:false,activeElement:null,getElementById:node,createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
    createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;},
    querySelector:s=>s==='.environment'?env:skip,querySelectorAll:()=>node('navigation').children,addEventListener:()=>{}};
  const context=vm.createContext({document,Node:Element,URLSearchParams,Intl,Date,console,location:{hash:'#dashboard'},
    window:{addEventListener:(type,fn)=>events[type]=fn,scrollTo:()=>{}},
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearInterval:()=>{},
    fetch:async url=>{requests.push(url);if(current instanceof Error)throw current;return {ok:true,json:async()=>structuredClone(current)};}});
  for(const file of ['view-model.js','components.js','services.js','app.js']){
    let source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8');
    source=source.replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  return {context,node,timers,events,requests,env,document,setData:d=>{current=d;},run:code=>vm.runInContext(code,context),
    ready:async()=>{await new Promise(r=>setImmediate(r));}};
}

test('uniform server state renders dashboard, monitoring and visual summaries with no fake video',async()=>{
  const p=page();await p.ready();
  assert.match(p.node('content').textContent,/6.4/);assert.match(p.env.textContent,/本机模拟/);
  p.run("location.hash='#monitoring';render()");
  assert.match(p.node('content').textContent,/窗口均值/);assert.doesNotMatch(p.node('content').textContent,/演示数据状态/);
  p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/疑似病灶/);assert.match(p.node('content').textContent,/未标定/);
  assert.match(p.node('content').textContent,/不代表鱼池存量/);assert.match(p.node('content').textContent,/无视频流/);
});
test('five second read polling updates received values and preserves draft, filters and source status',async()=>{
  const p=page();await p.ready();assert.equal(p.timers[0].ms,5000);
  p.run("state.draft='保留草稿';state.eventFilters.q='疑似';");
  p.setData(fixture(2.2));await p.run('refresh()');
  assert.match(p.node('content').textContent,/2.2/);
  assert.equal(p.run('state.draft'),'保留草稿');assert.equal(p.run('state.eventFilters.q'),'疑似');
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
  assert.ok(p.requests.every(url=>!url.includes('ingestion')&&!url.includes('apply')));
  const stale=fixture();stale.monitoring.freshness='stale';stale.monitoring.connectivity='offline';p.setData(stale);await p.run('refresh()');
  assert.match(p.node('content').textContent,/已过期/);assert.match(p.node('content').textContent,/上报中断/);
});
test('NO_DATA, partial, invalid and read failure never substitute normal values; reconnect recovers',async()=>{
  const d=fixture();d.monitoring.quality='missing';d.monitoring.freshness='unknown';d.monitoring.observed_at=null;d.cameras[0].summary=null;
  for(const m of d.monitoring.metrics){m.value=null;m.quality='missing';}
  const p=page(d);await p.ready();assert.doesNotMatch(p.node('content').textContent,/6.4/);
  p.run("location.hash='#video';render()");assert.match(p.node('content').textContent,/NO_DATA/);
  for(const quality of ['partial','invalid']){const next=fixture();next.monitoring.quality=quality;next.monitoring.metrics[2].value=null;next.monitoring.metrics[2].quality=quality==='partial'?'missing':'invalid';p.setData(next);p.run("location.hash='#monitoring'");await p.run('refresh()');assert.match(p.node('content').textContent,/—/);}
  p.setData(new Error('private-details-should-not-display'));await p.run('refresh()');
  assert.match(p.node('content').textContent,/显示已失效/);assert.doesNotMatch(p.node('content').textContent,/private-details/);
  p.run("location.hash='#assistant';render()");assert.match(p.node('content').textContent,/显示已失效/);
  p.setData(fixture());await p.run('refresh()');assert.match(p.node('content').textContent,/尚未接入/);
});
test('obsolete in-flight read cannot overwrite a new device selection',async()=>{
  const p=page();await p.ready();
  let resolve;
  p.context.fetch=()=>new Promise(r=>resolve=r);
  const pending=p.run('refresh()');p.run('state.revision++');
  resolve({ok:true,json:async()=>fixture(1)});await pending;
  assert.equal(p.run('state.data.monitoring.metrics[2].value'),6.4);
});
test('seven pages remain navigable; only text renders and AI stays disabled',async()=>{
  const d=fixture();d.events[0].title='<script>fake()</script>';
  const p=page(d);await p.ready();
  for(const route of ['dashboard','monitoring','assistant','video','events','knowledge','settings']){
    p.run(`location.hash='#${route}';render()`);assert.ok(p.node('content').children.length);
  }
  p.run("location.hash='#events';render()");assert.match(p.node('content').textContent,/<script>fake\(\)<\/script>/);
  assert.equal(p.context.fake,undefined);
  p.run("location.hash='#assistant';render()");assert.match(p.node('content').textContent,/发送 · 尚未接入/);
});
