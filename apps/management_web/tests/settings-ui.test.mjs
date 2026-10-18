import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
import {fixture as assistantFixture,tick} from './assistant-fixture.mjs';

const walk=n=>[n,...n.children.flatMap(walk)];
function setup(){
  const normal={can_send:true,max_output_tokens:1024,max_model_requests:3,max_tool_calls:2,max_tool_rounds:2,deadline_s:120,retry:0};
  const data={epoch:'fake-epoch',revision:'r1',browser_token:'fake-browser-token',default_available:true,
    preferences:{preset_id:'qwen',device_id:'pond-a',transport:'normal',show_details:true},
    devices:[{id:'pond-a',name:'池 A'},{id:'pond-b',name:'池 B'}],
    models:[{preset_id:'qwen',name:'Qwen',provider:'dashscope',kind:'cloud',model_id:'fixed-model',connection:'https://example.invalid/v1',
      capabilities:{tool_calling:'supported',streaming:'supported'},modes:{normal,streaming:{...normal,max_output_tokens:512}}}],
    credentials:[{provider:'dashscope',availability:'MISSING',source:'MISSING',editable:true,exists:false,revision:'key-r1'}],rag:{method:'TF-IDF',top_k:3,max_evidence_chars:800}};
  const writes=[],keys=[];let reads=0;
  const api={read:async()=>{reads++;return structuredClone(data);},save:async value=>{
    writes.push(structuredClone(value));data.preferences=value.preferences;data.revision='r2';return structuredClone(data);},
    credential:async value=>{keys.push(structuredClone(value));return {credential:{...data.credentials[0],exists:value.action==='save',
      availability:value.action==='save'?'PRESENT':'MISSING',source:'PROJECT_ENV',revision:'key-r2'}};}};
  const context=vm.createContext({console,Node:Element,
    document:{createElement:t=>new Element(t),createTextNode:t=>{const n=new Element('text');n.textContent=t;return n;}}});
  for(const file of ['components.js','settings.js'])vm.runInContext(fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8')
    .replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context,{filename:file});
  context.settingsAPI=api;context.toolPanel={mount:()=>new Element('tool-policy')};
  const panel=vm.runInContext('createSettingsWorkspace(settingsAPI,toolPanel)',context),root=panel.mount();
  const find=text=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text);
  const input=label=>walk(root).find(n=>n.getAttribute('aria-label')===label);
  return {panel,root,api,data,writes,keys,find,input,get reads(){return reads;}};
}

test('section changes preserve general and secret drafts; mounting or navigating never writes',async()=>{
  const p=setup();await tick();
  const mode=p.input('默认响应模式');mode.events.change({target:{value:'streaming'}});
  const key=p.input('dashscope API Key');key.value='fictional-unsubmitted-key';
  p.find('API 密钥').events.click();p.find('AI 模型管理').events.click();p.find('常规设置').events.click();
  assert.equal(p.input('dashscope API Key'),key);assert.equal(key.value,'fictional-unsubmitted-key');
  p.panel.mount();assert.equal(p.reads,1);assert.equal(p.keys.length,0);assert.equal(p.writes.length,0);
  p.find('保存常规设置').events.click();await tick();
  assert.equal(p.writes[0].preferences.transport,'streaming');assert.equal(key.value,'fictional-unsubmitted-key');
  assert.match(p.root.textContent,/下次打开页面生效/);assert.doesNotMatch(p.root.textContent,/fictional-unsubmitted-key/);
});

test('API key is explicit write only, cleared in DOM after submission and never echoed',async()=>{
  const p=setup();await tick();p.find('API 密钥').events.click();
  const key=p.input('dashscope API Key');key.value='fictional-key';
  p.find('保存 / 替换密钥').events.click();await tick();
  assert.equal(p.keys[0].secret,'fictional-key');assert.equal(key.value,'');
  assert.doesNotMatch(p.root.textContent,/fictional-key/);assert.match(p.root.textContent,/已安全保存/);
  p.find('清除密钥').events.click();assert.equal(p.keys.length,1);
  p.find('取消').events.click();assert.equal(p.keys.length,1);
  p.find('清除密钥').events.click();p.find('确认清除').events.click();await tick();
  assert.equal(p.keys[1].confirm_clear,true);assert.equal(p.keys[1].secret,null);assert.equal(p.keys[1].action,'remove');
});

test('credential errors are bounded; budget and model capabilities are honest read-only facts',async()=>{
  const p=setup();await tick();p.api.credential=async()=>{throw new Error('private exception containing fictional-key');};
  p.input('dashscope API Key').value='fictional-key';p.find('保存 / 替换密钥').events.click();await tick();
  assert.equal(p.input('dashscope API Key').value,'');assert.doesNotMatch(p.root.textContent,/private exception|fictional-key/);
  p.find('回答与执行预算').events.click();
  assert.match(p.root.textContent,/1024/);assert.match(p.root.textContent,/512/);assert.match(p.root.textContent,/暂无其他可编辑选项/);
  assert.equal(walk(p.root).some(n=>n.getAttribute('type')==='range'),false);
  assert.equal(walk(p.root).some(n=>n.tagName==='button'&&n.textContent==='添加模型'),false);
});

test('reloading requires explicit discard confirmation; no section switch discards drafts',async()=>{
  const p=setup();await tick();p.find('重新读取设置').events.click();assert.equal(p.reads,1);
  p.find('取消').events.click();assert.equal(p.reads,1);
  p.find('重新读取设置').events.click();p.find('确认重新读取').events.click();await tick();
  assert.equal(p.reads,2);assert.equal(p.keys.length,0);
});

test('preferences initialize one new workspace, never change an active session or send automatically',async()=>{
  const p=assistantFixture();await p.ready();
  p.workspace.state.turns=[{user:'已完成问题',assistant:'已完成回答',completed_at:'2026-10-18T00:00:00Z'}];
  p.workspace.setDefaults({preset_id:'ollama',transport:'streaming',show_details:false});
  assert.equal(p.workspace.state.transport,'normal');assert.equal(p.workspace.state.turns.length,1);
  const context=vm.createContext({Node:Element,TextEncoder,AbortController,Intl,Date,JSON,console,
    document:{createElement:t=>new Element(t),createElementNS:(_ns,t)=>new Element(t),
      createTextNode:t=>{const n=new Element('text');n.textContent=t;return n;}},
    window:{confirm:()=>true},setInterval:()=>1,clearInterval:()=>{},testAPI:p.api});
  for(const file of ['view-model.js','components.js','assistant.js'])vm.runInContext(fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8')
    .replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context);
  const next=vm.runInContext('createAssistantWorkspace(testAPI)',context);
  next.setDefaults({preset_id:'ollama',transport:'streaming',show_details:false});
  next.mount([{id:'pond-b',name:'池 B'}],'pond-b');await tick();
  assert.equal(next.state.preset,'ollama');assert.equal(next.state.transport,'streaming');
  assert.equal(next.state.device,'pond-b');assert.equal(next.state.detailsVisible,false);assert.equal(p.sent.length,0);
});

test('settings HTTP client uses existing browser access token and explicit POST, no persisted key',async()=>{
  const requests=[];const context=vm.createContext({URLSearchParams,fetch:async(url,options)=>{
    requests.push({url,options});return {ok:true,json:async()=>({credential:{availability:'PRESENT'}})};}});
  vm.runInContext(fs.readFileSync(new URL('../static/services.js',import.meta.url),'utf8')
    .replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context);
  await vm.runInContext("services.settings.credential({secret:'fictional-client-key'},{browser_token:'fake-browser-token'})",context);
  assert.equal(requests[0].url,'/api/settings/credentials');assert.equal(requests[0].options.method,'POST');
  assert.equal(requests[0].options.headers['X-Management-AI'],'fake-browser-token');
  assert.equal(requests[0].options.credentials,'same-origin');
  assert.doesNotMatch(fs.readFileSync(new URL('../static/settings.js',import.meta.url),'utf8'),/localStorage\s*\.|sessionStorage\s*\./);
});
