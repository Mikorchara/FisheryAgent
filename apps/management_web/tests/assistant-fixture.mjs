import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';

export const tick=()=>new Promise(resolve=>setImmediate(resolve));
export const activity=(status='OK',quality='valid',freshness='fresh')=>({counts:{tools_executed:1,model_requests_started:2},steps:[
  {kind:'model',request_index:1,state:'COMPLETED',outcome:'tool_calls'},
  {kind:'tool',tool_name:'get_current_water_quality',state:'COMPLETED',result_status:status,handler_started:true,
    quality,freshness,duration_ms:2,observed_at:'2026-10-15T00:00:00Z',evaluated_at:'2026-10-15T00:00:35Z'},
  {kind:'model',request_index:2,state:'COMPLETED',outcome:'final_answer'}],aggregate_usage:{total_tokens:42}});
export const success=(text='离线回答',details=activity())=>({result:{successful_turn:true,final_text:text,
  completed_at:'2026-10-15T00:01:00Z',activity:details,history_trimmed:false}});
export function fixture(configure=()=>{}){
  const config={epoch:'epoch',browser_token:'fictional-control-token',tools:['get_current_water_quality'],
    default_preset_id:'qwen',presets:[{preset_id:'qwen',display_name:'Qwen 3.8 Flash',runtime_type:'cloud',revision:'q'},
      {preset_id:'ollama',display_name:'Ollama Qwen3.5 4B',runtime_type:'local',revision:'o'}]};
  configure(config);
  const sent=[],cancelled=[],timers=[];
  const api={bootstrap:async()=>structuredClone(config),prepare:async()=>({request_id:'request',control_token:'control'}),
    send:async value=>{sent.push(structuredClone(value));return success();},state:async()=>({state:'RUNNING',phase:'REQUEST_1'}),
    cancel:async value=>{cancelled.push(value);return {state:'CANCEL_REQUESTED'};}};
  const context=vm.createContext({Node:Element,TextEncoder,AbortController,Intl,Date,JSON,console,
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

