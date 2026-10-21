import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {chartGeometry,normalizedChartGeometry,trendRanges} from '../static/view-model.js';
import {point,time,restartHistory} from './chart-fixture.mjs';
const key='dissolved_oxygen_mg_l';

function render(trend,options={},normalized=false){
  const context=vm.createContext({Node:Element,Intl,Date,console,
    document:{createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
      createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}}});
  for(const file of ['view-model.js','components.js']){
    const source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  context.input={trend,source_kind:'simulator'};context.options=options;
  return vm.runInContext(normalized?'normalizedTrendChart(input,options)':"trendChart(input,'dissolved_oxygen_mg_l',options)",context);
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
    const markers=nodes.filter(n=>n.attributes.class==='trend-marker');
    assert.equal(markers.length,options.rangeSeconds===null?214:85);
    assert.ok(markers.every(n=>n.attributes.r<=1.35));
    if(options.rangeSeconds===null)assert.ok(markers.every(n=>n.attributes.r<1&&n.attributes.opacity<.5));
    assert.match(root.textContent,/北京时间 UTC\+8/);assert.match(root.textContent,/最后观测/);
    assert.ok(nodes.some(n=>n.className==='chart-viewport'));
  }
  const css=fs.readFileSync(new URL('../static/styles.css',import.meta.url),'utf8');
  assert.match(css,/\.chart-viewport\{overflow-x:auto/);assert.match(css,/min-width:520px/);
});

test('five ranges share the latest stored timestamp and preserve the default short-window markers',()=>{
  assert.deepEqual(trendRanges.map(([id])=>id),['300','600','1800','3600','all']);
  const data=restartHistory();
  for(const [seconds,count] of [[300,31],[600,61],[1800,85],[3600,85]]){
    const g=chartGeometry(data,key,{rangeSeconds:seconds});
    assert.equal(g.displayedCount,count);assert.equal(g.end,Date.parse(data.at(-1).observed_at));
    assert.ok(g.rows.every(row=>Date.parse(row.observed_at)>=g.end-seconds*1000));
  }
  const markers=walk(render([point(10),point(20,6.8)])).filter(n=>n.attributes.class==='trend-marker');
  assert.ok(markers.every(n=>n.attributes.r>1&&n.attributes.r<2));
});

test('single markers follow all five ranges, dense data stay small without dropping observations',()=>{
  const data=Array.from({length:360},(_,i)=>point(i*10,6+(i%7)*.01));
  for(const [rangeSeconds,count,radius] of [[300,31,2.5],[600,61,2],[1800,181,1.35],[3600,360,.65],[null,360,.65]]){
    const nodes=walk(render(data,{rangeSeconds})),markers=nodes.filter(n=>n.attributes.class==='trend-marker');
    assert.equal(markers.length,count);assert.ok(markers.every(n=>n.attributes.r===radius));
    const plot=nodes.find(n=>n.tagName==='svg'),tip=nodes.find(n=>n.className==='chart-tooltip');
    plot.events.keydown({key:'End',preventDefault(){}});
    assert.ok(tip.textContent.includes('溶解氧：'+String(data.at(-1)[key])+' mg/L'));
    assert.equal(nodes.find(n=>n.attributes.class==='chart-highlight').attributes.r,4);
  }
  // One-second windows need a density fallback even in a five-minute selection.
  const dense=Array.from({length:301},(_,i)=>point(i,6.4,{window_start:time(i-1),window_duration_s:1}));
  const markers=walk(render(dense,{rangeSeconds:300})).filter(n=>n.attributes.class==='trend-marker');
  assert.equal(markers.length,301);assert.ok(markers.every(n=>n.attributes.r===.65));
  for(const rangeSeconds of [3600,null]){
    assert.ok(walk(render([point(10),point(20)],{rangeSeconds})).filter(n=>n.attributes.class==='trend-marker').every(n=>n.attributes.r===1.35));
  }
});

const threeMetrics=()=>[
  point(10,4,{temperature_c:20,ph:7}),point(20,6,{temperature_c:25,ph:7.5}),point(30,8,{temperature_c:30,ph:8}),
];
test('combined view keeps small markers even when the short-view single chart is enlarged',()=>{
  for(const rangeSeconds of [300,600,1800,3600,null]){
    const root=render(threeMetrics(),{rangeSeconds},true);
    const markers=walk(root).filter(n=>n.attributes.class==='trend-marker');
    assert.equal(markers.length,9);assert.ok(markers.every(n=>n.attributes.r===1.35));
    assert.equal(new Set(walk(root).filter(n=>n.attributes.class==='trend-line').map(n=>n.attributes.stroke)).size,3);
  }
});
test('per-metric min-max is dimensionless, keeps original values and puts constants at 50',()=>{
  const rows=threeMetrics(),before=JSON.stringify(rows),g=normalizedChartGeometry(rows);
  assert.equal(g.series.length,3);
  for(const item of g.series)assert.deepEqual(item.data.normalized,[0,50,100]);
  assert.equal(JSON.stringify(rows),before);
  assert.deepEqual(g.yTicks.map(t=>t.label),['0','25','50','75','100']);
  const constant=normalizedChartGeometry(rows.map(row=>({...row,ph:7.5})));
  assert.deepEqual(constant.series[1].data.normalized,[50,50,50]);
  assert.ok(constant.series[1].data.points.every(p=>Number.isFinite(p[1])));
  const recent=normalizedChartGeometry(rows,{rangeSeconds:10});
  assert.deepEqual(recent.series[0].data.normalized,[0,100]);
  assert.equal(recent.series[0].min,25);
});

test('normalized series preserve sessions, holes, last-received duplicates and missing metrics without interpolation',()=>{
  const rows=[...threeMetrics(),point(40,9,{temperature_c:29,ph:7.4,session_id:'b'})];
  rows[1].metric_quality={ph:'invalid'};
  const g=normalizedChartGeometry(rows);
  assert.equal(g.series[1].data.points.length,3);assert.equal(g.series[1].data.segments.length,3);
  assert.equal(g.series[0].data.segments.length,2);
  rows.push({...rows[1],ph:null,received_at:time(23)});
  assert.equal(normalizedChartGeometry(rows).series[1].data.points.length,3);
  const partial=normalizedChartGeometry([point(10),point(20)]);
  assert.equal(partial.series[0].data,null);assert.equal(partial.series[1].data,null);
  assert.equal(partial.displayedCount,2);
  assert.equal(normalizedChartGeometry([point(10),point(20,null)]),null);
});

test('combined chart has three distinct styles; pointer, touch and keyboard inspect exact raw values and units',()=>{
  const root=render(threeMetrics(),{},true),nodes=walk(root);
  const lines=nodes.filter(n=>n.attributes.class==='trend-line');
  assert.equal(lines.length,3);assert.equal(new Set(lines.map(n=>n.attributes.stroke)).size,3);
  assert.equal(new Set(lines.map(n=>n.attributes['stroke-dasharray'])).size,3);
  assert.match(root.textContent,/仅比较趋势/);assert.match(root.textContent,/非适宜度/);
  const svg=nodes.find(n=>n.tagName==='svg'),tip=nodes.find(n=>n.className==='chart-tooltip');
  svg.getBoundingClientRect=()=>({left:100,top:50,width:780,height:276});
  svg.events.pointermove({clientX:497,clientY:180});
  assert.equal(tip.getAttribute('hidden'),null);
  for(const expected of ['水温：25 °C','pH：7.5（无单位）','溶解氧：6 mg/L'])assert.ok(tip.textContent.includes(expected));
  assert.match(tip.textContent,/08:00:20/);
  const key=key=>svg.events.keydown({key,preventDefault(){}});
  key('End');assert.match(tip.textContent,/水温：30 °C/);
  key('ArrowLeft');assert.match(tip.textContent,/水温：25 °C/);
  key('Home');assert.match(tip.textContent,/溶解氧：4 mg\/L/);
  key('Escape');assert.equal(tip.getAttribute('hidden'),'');
  svg.events.pointerdown({clientX:842,clientY:180});assert.match(tip.textContent,/08:00:30/);
  svg.events.pointerdown({clientX:843,clientY:259});assert.match(tip.textContent,/08:00:30/);
  svg.events.pointerleave();assert.equal(tip.getAttribute('hidden'),'');
});

test('single tooltip stays usable on tiny markers and combined tooltip marks invalid values unavailable',()=>{
  const root=render(threeMetrics()),nodes=walk(root),svg=nodes.find(n=>n.tagName==='svg');
  const tip=nodes.find(n=>n.className==='chart-tooltip');
  svg.getBoundingClientRect=()=>({left:0,top:0,width:780,height:276});
  svg.events.pointermove({clientX:397,clientY:130});
  assert.match(tip.textContent,/溶解氧：6 mg\/L/);
  assert.equal(nodes.find(n=>n.attributes.class==='chart-highlight').attributes.r,4);
  const rows=threeMetrics();rows[1].metric_quality={ph:'invalid'};
  const combined=walk(render(rows,{},true)),plot=combined.find(n=>n.tagName==='svg');
  plot.events.keydown({key:'Home',preventDefault(){}});plot.events.keydown({key:'ArrowRight',preventDefault(){}});
  assert.match(combined.find(n=>n.className==='chart-tooltip').textContent,/pH：不可用/);
});
