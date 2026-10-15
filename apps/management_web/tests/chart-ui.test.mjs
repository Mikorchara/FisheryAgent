import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {chartGeometry} from '../static/view-model.js';
import {point,time,restartHistory} from './chart-fixture.mjs';
const key='dissolved_oxygen_mg_l';

function render(trend,options={}){
  const context=vm.createContext({Node:Element,Intl,Date,console,
    document:{createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
      createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}}});
  for(const file of ['view-model.js','components.js']){
    const source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  context.input={trend,source_kind:'simulator'};context.options=options;
  return vm.runInContext("trendChart(input,'dissolved_oxygen_mg_l',options)",context);
}
const walk=node=>[node,...node.children.flatMap(walk)];

test('real time spacing survives unordered data; no row index fallback or input mutation',()=>{
  const input=[point(40,7),point(10,6),point(20,6.5),point(30,null),point(50,8,{observed_at:'bad-time'})];
  const before=JSON.stringify(input),g=chartGeometry(input,key);
  assert.equal(JSON.stringify(input),before);assert.deepEqual(g.rows.map(r=>r.observed_at),[time(10),time(20),time(40)]);
  assert.equal(g.points[0][0],52);assert.equal(g.points[1][0],282);assert.equal(g.points[2][0],742);
  assert.equal(g.segments.length,2);assert.equal(g.invalidTimeCount,1);
  assert.equal(chartGeometry([{[key]:6},{[key]:7}],key),null);
});

test('214 windows across three restarts: recent view spreads 85 points, all preserves actual gaps',()=>{
  const data=restartHistory(),all=chartGeometry(data,key),recent=chartGeometry(data,key,{rangeSeconds:1800});
  assert.equal(all.points.length,214);assert.equal(all.segments.length,3);
  assert.equal(recent.points.length,85);assert.equal(recent.segments.length,1);
  assert.equal(recent.points[0][0],52);assert.equal(recent.points.at(-1)[0],742);
  assert.ok(Math.abs(recent.points[1][0]-52-690/84)<1e-8);
  assert.ok(all.points[63][0]-all.points[0][0]<7); // Real 20h scale still has truthful clusters.
  assert.equal(new Set(all.xTicks.map(t=>t.x)).size,all.xTicks.length);
  for(let i=1;i<all.xTicks.length;i++)assert.ok(all.xTicks[i].x-all.xTicks[i-1].x>=170);
});

test('duplicate instants choose last received, never average/backfill; no vertical polyline',()=>{
  const data=[point(10,2.2),point(20,6),point(10,8,{observed_at:'2026-10-14T08:00:10+08:00',received_at:time(12)}),point(30,7)];
  const g=chartGeometry(data,key);assert.equal(g.duplicateCount,1);
  assert.equal(g.rows[0][key],8);assert.equal(new Set(g.points.map(p=>p[0])).size,3);
  data.push(point(20,null,{received_at:time(25)}));
  const missing=chartGeometry(data,key);assert.equal(missing.points.length,2);assert.equal(missing.segments.length,2);
  assert.equal(chartGeometry([point(10),point(10,7)],key),null);
});

test('sessions, explicit gaps and quality holes break lines; legacy without session remains readable',()=>{
  assert.equal(chartGeometry([point(10),point(20,6,{session_id:'b'})],key).segments.length,2);
  assert.equal(chartGeometry([point(10),point(40)],key).segments.length,2);
  assert.equal(chartGeometry([point(10),point(20,6,{metric_quality:{[key]:'invalid'}}),point(30)],key).segments.length,2);
  const legacy=[point(10),point(20)].map(p=>{delete p.session_id;delete p.window_start;return p;});
  assert.equal(chartGeometry(legacy,key).segments.length,1);
  // Missing latest values anchor the selected time range; stale old values cannot slide forward.
  assert.equal(chartGeometry([point(10),point(20),point(8000,null)],key,{rangeSeconds:1800}),null);
});

test('subsecond and tiny value ranges have unique legible Beijing ticks and finite coordinates',()=>{
  for(const span of [1,.05,.001,20,90000]){
    const g=chartGeometry([point(10,6.401),point(10+span,6.402)],key);
    assert.equal(new Set(g.xTicks.map(t=>t.label+' '+t.date)).size,g.xTicks.length);
    assert.equal(new Set(g.yTicks.map(t=>t.label)).size,g.yTicks.length);
    assert.ok(g.points.every(p=>p.every(Number.isFinite)));
    if(span<4)assert.match(g.xTicks[0].label,/08:00:10\.000/);
    if(span>86400)assert.ok(g.xTicks.every(t=>t.date));
  }
});

test('actual SVG has spaced time ticks, distinct y labels, recent/all controls and bounded narrow viewport',()=>{
  for(const options of [{},{rangeSeconds:null}]){
    const root=render(restartHistory(),options),nodes=walk(root),svg=nodes.find(n=>n.tagName==='svg');
    const x=svg.children.filter(n=>n.tagName==='text'&&n.attributes.y===241);
    assert.equal(x.length,5);assert.equal(new Set(x.map(n=>n.textContent)).size,5);
    for(let i=1;i<x.length;i++)assert.ok(x[i].attributes.x-x[i-1].attributes.x>=170);
    assert.equal(x[0].attributes['text-anchor'],'start');assert.equal(x.at(-1).attributes['text-anchor'],'end');
    assert.equal(nodes.filter(n=>n.tagName==='circle').length,options.rangeSeconds===null?214:85);
    assert.match(root.textContent,/北京时间 UTC\+8/);assert.match(root.textContent,/最后观测/);
    assert.ok(nodes.some(n=>n.className==='chart-viewport'));
  }
  const css=fs.readFileSync(new URL('../static/styles.css',import.meta.url),'utf8');
  assert.match(css,/\.chart-viewport\{overflow-x:auto/);assert.match(css,/min-width:520px/);
});
