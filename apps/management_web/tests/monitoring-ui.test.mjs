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
function page(data=fixture(),handler=null){
  const elements=new Map();const node=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const env=new Element(),skip=new Element();const timers=[];const events={};const requests=[];
  let current=data;
  const document={hidden:false,activeElement:null,getElementById:node,createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
    createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;},
    querySelector:s=>s==='.environment'?env:skip,querySelectorAll:()=>node('navigation').children,addEventListener:()=>{}};
  const context=vm.createContext({document,Node:Element,URLSearchParams,Intl,Date,console,location:{hash:'#dashboard'},
    crypto:{randomUUID:()=> '00000000-0000-4000-8000-000000000001'},
    window:{addEventListener:(type,fn)=>events[type]=fn,scrollTo:()=>{}},
    setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length;},clearInterval:()=>{},
    fetch:async (url,options)=>{requests.push(url);if(handler)return handler(url,options,current);if(current instanceof Error)throw current;
      return {ok:true,json:async()=>url.startsWith('/api/knowledge')?
        {items:[],total:0,categories:[],offset:0,limit:50,write_token:'fictional-knowledge-token'}:structuredClone(current)};}});
  for(const file of ['view-model.js','components.js','assistant-events.js','services.js','assistant.js','tool-policy.js','knowledge.js','settings.js','app.js']){
    let source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8');
    source=source.replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  return {context,node,timers,events,requests,env,document,setData:d=>{current=d;},run:code=>vm.runInContext(code,context),
    ready:async()=>{await new Promise(r=>setImmediate(r));}};
}

test('SIMPLIFY-1 uses server cycles on homepage and list, then fetches the original detail',async()=>{
  const d=fixture();d.event_management={enabled:true,ack_enabled:true};
  const original={...d.events[0],id:'critical',device_id:'sim-pond-1',channel:'water',code:'OXYGEN_CRITICAL_LOW',title:'溶氧低 (2.2 mg/L)',lifecycle_state:'ACTIVE'};
  d.events=[{...original,id:'low',code:'OXYGEN_LOW'},original];
  const cycle={...original,title:'溶解氧偏低风险',deletable:false,cycle_summary:{key:'stable-cycle',count:2,
    member_ids:['low','critical'],detail_event_id:'critical',ended:false,reading_label:'最新异常观测',reading:original.title}};
  d.event_cycles=[cycle];const queries=[];
  const p=page(d,async(url)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(d)};
    if(url.startsWith('/api/events?')){queries.push(new URL(url,'http://localhost').searchParams);return {ok:true,json:async()=>({items:d.event_cycles,total:1,offset:0,limit:50})};}
    if(url==='/api/events/critical')return {ok:true,json:async()=>structuredClone(original)};
    return {ok:true,json:async()=>({items:[]})};
  });
  await p.ready();assert.match(p.node('content').textContent,/2 条原始记录/);
  p.run("location.hash='#events';render()");await p.ready();
  assert.equal(queries.at(-1).get('view'),'cycles');
  assert.match(p.node('content').textContent,/共 1 条符合条件/);
  assert.match(p.node('content').textContent,/异常中/);
  await p.run('showEventDetail(state.data.event_cycles[0])');
  assert.equal(p.node('dialog-title').textContent,original.title);
  assert.match(p.node('dialog-body').textContent,/critical/);
  cycle.lifecycle_state='RESOLVED';cycle.status='closed';cycle.resolved_at=d.monitoring.observed_at;
  Object.assign(cycle.cycle_summary,{ended:true,reading_label:'异常时读数'});
  await p.run('refresh()');p.run("location.hash='#events';render()");await p.ready();
  assert.match(p.node('content').textContent,/已恢复/);
  assert.match(p.node('content').textContent,/异常时读数/);
  assert.match(p.node('content').textContent,/历史最高等级/);
});

test('uniform server state renders dashboard, monitoring and visual summaries with no fake video',async()=>{
  const p=page();await p.ready();
  assert.equal(p.document.title,'综合总览 · AI 监测系统');
  assert.match(p.node('content').textContent,/6.4/);assert.match(p.env.textContent,/本机模拟/);
  p.run("location.hash='#monitoring';render()");
  assert.equal(p.document.title,'水质监测 · AI 监测系统');
  assert.match(p.node('content').textContent,/窗口均值/);assert.doesNotMatch(p.node('content').textContent,/演示数据状态/);
  p.run("location.hash='#video';render()");
  assert.match(p.node('content').textContent,/疑似病灶/);assert.match(p.node('content').textContent,/未标定/);
  assert.match(p.node('content').textContent,/不代表鱼池存量/);assert.match(p.node('content').textContent,/无视频流/);
});

test('EVT-2 homepage collapses risk grades but retains unknown evidence and original detail',async()=>{
  const d=fixture();const common={...d.events[0],device_id:'sim-pond-1',channel:'water',
    risk_family:{episode_id:'same-low-oxygen',label:'溶解氧偏低风险',transitions:[]},family_current_event_id:'critical',family_current_code:'OXYGEN_CRITICAL_LOW'};
  d.events=[{...common,id:'low',title:'溶氧偏低',severity:'warning',lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE'},
    {...common,id:'critical',title:'溶氧低',severity:'critical',lifecycle_state:'ACTIVE',last_observed_at:d.monitoring.observed_at}];
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  let overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.equal(walk(overview).filter(n=>n.attributes['data-event-id']).length,1);
  assert.match(overview.textContent,/溶氧低/);assert.doesNotMatch(overview.textContent,/溶氧偏低/);
  assert.match(overview.textContent,/关联 2 条等级记录/);
  for(const e of d.events){e.lifecycle_state='INDETERMINATE';e.family_current_code=null;e.family_current_event_id=null;}
  p.setData(d);await p.run('refresh()');
  overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.equal(walk(overview).filter(n=>n.attributes['data-event-id']).length,1);
  assert.match(overview.textContent,/当前等级未知/);assert.doesNotMatch(overview.textContent,/当前未见异常信号/);
});

function eventPage({conflict=false,legacy=false}={}){
  const data=fixture();data.event_management={enabled:true,write_token:'fictional-event-capability'};
  const record={...data.events[0],id:'closed-record',lifecycle_state:'RESOLVED',status:'closed',deletable:true,
    channel:'visual',resolved_at:data.monitoring.observed_at};
  if(legacy)Object.assign(record,{legacy_closed:true,lifecycle_state:'INDETERMINATE',state_reason:'LEGACY_UNREVIEWED',
    handling:{state:'PENDING',ended:true,can_ack:false,action_count:0,history:[],unavailable_reason:'LEGACY_OR_UNSUPPORTED_IDENTITY'}});
  data.events=[record];let records=[record];const writes=[],queries=[];
  const p=page(data,async(url,options)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(data)};
    if(url.startsWith('/api/events?')){const query=new URL(url,'http://localhost').searchParams;queries.push(query);
      return {ok:true,json:async()=>({items:Number(query.get('offset'))===50?[]:structuredClone(records),
        total:records.length?51:0,limit:50,offset:Number(query.get('offset'))})};}
    if(url.startsWith('/api/events/')){
      writes.push({url,value:JSON.parse(options.body),token:options.headers['X-Management-Events']});
      if(url.endsWith('deletion-preview'))return {ok:true,json:async()=>({count:1,legacy_count:legacy?1:0,revision:'f'.repeat(64)})};
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_DELETE_CONFLICT'})};
      records=[];data.events=[];return {ok:true,json:async()=>({deleted_count:1})};
    }
    return {ok:true,json:async()=>({items:[],total:0})};
  });
  const walk=node=>[node,...node.children.flatMap(walk)];
  return {...p,writes,queries,walk,findButton:(root,text)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text),
    open:async()=>{await p.ready();p.run("location.hash='#events';render()");await p.ready();}};
}

function ackPage({conflict=false,legacy=false,ended=false,cycleDelete=false}={}){
  const data=fixture();data.event_management={enabled:true,ack_enabled:true,write_token:'fictional-event-token'};
  const item={...data.events[0],device_id:'sim-pond-1',channel:'visual',lifecycle_state:ended?'RESOLVED':'ACTIVE',
    status:ended?'closed':'pending',deletable:false,can_delete_ack_cycle:ended&&cycleDelete,deletion_block_reason:ended?'ACK_AUDIT_RETAINED':null,
    handling:{state:'PENDING',ended,can_ack:!legacy&&!ended,cycle_id:'a'.repeat(64),grade_token:'b'.repeat(64),
      grade_version:'fixture-grades-v1',revision:0,action_count:0,history:[],unavailable_reason:legacy?'LEGACY_OR_UNSUPPORTED_IDENTITY':null}};
  data.events=[item];const writes=[];
  const p=page(data,async(url,options)=>{
    if(url.startsWith('/api/bootstrap'))return {ok:true,json:async()=>structuredClone(data)};
    if(url.startsWith('/api/events?'))return {ok:true,json:async()=>({items:structuredClone(data.events),total:1,limit:50,offset:0})};
    if(url==='/api/events/deletion-preview')return {ok:true,json:async()=>({count:2,ack_count:2,revision:'c'.repeat(64)})};
    if(url==='/api/events/delete'){
      writes.push({value:JSON.parse(options.body),headers:options.headers});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_DELETE_CONFLICT'})};
      data.events=[];return {ok:true,json:async()=>({deleted_count:2,deleted_ack_count:2})};
    }
    if(url==='/api/events/ack'){
      writes.push({value:JSON.parse(options.body),headers:options.headers});
      if(conflict)return {ok:false,json:async()=>({error_code:'EVENT_ACK_CONFLICT'})};
      item.handling={...item.handling,state:'ACKNOWLEDGED',can_ack:false,revision:1,acked_at:data.monitoring.observed_at,
        latest_ack_at:data.monitoring.observed_at,actor_kind:'local_visitor',action_count:1,
        history:[{acted_at:data.monitoring.observed_at,event_title:'疑似病灶检测信号',grade_code:'SUSPECTED_LESION',actor_kind:'local_visitor'}]};
      return {ok:true,json:async()=>({status:'ACK_RECORDED'})};
    }
    if(url==='/api/events/'+item.id)return {ok:true,json:async()=>structuredClone(item)};
    return {ok:true,json:async()=>({items:[],total:0})};
  });
  const walk=node=>[node,...node.children.flatMap(walk)];
  const find=(root,text)=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text);
  return {...p,writes,item,find,walk,open:async()=>{await p.ready();p.run('eventDetail(state.data.events[0])');}};
}

test('EVT-3A explicit ACK confirmation, cancellation and reload preserve separate observation state',async()=>{
  const p=ackPage();await p.open();
  assert.match(p.node('content').textContent,/待确认/);
  assert.ok(p.find(p.node('dialog-body'),'确认已知晓'));
  assert.equal(p.walk(p.node('content')).filter(n=>n.tagName==='button'&&n.textContent==='确认已知晓').length,0);
  p.find(p.node('dialog-body'),'确认已知晓').events.click();
  assert.equal(p.writes.length,0);assert.match(p.node('dialog-body').textContent,/不代表经过认证/);
  p.find(p.node('dialog-body'),'取消').events.click();assert.equal(p.writes.length,0);
  p.find(p.node('dialog-body'),'确认已知晓').events.click();
  p.find(p.node('dialog-body'),'确认知晓此风险').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].headers['X-Management-Events'],'fictional-event-token');
  assert.equal(p.writes[0].value.grade_token,'b'.repeat(64));assert.equal(p.writes[0].value.revision,0);
  assert.match(p.node('dialog-body').textContent,/已知晓/);assert.match(p.node('dialog-body').textContent,/本机操作（未认证访客）/);
  assert.match(p.node('dialog-body').textContent,/异常持续/);
  assert.equal(p.find(p.node('dialog-body'),'确认已知晓'),undefined);
  await p.run('refresh()');assert.match(p.node('content').textContent,/已知晓/);
  p.run("location.hash='#events';render()");await p.ready();assert.match(p.node('content').textContent,/已知晓/);
});

test('EVT-3A conflicts never retry; unsupported legacy and protected audit records cannot ACK or delete',async()=>{
  const p=ackPage({conflict:true});await p.open();
  p.find(p.node('dialog-body'),'确认已知晓').events.click();p.find(p.node('dialog-body'),'确认知晓此风险').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.match(p.node('dialog-title').textContent,/确认未完成/);
  assert.match(p.node('dialog-body').textContent,/未自动重试/);assert.match(p.node('content').textContent,/待确认/);
  const old=ackPage({legacy:true});await old.open();
  assert.equal(old.find(old.node('dialog-body'),'确认已知晓'),undefined);assert.match(old.node('dialog-body').textContent,/仅供查看/);
  const ended=ackPage({ended:true});ended.item.handling.action_count=1;
  ended.item.handling.history=[{acted_at:'2026-10-23T00:00:00Z',grade_code:'SUSPECTED_LESION'}];
  await ended.open();assert.match(ended.node('dialog-body').textContent,/历史已知晓/);
  assert.equal(ended.find(ended.node('dialog-body'),'确认已知晓'),undefined);
  ended.run("location.hash='#events';render()");await ended.ready();
  assert.match(ended.node('content').textContent,/知晓审计留存，不可删除/);
});

test('ended ACK cycle deletion previews both counts, cancellation keeps data, explicit commit uses revision',async()=>{
  const p=ackPage({ended:true,cycleDelete:true});p.item.handling.confirmed=true;await p.open();
  p.run("location.hash='#events';render()");await p.ready();
  assert.match(p.node('content').textContent,/是否确认/);assert.match(p.node('content').textContent,/已确认/);
  await p.find(p.node('content'),'删除已结束周期').events.click();
  assert.match(p.node('dialog-body').textContent,/预计删除 2 条/);
  assert.match(p.node('dialog-body').textContent,/2 条确认历史/);
  p.find(p.node('dialog-body'),'取消').events.click();assert.equal(p.writes.length,0);
  p.run('eventDetail(state.data.events[0])');
  await p.find(p.node('dialog-body'),'删除已结束周期').events.click();
  await p.find(p.node('dialog-body'),'确认删除周期及确认历史').events.click();await p.ready();
  assert.equal(p.writes.length,1);assert.equal(p.writes[0].value.scope,'ack_cycle');
  assert.equal(p.writes[0].value.revision,'c'.repeat(64));
  assert.match(p.node('refresh-status').textContent,/及 2 条确认历史/);
  const active=ackPage({cycleDelete:true});await active.open();
  assert.equal(active.find(active.node('dialog-body'),'删除已结束周期'),undefined);
  const conflict=ackPage({ended:true,cycleDelete:true,conflict:true});await conflict.open();
  await conflict.find(conflict.node('dialog-body'),'删除已结束周期').events.click();
  await conflict.find(conflict.node('dialog-body'),'确认删除周期及确认历史').events.click();await conflict.ready();
  assert.equal(conflict.writes.length,1);assert.match(conflict.node('dialog-title').textContent,/删除未完成/);
});

test('EVT wording is consistent in homepage, list, detail and family member rows',async()=>{
  const cases=[
    [{lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE',family_current_code:'OXYGEN_CRITICAL_LOW',family_level_change:'UPGRADED'},'已升级为严重低氧'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'OTHER_RISK_CONDITION_ACTIVE'},'同指标等级已变化'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'FRAME_COVERAGE_INSUFFICIENT'},'恢复状态待确认'],
    [{lifecycle_state:'INDETERMINATE',state_reason:'STALE_OR_OFFLINE',current_data_quality:{connectivity:'offline'}},'监测数据中断'],
    [{lifecycle_state:'ACTIVE',visual_recovery:{clear_count:2,required_clear_windows:3}},'恢复观察中 2/3'],
  ];
  const walk=node=>[node,...node.children.flatMap(walk)];
  for(const [fields,label] of cases){
    const d=fixture();const record={...d.events[0],device_id:'sim-pond-1',channel:'visual',...fields};
    d.events=[record];const p=page(d);await p.ready();
    let overview=walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
    assert.ok(overview.textContent.includes(label));assert.match(overview.textContent,/SIMULATOR/);
    walk(overview).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
    assert.ok(p.node('dialog-body').textContent.includes(label));
    p.run("location.hash='#events';render()");
    assert.ok(p.node('content').textContent.includes(label));
    p.run('eventDetail(state.data.events[0])');
    assert.ok(p.node('dialog-body').textContent.includes(label));
  }
  const d=fixture();const member={...d.events[0],channel:'water',lifecycle_state:'INDETERMINATE',
    state_reason:'OTHER_RISK_CONDITION_ACTIVE',family_current_code:'OXYGEN_CRITICAL_LOW',family_level_change:'UPGRADED'};
  d.events=[{...member,risk_family:{label:'溶解氧偏低风险',transitions:[]},family_members:[member]}];
  const p=page(d);await p.ready();p.run('eventDetail(state.data.events[0])');
  assert.equal(p.node('dialog-body').textContent.split('已升级为严重低氧').length-1,2);
  p.setData({...d,events:[{...member,channel:'visual',status:'closed',lifecycle_state:'RESOLVED'}]});
  await p.run('refresh()');p.run("location.hash='#events';render();eventDetail(state.data.events[0])");
  assert.match(p.node('dialog-body').textContent,/规则条件已消退/);
  assert.match(p.node('dialog-body').textContent,/连续可靠观测未再检出/);
  assert.match(p.node('dialog-body').textContent,/不代表疾病治愈/);
});

test('EVT-2 server queries all five intervals with combined filters and pagination',async()=>{
  const p=eventPage();await p.open();
  const range=p.walk(p.node('content')).find(n=>n.attributes['aria-label']==='事件时间范围');
  assert.deepEqual(range.children.map(n=>n.attributes.value),['5','10','30','60','all']);
  for(const value of ['5','10','30','60','all']){range.events.change({target:{value}});await p.ready();assert.equal(p.queries.at(-1).get('lookback_minutes'),value);}
  p.findButton(p.node('content'),'下一页').events.click();await p.ready();assert.equal(p.queries.at(-1).get('offset'),'50');
  const level=p.walk(p.node('content')).find(n=>n.attributes['aria-label']==='事件等级');
  level.events.change({target:{value:'warning'}});await p.ready();
  assert.equal(p.queries.at(-1).get('offset'),'0');assert.equal(p.queries.at(-1).get('severity'),'warning');
  assert.match(p.node('content').textContent,/共 51 条符合条件/);
  assert.equal(p.writes.length,0);
});

test('EVT-2 single deletion requires confirmation and cancel never sends commit',async()=>{
  const p=eventPage();await p.open();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/预计删除 1 条/);
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.length,1);
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  await p.findButton(p.node('dialog-body'),'确认删除此条事件').events.click();await p.ready();
  const commits=p.writes.filter(w=>w.url.endsWith('/delete'));
  assert.equal(commits.length,1);assert.equal(commits[0].value.event_id,'closed-record');
  assert.equal(commits[0].token,'fictional-event-capability');assert.equal(commits[0].value.revision,'f'.repeat(64));
  assert.match(p.node('content').textContent,/没有符合条件的记录/);
  assert.equal(p.run('state.data.events.length'),0);
});

test('EVT-2 bulk clear has two confirmations, global scope and cancellable final step',async()=>{
  const p=eventPage();await p.open();
  p.run("state.eventFilters.q='屏幕上的筛选';state.eventFilters.lookback_minutes='5'");
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/全部设备、全部时间/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认清理 1 条记录'),undefined);
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  assert.match(p.node('dialog-body').textContent,/不受当前筛选或分页影响/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  await p.findButton(p.node('dialog-body'),'确认清理 1 条记录').events.click();await p.ready();
  const commit=p.writes.find(w=>w.url.endsWith('/delete'));
  assert.deepEqual(Object.keys(commit.value).sort(),['revision','scope']);assert.equal(commit.value.scope,'all_resolved');
});

test('legacy ended history explains closure and cleanup without offering ACK or silently deleting',async()=>{
  const p=eventPage({legacy:true});await p.open();
  assert.match(p.node('content').textContent,/旧版已结束（未复核）/);
  assert.doesNotMatch(p.node('content').textContent,/恢复状态待确认/);
  p.run('eventDetail(state.data.events[0])');
  assert.match(p.node('dialog-body').textContent,/未经新版规则复核/);
  assert.match(p.node('dialog-body').textContent,/不支持人工知晓确认/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认已知晓'),undefined);
  p.node('details-dialog').close();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/其中 1 条为旧版已结束记录/);
  assert.match(p.node('dialog-body').textContent,/清理不表示已验证恢复/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
  p.findButton(p.node('content'),'清理全部已结束事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/其中 1 条为旧版已结束记录/);
  assert.equal(p.findButton(p.node('dialog-body'),'确认清理 1 条记录'),undefined);
  p.findButton(p.node('dialog-body'),'继续核对').events.click();
  assert.match(p.node('dialog-body').textContent,/包含符合条件的旧版已结束记录/);
  p.findButton(p.node('dialog-body'),'取消').events.click();
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,0);
});

test('EVT-2 conflicting deletion stays explicit, never retries or clears local data',async()=>{
  const p=eventPage({conflict:true});await p.open();
  p.findButton(p.node('content'),'删除记录').events.click();await p.ready();
  await p.findButton(p.node('dialog-body'),'确认删除此条事件').events.click();await p.ready();
  assert.match(p.node('dialog-body').textContent,/未自动重试/);
  assert.equal(p.writes.filter(w=>w.url.endsWith('/delete')).length,1);
  assert.equal(p.run('state.data.events.length'),1);
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
  p.run("location.hash='#settings';render();settingsWorkspace.show('tools')");await p.ready();
  assert.match(p.node('content').textContent,/未启用该试用时，历史不会进入原两工具范围/);
  assert.match(p.node('content').textContent,/授权配置读取失败/);
});

test('event lifecycle and critical severity are distinct from data quality and human handling',async()=>{
  const d=fixture();d.events=[
    {...d.events[0],id:'active',title:'低氧实验规则',severity:'critical',lifecycle_state:'ACTIVE',publication_status:'PROTOTYPE'},
    {...d.events[0],id:'unknown',title:'证据不足',lifecycle_state:'INDETERMINATE'},
    {...d.events[0],id:'resolved',title:'有效新观测',status:'closed',lifecycle_state:'RESOLVED'}];
  const p=page(d);await p.ready();p.run("location.hash='#events';render()");
  assert.match(p.node('content').textContent,/严重/);assert.match(p.node('content').textContent,/异常持续/);
  assert.match(p.node('content').textContent,/恢复状态待确认/);assert.match(p.node('content').textContent,/规则条件已消退/);
  assert.match(p.node('content').textContent,/PROTOTYPE/);
  p.run("state.eventFilters.status='INDETERMINATE';render()");
  assert.match(p.node('content').textContent,/证据不足/);assert.doesNotMatch(p.node('content').textContent,/低氧实验规则/);
  p.run("location.hash='#monitoring';render()");assert.match(p.node('content').textContent,/PROTOTYPE/);
  d.cameras[0].signal_status='indeterminate';p.setData(d);p.run("location.hash='#video'");await p.run('refresh()');
  assert.match(p.node('content').textContent,/当前状态待确认/);
});

test('dashboard shows ongoing old events before recent resolved records and opens original details',async()=>{
  const d=fixture();d.events=[...Array.from({length:6},(_,i)=>({...d.events[0],id:'resolved-'+i,status:'closed',lifecycle_state:'RESOLVED'})),
    {...d.events[0],id:'old-active',device_id:'sim-pond-1',channel:'visual',code:'SUSPECTED_LESION',
      title:'疑似病灶检测信号（模拟，非诊断）',lifecycle_state:'ACTIVE',last_observed_at:d.monitoring.observed_at,
      visual_recovery:{clear_count:1,required_clear_windows:3,last_valid_observed_at:d.monitoring.observed_at,continuity:'continuous'}}];
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const overview=()=>walk(p.node('content')).find(n=>n.attributes['data-current-anomalies']==='true');
  assert.ok(overview());assert.match(overview().textContent,/恢复观察中 1\/3/);
  assert.match(overview().textContent,/SIMULATOR/);assert.match(overview().textContent,/最近有效观测/);
  assert.match(overview().textContent,/首次发生/);assert.match(overview().textContent,/sim-pond-1/);
  assert.doesNotMatch(overview().textContent,/resolved-/);
  walk(overview()).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
  assert.match(p.node('dialog-title').textContent,/疑似病灶/);
  assert.match(p.node('dialog-body').textContent,/未再检出/);
  assert.doesNotMatch(p.node('dialog-body').textContent,/已确认消退|疾病已经治愈|人工已经确认/);
  await p.run('refresh()');assert.ok(overview());
});

test('dashboard empty current anomalies requires fresh complete evidence from both channels',async()=>{
  const d=fixture();d.events=[];
  d.monitoring.device_id='sim-pond-1';d.monitoring.findings=[];
  d.cameras[0].signal_status='no_obvious_anomaly';
  d.cameras[0].analysis={data_quality:{quality:'valid',freshness:'fresh',connectivity:'online'}};
  const p=page(d);await p.ready();
  assert.match(p.node('content').textContent,/当前未见异常信号/);
  for(const key of ['stale','missing','invalid','offline']){
    const next=structuredClone(d);
    if(key==='stale')next.monitoring.freshness='stale';
    if(key==='missing')next.cameras[0].summary=null;
    if(key==='invalid')next.cameras[0].analysis.data_quality.quality='invalid';
    if(key==='offline')next.cameras[0].analysis.data_quality.connectivity='offline';
    p.setData(next);await p.run('refresh()');
    assert.match(p.node('content').textContent,/状态未知/);
    assert.doesNotMatch(p.node('content').textContent,/当前未见异常信号/);
  }
});

test('unknown active observation is distinct from recovery and resolved signal wording',async()=>{
  const d=fixture();d.events=[{...d.events[0],device_id:'sim-pond-1',channel:'visual',code:'SUSPECTED_LESION',
    lifecycle_state:'INDETERMINATE',visual_recovery:{clear_count:0,required_clear_windows:3,continuity:'interrupted'}}];
  const p=page(d);await p.ready();
  assert.match(p.node('content').textContent,/恢复状态待确认/);
  assert.doesNotMatch(p.node('content').textContent,/恢复观察中/);
  d.events[0].lifecycle_state='RESOLVED';d.events[0].status='closed';p.setData(d);
  p.run("location.hash='#events'");await p.run('refresh()');
  assert.match(p.node('content').textContent,/规则条件已消退/);
  assert.doesNotMatch(p.node('content').textContent,/已确认消退/);
});


test('chart range controls render real page: default recent, all history, polling preserves selection',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  let nodes=walk(p.node('content'));
  const singleMarkers=()=>walk(walk(p.node('content')).find(n=>n.attributes['data-chart']==='single')).filter(n=>n.attributes.class==='trend-marker');
  assert.equal(singleMarkers().length,85);
  const range=nodes.find(n=>n.tagName==='select'&&n.attributes['aria-label']==='历史范围');
  assert.ok(range);range.events.change({target:{value:'all'}});
  assert.equal(p.run('state.trendRange'),'all');
  nodes=walk(p.node('content'));assert.equal(singleMarkers().length,214);
  await p.run('refresh()');assert.equal(p.run('state.trendRange'),'all');
  assert.equal(singleMarkers().length,214);
  p.run("location.hash='#monitoring';render()");
  assert.equal(singleMarkers().length,214);
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

test('5/10 minute selectors drive both charts, keep default 30 minutes and survive polling and navigation',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory().map((row,i)=>({...row,temperature_c:25+i/100,ph:7+i/1000}));
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const nodes=()=>walk(p.node('content'));
  const range=()=>nodes().find(n=>n.tagName==='select'&&n.attributes['aria-label']==='历史范围');
  assert.equal(p.run('state.trendRange'),'1800');
  assert.deepEqual(range().children.map(n=>n.attributes.value),['300','600','1800','3600','all']);
  for(const [value,count,radius] of [['300',31,2.5],['600',61,2],['1800',85,1.35],['3600',85,1.35],['all',214,.65]]){
    range().events.change({target:{value}});
    const charts=nodes().filter(n=>n.attributes['data-chart']);
    assert.equal(charts.length,2);
    assert.equal(walk(charts[0]).filter(n=>n.attributes.class==='trend-marker').length,count);
    assert.ok(walk(charts[0]).filter(n=>n.attributes.class==='trend-marker').every(n=>n.attributes.r===radius));
    assert.equal(walk(charts[1]).filter(n=>n.attributes.class==='trend-marker').length,count*3);
    assert.ok(walk(charts[1]).filter(n=>n.attributes.class==='trend-marker').every(n=>n.attributes.r<=1.35));
  }
  range().events.change({target:{value:'600'}});
  await p.run('refresh()');p.run("location.hash='#monitoring';render()");
  assert.equal(p.run('state.trendRange'),'600');
  assert.ok(nodes().some(n=>n.textContent==='三指标综合趋势（归一化）'));
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});

test('dashboard moves existing side cards beside trends and keeps one full-row event table with working details',async()=>{
  const d=fixture();d.monitoring.trend=restartHistory();
  const p=page(d);await p.ready();
  const walk=node=>[node,...node.children.flatMap(walk)];
  const hasClass=(node,name)=>(node.className||'').split(/\s+/).includes(name);
  const titles=node=>walk(node).filter(n=>n.tagName==='h2').map(n=>n.textContent);
  const check=()=>{
    const nodes=walk(p.node('content')),grid=nodes.find(n=>hasClass(n,'dashboard-overview'));
    assert.ok(grid);assert.equal(grid.children.length,3);
    assert.deepEqual(titles(grid.children[0]),['历史趋势','三指标综合趋势（归一化）']);
    assert.ok(hasClass(grid.children[1],'dashboard-sidebar'));
    assert.deepEqual(titles(grid.children[1]),['视觉监测概况','AI 智能助手','连接状态']);
    assert.ok(hasClass(grid.children[2],'dashboard-events'));
    assert.deepEqual(titles(grid.children[2]),['最近事件']);
    for(const title of ['视觉监测概况','AI 智能助手','连接状态','最近事件']){
      assert.equal(nodes.filter(n=>n.tagName==='h2'&&n.textContent===title).length,1);
    }
    const eventCard=grid.children[2];
    assert.ok(walk(eventCard).some(n=>n.attributes.href==='#events'&&n.textContent==='全部记录'));
    assert.ok(walk(grid.children[1]).some(n=>n.attributes.href==='#assistant'&&n.textContent.includes('打开助手工作区')));
    walk(eventCard).find(n=>n.tagName==='button'&&n.textContent==='查看详情').events.click();
    assert.equal(p.node('dialog-title').textContent,d.events[0].title);
    assert.ok(p.node('dialog-body').textContent.includes(d.events[0].batch_id));
  };
  check();await p.run('refresh()');check();
  assert.ok(p.requests.every(url=>url.startsWith('/api/bootstrap')));
});
