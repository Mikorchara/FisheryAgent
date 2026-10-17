import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture,activity,success,tick} from './assistant-fixture.mjs';

const unifiedConfig=c=>{
  c.presets[0].execution={can_send:true,release_status:'local_experimental',mode:'BOUNDED_MULTI_ROUND',
    revision:'unified-revision',max_model_requests:3,max_output_tokens:1024,
    tools:['get_current_water_quality','search_fishery_knowledge','get_water_quality_history']};
};
const walk=node=>[node,...node.children.flatMap(walk)];
const checkbox=p=>walk(p.root).find(n=>n.tagName==='input'&&n.getAttribute('type')==='checkbox');
const sendButton=p=>walk(p.root).find(n=>n.tagName==='button'&&n.textContent==='发送');

test('unified tools need no history action or Profile; actual tools and revision drive confirmation',async()=>{
  const p=fixture(unifiedConfig);await p.ready();
  assert.equal('nextAction' in p.workspace.state,false);assert.equal(p.workspace.historyQuery,undefined);
  assert.doesNotMatch(p.root.textContent,/执行 Profile|下一条：历史|取消历史查询/);
  assert.equal(walk(p.root).some(n=>n.tagName==='button'&&n.textContent==='历史查询'),false);
  assert.match(p.root.textContent,/当前水质、项目养殖知识、历史水质/);
  checkbox(p).events.change({target:{checked:true}});
  p.workspace.state.config.presets[0].execution.revision='changed-revision';p.workspace.state.draft='过去30分钟溶氧变化';
  await p.workspace.send();assert.equal(p.sent.length,0);assert.equal(p.workspace.state.confirmed,false);
  checkbox(p).events.change({target:{checked:true}});await p.workspace.send();
  assert.equal(p.sent[0].revision,'changed-revision');assert.equal('action' in p.sent[0],false);
  assert.equal('execution_profile' in p.sent[0],false);assert.equal(p.workspace.state.turns.length,1);
});

test('unified mode/revocation blocks and unchecks confirmation without fallback or history loss',async()=>{
  const p=fixture(unifiedConfig);await p.ready();p.workspace.state.draft='第一问';p.workspace.state.confirmed=true;await p.workspace.send();
  p.config.presets[0].execution.can_send=false;p.config.presets[0].execution.revision='revoked';
  p.workspace.state.draft='保留草稿';p.workspace.state.confirmed=true;p.workspace.policyChanged();await tick();
  assert.equal(p.workspace.state.turns.length,1);assert.equal(p.workspace.state.draft,'保留草稿');
  assert.equal(checkbox(p).getAttribute('checked'),null);assert.equal(sendButton(p).getAttribute('disabled'),'disabled');
  p.workspace.state.confirmed=true;await p.workspace.send();assert.equal(p.sent.length,1);
  p.workspace.changeTransport('streaming');assert.equal(p.workspace.state.confirmed,false);
  assert.equal(p.workspace.state.turns.length,1);assert.equal(p.sent.length,1);
});

test('Send and Stop have their own fixed action group, independent of latest/status text',async()=>{
  const p=fixture(unifiedConfig);await p.ready();
  for(const mode of ['normal','fullscreen','reading','normal']){
    p.workspace.changeView(mode);
    const group=walk(p.root).find(n=>n.className==='composer-actions');
    assert.deepEqual(group.children.map(n=>n.textContent),['发送','Stop']);
    assert.equal(group.children.some(n=>n.className?.includes('latest-message')),false);
    assert.equal(group.parentNode.children[0].className,'composer-navigation');
  }
});

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
  assert.equal('executionProfile' in p.workspace.state,false);
  assert.doesNotMatch(p.root.textContent,/执行 Profile|Scope/);
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

test('parameter rejection shows bounded diagnostics and never commits history or renders raw metadata',async()=>{
  const p=fixture();await p.ready();
  const rejected=activity();rejected.counts={tools_executed:0,model_requests_started:1};
  rejected.steps=rejected.steps.slice(0,2);Object.assign(rejected.steps[1],{
    state:'REJECTED',result_status:'ERROR',handler_started:false,
    argument_diagnostic:{schema_version:1,stage:'definition',reason:'UNEXPECTED_ARGUMENTS',
      argument_bytes:42,object_member_count:1,raw:'fictional-private-argument'}});
  p.api.send=async()=>({result:{successful_turn:false,error_code:'INVALID_TOOL_ARGUMENTS',activity:rejected}});
  p.workspace.state.draft='水质';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.workspace.state.turns.length,0);
  assert.equal(p.workspace.state.pending,false);
  assert.match(p.root.textContent,/被拒绝的 Tool 未执行/);
  assert.match(p.root.textContent,/UNEXPECTED_ARGUMENTS/);
  assert.match(p.root.textContent,/definition/);
  assert.doesNotMatch(p.root.textContent,/fictional-private-argument/);
});

test('Knowledge activity distinguishes project evidence and NO_MATCH from current water',async()=>{
  const p=fixture();p.config.tools.push('search_fishery_knowledge');await p.ready();
  for(const [status,count] of [['OK',1],['NO_MATCH',0]]){
    const details=activity();details.steps[1]={kind:'tool',tool_name:'search_fishery_knowledge',
      display_name:'项目养殖知识检索',state:'COMPLETED',handler_started:true,result_status:status,
      evidence_count:count,duration_ms:2,
      query:'fictional-query-do-not-log',evidence:'fictional-evidence-body-do-not-log'};
    p.api.send=async()=>success('背景知识解释',details);
    p.workspace.state.draft='请检索项目资料';p.workspace.state.confirmed=true;await p.workspace.send();
    assert.match(p.root.textContent,/项目养殖知识检索/);
    assert.match(p.root.textContent,/项目背景知识 · 不代表当前观测或疾病确诊/);
    assert.match(p.root.textContent,/命中条数/);
    assert.match(p.root.textContent,/使用了 1 个 Tool/);
    assert.doesNotMatch(p.root.textContent,/已使用水质查询 Tool|fictional-query-do-not-log|fictional-evidence-body-do-not-log/);
    if(status==='NO_MATCH')assert.match(p.root.textContent,/检索完成 · 无合格命中/);
  }
  assert.equal(p.workspace.state.turns.length,2);
  assert.equal(p.workspace.state.confirmed,false);
});

test('management multi-round budgets follow selected preset and two Tool steps commit one answer',async()=>{
  const p=fixture(config=>{
    config.tools.push('search_fishery_knowledge');
    config.presets[0].execution={mode:'BOUNDED_MULTI_ROUND',can_send:true,max_model_requests:3,release_status:'local_experimental'};
    config.presets[1].execution={mode:'SINGLE_ROUND',can_send:true,max_model_requests:2};
  });
  await p.ready();
  assert.match(p.root.textContent,/最多 3 次模型请求/);assert.match(p.root.textContent,/多轮 · 本地实验/);
  const details=activity();details.counts={model_requests_started:3,tools_executed:2};
  details.steps.push({kind:'tool',tool_name:'search_fishery_knowledge',state:'COMPLETED',handler_started:true,
    result_status:'NO_MATCH',evidence_count:0,duration_ms:1},{kind:'model',request_index:3,state:'COMPLETED',outcome:'final_answer'});
  p.api.send=async()=>success('single final after two tools',details);
  p.workspace.state.draft='当前水质，异常时检索知识';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.workspace.state.turns.length,1);
  assert.equal(p.workspace.state.entries.filter(e=>e.kind==='assistant').length,1);
  assert.match(p.root.textContent,/使用了 2 个 Tool/);assert.match(p.root.textContent,/Request #3/);
  assert.match(p.root.textContent,/search_fishery_knowledge/);
  p.workspace.changePreset('ollama');
  assert.equal(p.workspace.state.confirmed,false);assert.match(p.root.textContent,/最多 2 次本地模型请求/);
});

test('unmatched multi-round scope blocks sending before any HTTP model attempt',async()=>{
  const p=fixture(config=>{config.presets[0].execution={mode:'SINGLE_ROUND',can_send:false,max_model_requests:2};});
  await p.ready();p.workspace.state.draft='current question';p.workspace.state.confirmed=true;
  await p.workspace.send();assert.equal(p.sent.length,0);
  assert.match(p.root.textContent,/授权组合不匹配/);
  assert.equal(p.workspace.state.turns.length,0);
});
