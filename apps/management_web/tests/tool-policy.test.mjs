import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import {Element} from './dom-fixture.mjs';
import {fixture,tick} from './assistant-fixture.mjs';

const WATER='get_current_water_quality',KNOWLEDGE='search_fishery_knowledge',HISTORY='get_water_quality_history';
const walk=node=>[node,...node.children.flatMap(walk)];
function settingsFixture(){
  let config={epoch:'epoch',browser_token:'fictional',revision:'r1',source:'INHERITED_SHARED_POLICY',
    selected_tools:[WATER,KNOWLEDGE],tools:[{name:WATER},{name:KNOWLEDGE},{name:HISTORY,candidate_only:true},
      {name:'score_current_water_quality',compatibility_only:true}]};
  const writes=[];let saved=0;
  const api={toolPolicy:async()=>structuredClone(config),saveToolPolicy:async value=>{
    writes.push(structuredClone(value));config={...config,selected_tools:value.selected_tools,revision:'r2',source:'MANAGEMENT_OVERRIDE'};return config;}};
  const context=vm.createContext({Node:Element,Set,document:{createElement:tag=>new Element(tag),
    createTextNode:text=>{const node=new Element('text');node.textContent=text;return node;}}});
  for(const file of ['components.js','tool-policy.js']){
    vm.runInContext(fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8')
      .replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context,{filename:file});
  }
  context.api=api;context.saved=()=>saved++;
  const panel=vm.runInContext('createToolPolicySettings(api,{onSaved:saved})',context);
  return {root:panel.mount(),writes,api,panel,get saved(){return saved;}};
}

test('settings load never saves; history opt-in preserves choices and publication is separate',async()=>{
  const p=settingsFixture();await tick();
  assert.equal(p.writes.length,0);assert.match(p.root.textContent,/Normal：未启用 · Streaming：未启用/);
  let inputs=walk(p.root).filter(n=>n.tagName==='input');
  assert.equal(inputs[2].getAttribute('checked'),null);
  assert.equal(inputs[3].getAttribute('disabled'),'disabled');
  inputs[2].events.change({target:{checked:true}});
  walk(p.root).find(n=>n.textContent==='保存 Tool 授权').events.click();await tick();
  assert.deepEqual(p.writes[0].selected_tools,[WATER,KNOWLEDGE,HISTORY]);
  assert.equal(p.saved,1);assert.match(p.root.textContent,/下一条请求/);
  // Re-mount during page refresh retains the selection and does not submit again.
  p.panel.mount();await tick();assert.equal(p.writes.length,1);
});

test('stale concurrent settings require reload; safe errors never render private text',async()=>{
  const p=settingsFixture();await tick();
  p.api.saveToolPolicy=async()=>{throw new Error('TOOL_POLICY_REVISION_MISMATCH');};
  walk(p.root).find(n=>n.textContent==='保存 Tool 授权').events.click();await tick();
  assert.match(p.root.textContent,/其他窗口修改/);assert.equal(p.saved,0);
  p.api.toolPolicy=async()=>{throw new Error('private payload');};
  await p.panel.load();assert.doesNotMatch(p.root.textContent,/private payload/);
  assert.equal(walk(p.root).find(n=>n.textContent==='保存 Tool 授权').getAttribute('disabled'),'disabled');
});

test('policy save invalidates confirmation, preserves history and draft, defers refresh in flight',async()=>{
  const p=fixture();await p.ready();
  p.workspace.state.turns=[{user:'old',assistant:'answer',completed_at:'2026-10-17T00:00:00Z'}];
  p.workspace.state.draft='draft';p.workspace.state.confirmed=true;
  p.workspace.policyChanged();await tick();
  assert.equal(p.workspace.state.confirmed,false);assert.equal(p.workspace.state.turns.length,1);
  assert.equal(p.workspace.state.draft,'draft');
  const previous=p.workspace.state.config;
  p.workspace.state.pending=true;p.workspace.state.confirmed=true;p.workspace.policyChanged();
  assert.equal(p.workspace.state.confirmed,false);assert.equal(p.workspace.state.config,previous);
  assert.equal(p.workspace.state.reloadPolicy,true);
});
