import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';

const tick=()=>new Promise(resolve=>setImmediate(resolve));
const activity=(status='OK',quality='valid',freshness='fresh')=>({counts:{tools_executed:1,model_requests_started:2},steps:[
  {kind:'model',request_index:1,state:'COMPLETED',outcome:'tool_calls'},
  {kind:'tool',tool_name:'get_current_water_quality',state:'COMPLETED',result_status:status,handler_started:true,
    quality,freshness,duration_ms:2,observed_at:'2026-10-15T00:00:00Z',evaluated_at:'2026-10-15T00:00:35Z'},
  {kind:'model',request_index:2,state:'COMPLETED',outcome:'final_answer'}],aggregate_usage:{total_tokens:42}});
const success=(text='离线回答',details=activity())=>({result:{successful_turn:true,final_text:text,
  completed_at:'2026-10-15T00:01:00Z',activity:details,history_trimmed:false}});
function fixture(){
  const config={epoch:'epoch',browser_token:'fictional-control-token',tools:['get_current_water_quality'],
    default_preset_id:'qwen',presets:[{preset_id:'qwen',display_name:'Qwen 3.8 Flash',runtime_type:'cloud',revision:'q'},
      {preset_id:'ollama',display_name:'Ollama Qwen3.5 4B',runtime_type:'local',revision:'o'}]};
  const sent=[],cancelled=[],timers=[];
  const api={bootstrap:async()=>structuredClone(config),prepare:async()=>({request_id:'request',control_token:'control'}),
    send:async value=>{sent.push(structuredClone(value));return success();},state:async()=>({state:'RUNNING',phase:'REQUEST_1'}),
    cancel:async value=>{cancelled.push(value);return {state:'CANCEL_REQUESTED'};}};
  const context=vm.createContext({Node:Element,TextEncoder,Intl,Date,JSON,console,
    document:{createElement:tag=>new Element(tag),createElementNS:(_ns,tag)=>new Element(tag),createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}},
    window:{confirm:()=>true},setInterval:fn=>{timers.push(fn);return timers.length;},clearInterval:()=>{}});
  for(const file of ['view-model.js','components.js','assistant.js']){
    const code=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(code,context,{filename:file});
  }
  context.testAPI=api;
  const workspace=vm.runInContext('createAssistantWorkspace(testAPI)',context);
  const root=workspace.mount([{id:'pond-a',name:'池 A'},{id:'pond-b',name:'池 B'}],'pond-a');
  return {workspace,root,config,api,sent,cancelled,timers,ready:tick};
}

test('normal model list, cloud/local confirmations, successful pair and safe text rendering',async()=>{
  const p=fixture();await p.ready();
  assert.match(p.root.textContent,/Qwen 3.8 Flash/);assert.match(p.root.textContent,/Ollama Qwen3.5 4B/);
  assert.match(p.root.textContent,/Thinking OFF · Normal/);assert.match(p.root.textContent,/REAL NETWORK REQUEST/);
  assert.doesNotMatch(p.root.textContent,/DeepSeek/);
  p.workspace.state.draft='什么是溶氧？';await p.workspace.send();assert.equal(p.sent.length,0);
  p.api.send=async value=>{p.sent.push(value);return success('<img src=x onerror=alert(1)>');};
  p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.workspace.state.turns.length,1);assert.equal(p.workspace.state.confirmed,false);
  assert.match(p.root.textContent,/<img src=x/);
  const walk=node=>[node,...node.children.flatMap(walk)];assert.equal(walk(p.root).filter(n=>n.tagName==='img').length,0);
  assert.equal(p.sent[0].device_id,'pond-a');assert.equal(p.sent[0].history.length,0);
  p.workspace.changePreset('ollama');assert.equal(p.workspace.state.turns.length,0);
  assert.match(p.root.textContent,/LOCAL MODEL REQUEST/);
});

test('only completed pairs enter history; trim notice; no raw Tool protocol or results',async()=>{
  const p=fixture();await p.ready();
  for(let i=0;i<2;i++){p.workspace.state.draft='问题 '+i;p.workspace.state.confirmed=true;await p.workspace.send();}
  assert.equal(p.sent[1].history.length,1);
  assert.deepEqual(Object.keys(p.sent[1].history[0]).sort(),['assistant','completed_at','user']);
  assert.doesNotMatch(JSON.stringify(p.sent[1].history),/tool_call|raw|activity|quality/);
  p.api.send=async()=>({...success(),result:{...success().result,history_trimmed:true}});
  p.workspace.state.draft='第三问';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.match(p.root.textContent,/较早对话未发送/);
  p.workspace.clear();assert.equal(p.workspace.state.turns.length,0);assert.equal(p.workspace.state.entries.length,0);
});

test('failed, truncated and empty turns never enter history; drafts survive',async()=>{
  const p=fixture();await p.ready();await p.workspace.send();assert.equal(p.sent.length,0);
  for(const code of ['ASSISTANT_RESPONSE_TRUNCATED','TOOL_EXECUTION_ERROR','TOTAL_TIMEOUT']){
    p.api.send=async()=>({result:{successful_turn:false,error_code:code,final_text:'incomplete'}});
    p.workspace.state.draft='保留问题';p.workspace.state.confirmed=true;await p.workspace.send();
    assert.equal(p.workspace.state.turns.length,0);assert.equal(p.workspace.state.draft,'保留问题');
    assert.doesNotMatch(p.root.textContent,/incomplete/);assert.match(p.root.textContent,new RegExp(code));
  }
});

test('Stop during Request #1/#2 and late response cannot commit a cancelled success',async()=>{
  for(const phase of ['REQUEST_1','REQUEST_2']){
    const p=fixture();await p.ready();let finish;
    p.api.send=async value=>{p.sent.push(value);return new Promise(resolve=>{finish=resolve;});};
    p.api.state=async()=>({phase,state:'RUNNING',activity:activity()});
    p.workspace.state.draft='现在水质？';p.workspace.state.confirmed=true;
    const turn=p.workspace.send();await tick();await p.timers[0]();
    assert.match(p.root.textContent,new RegExp(phase));
    p.workspace.changePreset('ollama');assert.equal(p.workspace.state.preset,'qwen');
    await p.workspace.stop();finish(success('late final'));await turn;
    assert.equal(p.cancelled.length,1);assert.equal(p.workspace.state.turns.length,0);
    assert.equal(p.workspace.state.pending,false);assert.equal(p.workspace.state.draft,'现在水质？');
    assert.doesNotMatch(p.root.textContent,/late final/);assert.match(p.root.textContent,/UNKNOWN/);
  }
});

test('epoch reset clears history and activity, keeps draft, never auto-resends',async()=>{
  for(const code of ['ASSISTANT_SESSION_EXPIRED','AI_ACCESS_DENIED']){
  const p=fixture();await p.ready();p.workspace.state.draft='第一问';p.workspace.state.confirmed=true;await p.workspace.send();
  p.api.send=async value=>{p.sent.push(value);throw new Error(code);};p.config.epoch='new epoch';
  p.workspace.state.draft='保留当前问题';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.sent.length,2);assert.equal(p.workspace.state.turns.length,0);assert.equal(p.workspace.state.activity,null);
  assert.equal(p.workspace.state.draft,'保留当前问题');assert.equal(p.workspace.state.config.epoch,'new epoch');
  assert.match(p.root.textContent,/重新发送当前问题/);
  }
});

test('NO_DATA/stale/invalid/partial use safe Activity; no raw body leaks into details',async()=>{
  const p=fixture();await p.ready();
  for(const [status,quality,freshness] of [['NO_DATA',undefined,undefined],['OK','valid','stale'],['OK','invalid','fresh'],['OK','partial','fresh']]){
    p.api.send=async()=>success('来源说明',activity(status,quality,freshness));
    p.workspace.state.draft='当前水质？';p.workspace.state.confirmed=true;await p.workspace.send();
    assert.match(p.root.textContent,new RegExp(status));
    if(quality)assert.match(p.root.textContent,new RegExp(quality));
  }
  assert.doesNotMatch(p.root.textContent,/control-token|tool_call_id|raw_result|system instruction/);
  p.workspace.changeDevice('pond-b');await p.ready();assert.equal(p.workspace.state.turns.length,0);
  assert.equal(p.workspace.state.device,'pond-b');
});

test('request profile changes require fresh confirmation, and poll responses are ordered',async()=>{
  const p=fixture();await p.ready();let resolve;
  p.api.send=async()=>new Promise(done=>{resolve=done;});
  p.workspace.state.draft='当前水质';p.workspace.state.confirmed=true;const turn=p.workspace.send();await tick();
  p.api.state=async()=>({state:'RUNNING',activity:{...activity(),revision:5}});await p.timers[0]();
  p.api.state=async()=>({state:'RUNNING',activity:{...activity(),revision:3}});await p.timers[0]();
  assert.equal(p.workspace.state.activity.revision,5);
  resolve({result:{successful_turn:false,error_code:'ASSISTANT_EXECUTION_PROFILE_CHANGED'}});await turn;
  assert.equal(p.workspace.state.confirmed,false);assert.match(p.root.textContent,/重新确认/);
  assert.equal(p.workspace.state.turns.length,0);
});

test('Stop after backend finalization cannot contradict the completed Commit Gate',async()=>{
  const p=fixture();await p.ready();let finish;
  p.api.send=async()=>new Promise(resolve=>{finish=resolve;});
  p.api.cancel=async()=>({state:'COMPLETED'});
  p.workspace.state.draft='当前水质？';p.workspace.state.confirmed=true;const turn=p.workspace.send();await tick();
  await p.workspace.stop();finish(success('已完成的回答'));await turn;
  assert.equal(p.workspace.state.turns.length,1);assert.match(p.root.textContent,/已在 Stop 前完成/);
});
