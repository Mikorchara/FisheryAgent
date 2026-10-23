import test from 'node:test';
import assert from 'node:assert/strict';
import {routes,routeFor,metricText,filterItems,chartGeometry,timeText,validateBootstrap,eventStateName,eventStateReasonName} from '../static/view-model.js';
import fs from 'node:fs';
import {execFileSync} from 'node:child_process';

test('event wording distinguishes structured grade changes, uncertainty and interruption',()=>{
  const unknown={lifecycle_state:'INDETERMINATE'};
  const grade={...unknown,state_reason:'OTHER_RISK_CONDITION_ACTIVE',family_current_code:'OXYGEN_CRITICAL_LOW',family_level_change:'UPGRADED'};
  assert.equal(eventStateName(grade),'已升级为严重低氧');
  assert.equal(eventStateName({...grade,family_current_code:'OXYGEN_CRITICAL_EXTREME'}),'已升级为极低氧');
  assert.equal(eventStateName({...grade,family_level_change:'CHANGED'}),'同指标等级已变化');
  assert.equal(eventStateName({...grade,family_current_code:'PH_CRITICAL_LOW'}),'同指标等级已变化');
  for(const state_reason of [undefined,'LEGACY_UNREVIEWED','RULE_CHANGED','METRIC_NOT_RELIABLE','FRAME_COVERAGE_INSUFFICIENT','CURRENT_EVIDENCE_UNAVAILABLE','STALE_OR_OFFLINE']){
    assert.equal(eventStateName({...unknown,state_reason}),'恢复状态待确认');
  }
  const stale={...unknown,state_reason:'STALE_OR_OFFLINE',current_data_quality:{freshness:'stale',connectivity:'online'}};
  assert.equal(eventStateName(stale),'恢复状态待确认');
  assert.match(eventStateReasonName(stale),/已过期/);
  const offline={...stale,current_data_quality:{freshness:'stale',connectivity:'offline'}};
  assert.equal(eventStateName(offline),'监测数据中断');
  assert.match(eventStateReasonName(offline),/上报中断/);
  assert.equal(eventStateName({...unknown,state_reason:'VISUAL_OBSERVATION_MISSING'}),'监测数据中断');
  // Old continuity metadata can describe a past gap; it cannot prove a current outage.
  assert.equal(eventStateName({...unknown,visual_recovery:{continuity:'interrupted'}}),'恢复状态待确认');
  assert.equal(eventStateName({lifecycle_state:'ACTIVE',visual_recovery:{clear_count:2,required_clear_windows:3}}),'恢复观察中 2/3');
  for(const channel of ['water','visual'])assert.equal(eventStateName({channel,lifecycle_state:'RESOLVED'}),'规则条件已消退');
  assert.match(eventStateReasonName({channel:'visual',lifecycle_state:'RESOLVED'}),/连续可靠观测未再检出/);
  assert.match(eventStateReasonName({channel:'visual',lifecycle_state:'RESOLVED'}),/不代表疾病治愈/);
});

test('seven distinct modules navigate safely including unknown hash',()=>{
  assert.equal(routes.length,7);assert.equal(new Set(routes.map(r=>r.id)).size,7);
  for(const r of routes)assert.equal(routeFor('#'+r.id).id,r.id);
  assert.equal(routeFor('#<script>unknown</script>').id,'dashboard');
});
test('missing invalid and nonfinite measurements never appear as normal values',()=>{
  for(const metric of [{value:null,quality:'missing'},{value:7,quality:'invalid'},{value:NaN,quality:'valid'},{value:Infinity,quality:'valid'}])assert.equal(metricText(metric),'—');
  assert.equal(metricText({value:6.4,quality:'valid'}),'6.4');
});
test('event filtering combines search level and processing state',()=>{
  const items=[{title:'低氧演示',device:'A',severity:'warning',status:'pending'},{title:'设备演示',device:'B',severity:'info',status:'closed'}];
  assert.equal(filterItems(items,{q:'低氧',severity:'warning',status:'pending'}).length,1);
  assert.equal(filterItems(items,{q:'不存在'}).length,0);
});
test('file search and category do not imply indexing or retrieval',()=>{
  const items=[{name:'设备说明',category:'设备',index_status:'not_indexed'}];
  assert.equal(filterItems(items,{category:'设备',q:'说明'}).length,1);
  assert.equal(items[0].index_status,'not_indexed');
});
test('chart geometry bounded flat and varied values; unavailable series empty',()=>{
  for(const values of [[6,6,6],[2.2,6.4,5.8]]){
    const g=chartGeometry(values.map((value,i)=>({oxygen:value,observed_at:new Date(i*10000).toISOString()})),'oxygen');
    for(const[x,y]of g.points){assert.ok(x>=52&&x<=742);assert.ok(y>=53&&y<=208);}
  }
  assert.equal(chartGeometry([{oxygen:null},{oxygen:NaN}],'oxygen'),null);
});
test('bad timestamps display unavailable instead of fabricated time',()=>{
  assert.equal(timeText(null),'暂无时间');assert.equal(timeText('wrong'),'暂无时间');
});
test('timestamps use Beijing time to seconds, across midnight and independent of host zone',()=>{
  const utc='2026-10-14T16:00:05Z';
  assert.match(timeText(utc),/2026\/10\/15 00:00:05 北京时间/);
  assert.equal(timeText(utc),timeText('2026-10-15T00:00:05+08:00'));
  assert.equal(timeText(utc,true),'00:00:05');
  const source=`import {timeText} from ${JSON.stringify(new URL('../static/view-model.js',import.meta.url).href)};process.stdout.write(timeText(${JSON.stringify(utc)}));`;
  for(const TZ of ['UTC','America/New_York','Asia/Shanghai']) {
    assert.equal(execFileSync(process.execPath,['--input-type=module','-e',source],{env:{...process.env,TZ},encoding:'utf8'}),timeText(utc));
  }
});

test('missing metrics and interrupted windows never become fabricated connecting trends',()=>{
  const time=seconds=>new Date(Date.UTC(2026,9,14,0,0,seconds)).toISOString();
  const series=[{oxygen:6,observed_at:time(10),window_duration_s:10},{oxygen:null,observed_at:time(20),window_duration_s:10},{oxygen:2,observed_at:time(30),window_duration_s:10}];
  assert.equal(chartGeometry(series,'oxygen').segments.length,2);
  assert.equal(chartGeometry([series[0],{oxygen:2,observed_at:time(60),window_duration_s:10}],'oxygen').segments.length,2);
});
test('bootstrap schema rejects absent services and undeclared source mode',()=>{
  assert.throws(()=>validateBootstrap({schema_version:1}));
  assert.throws(()=>validateBootstrap({schema_version:1,application:'management-web-r1',data_mode:'fake-live'}));
});
test('UI uses safe DOM text and only local application services; AI sending remains disabled',()=>{
  const ui=fs.readFileSync(new URL('../static/app.js',import.meta.url),'utf8');
  const components=fs.readFileSync(new URL('../static/components.js',import.meta.url),'utf8');
  assert.doesNotMatch(ui+components,/innerHTML|localStorage|eval\(/);
  assert.match(components,/textContent=value/);
  assert.match(ui,/disabled:'disabled',text:'发送 · 尚未接入'/);
  assert.doesNotMatch(ui,/Authorization|api_key|SYSTEM_INSTRUCTION|tool_calls/);
});
