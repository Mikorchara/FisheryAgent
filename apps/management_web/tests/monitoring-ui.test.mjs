// Offline DOM behavior harness using Node built-ins, exercising the actual page code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

import {Element} from './dom-fixture.mjs';
import {restartHistory} from './chart-fixture.mjs';

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
  for(const file of ['view-model.js','components.js','services.js','assistant.js','app.js']){
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
test('all page timestamps display Beijing seconds and weighted length statistics remain distinct',async()=>{
  const d=fixture();d.cameras[0].summary.valid_frames=3;d.cameras[0].summary.frames_processed=4;
  d.cameras[0].summary.length={average_length_cm:17.5,length_sample_count:8,valid_frame_count:2,calibration:'simulated'};
  d.monitoring.trend=[{observed_at:'2026-10-14T00:00:00Z',dissolved_oxygen_mg_l:6.4},{observed_at:'2026-10-14T00:00:10Z',dissolved_oxygen_mg_l:6.4}];
  const p=page(d);await p.ready();
  for(const route of ['dashboard','monitoring','video','events']){
    p.run(`location.hash='#${route}';render()`);
    assert.match(p.node('content').textContent,/08:00:10 北京时间/);
  }
  p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/17.5 cm/);
  assert.match(p.node('content').textContent,/有效体长检测记录8/);
  assert.match(p.node('content').textContent,/体长有效帧2/);
  assert.match(p.node('content').textContent,/有效画面 \/ 总帧3 \/ 4/);
  d.cameras[0].summary.valid_frames=0;d.cameras[0].summary.visible_fish_count=null;
  d.cameras[0].summary.length={average_length_cm:null,length_sample_count:0,valid_frame_count:0,calibration:'uncalibrated'};
  p.setData(d);await p.run('refresh()');assert.match(p.node('content').textContent,/无有效帧/);
  assert.match(p.node('content').textContent,/画面平均可见数缺失/);
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

test('event lifecycle and critical severity are distinct from data quality and human handling',async()=>{
  const d=fixture();d.events=[
    {...d.events[0],id:'active',title:'低氧实验规则',severity:'critical',lifecycle_state:'ACTIVE',publication_status:'PROTOTYPE'},
    {...d.events[0],id:'unknown',title:'证据不足',lifecycle_state:'INDETERMINATE'},
    {...d.events[0],id:'resolved',title:'有效新观测',status:'closed',lifecycle_state:'RESOLVED'}];
  const p=page(d);await p.ready();p.run("location.hash='#events';render()");
  assert.match(p.node('content').textContent,/严重/);assert.match(p.node('content').textContent,/异常持续/);
  assert.match(p.node('content').textContent,/状态待确认/);assert.match(p.node('content').textContent,/已确认消退/);
  assert.match(p.node('content').textContent,/PROTOTYPE/);
  p.run("state.eventFilters.status='INDETERMINATE';render()");
  assert.match(p.node('content').textContent,/证据不足/);assert.doesNotMatch(p.node('content').textContent,/低氧实验规则/);
  p.run("location.hash='#monitoring';render()");assert.match(p.node('content').textContent,/PROTOTYPE/);
  d.cameras[0].signal_status='indeterminate';p.setData(d);p.run("location.hash='#video'");await p.run('refresh()');
  assert.match(p.node('content').textContent,/当前状态待确认/);
});


test('chart range controls render real page: default recent, all history, polling preserves selection',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  let nodes=walk(p.node('content'));
  assert.equal(nodes.filter(n=>n.tagName==='circle').length,85);
  const range=nodes.find(n=>n.tagName==='select'&&n.attributes['aria-label']==='历史范围');
  assert.ok(range);range.events.change({target:{value:'all'}});
  assert.equal(p.run('state.trendRange'),'all');
  nodes=walk(p.node('content'));assert.equal(nodes.filter(n=>n.tagName==='circle').length,214);
  await p.run('refresh()');assert.equal(p.run('state.trendRange'),'all');
  assert.equal(walk(p.node('content')).filter(n=>n.tagName==='circle').length,214);
  p.run("location.hash='#monitoring';render()");
  assert.equal(walk(p.node('content')).filter(n=>n.tagName==='circle').length,214);
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});
