import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fixture,success,tick} from './assistant-fixture.mjs';
import {events,encode,response,profile} from './assistant-stream-fixture.mjs';
const {readAssistantEvents}=await import('data:text/javascript;base64,'+fs.readFileSync(new URL('../static/assistant-events.js',import.meta.url)).toString('base64'));
const walk=n=>[n,...n.children.flatMap(walk)];
const find=(root,cls)=>walk(root).find(n=>n.className?.split(' ').includes(cls));
const setup=async(enabled=true)=>{const p=fixture(c=>c.presets[0].streaming={...profile,can_send:enabled,
  release_status:enabled?'local_experimental':'candidate',mode_reason:enabled?'active':'flag_disabled'});await p.ready();return p;};
function stream(p,rows=events()){
  p.api.stream=async(value,_config,{onEvent})=>{
    p.sent.push(structuredClone(value));return readAssistantEvents(response(encode(rows)),{
      ...value,max_output_tokens:512,release_status:'local_experimental'},onEvent);
  };
}
test('default Normal, unavailable candidate visible but blocked; modes preserve history and invalidate confirmation',async()=>{
  const p=await setup(false);assert.equal(p.workspace.state.transport,'normal');
  p.workspace.state.draft='正常问答';p.workspace.state.confirmed=true;await p.workspace.send();
  p.workspace.state.confirmed=true;p.workspace.changeTransport('streaming');
  assert.equal(p.workspace.state.confirmed,false);assert.equal(p.workspace.state.turns.length,1);
  assert.match(p.root.textContent,/实际 normal/); // Changing the next mode does not relabel the previous Turn.
  assert.match(p.root.textContent,/candidate.*未开放/);assert.match(p.root.textContent,/flag_disabled/);
  p.workspace.state.confirmed=true;p.workspace.state.draft='不能联网';await p.workspace.send();assert.equal(p.sent.length,1);
  assert.match(p.root.textContent,/ASSISTANT_STREAMING_NOT_RELEASED/);
  p.workspace.changeTransport('normal');assert.equal(p.workspace.state.turns.length,1);
});

test('local trial shows exact mode, cost ceiling and clear gate reasons without changing history or auto-sending',async()=>{
  const p=await setup();p.workspace.changeTransport('streaming');
  assert.match(p.root.textContent,/Streaming · 本地实验 · local_experimental/);
  assert.match(p.root.textContent,/512 tokens\/请求/);
  assert.match(p.root.textContent,/REAL NETWORK REQUEST · 本次最多 3 次模型请求/);
  assert.equal(p.sent.length,0);
  for(const reason of ['flag_disabled','scope_not_published','candidate','runtime_constraints_mismatch']){
    const blocked=fixture(c=>c.presets[0].streaming={...profile,can_send:false,
      release_status:'local_experimental',mode_reason:reason});await blocked.ready();
    blocked.workspace.changeTransport('streaming');
    assert.match(blocked.root.textContent,/Streaming 不可用/);
    assert.ok(blocked.root.textContent.includes(reason));
    assert.doesNotMatch(blocked.root.textContent,/当前仅 candidate/);
    blocked.workspace.state.draft='当前水质';blocked.workspace.state.confirmed=true;await blocked.workspace.send();
    assert.equal(blocked.sent.length,0);
  }
});
test('preview and final reuse the same message; safe text, one final pair, shared normal/stream history',async()=>{
  const p=await setup();let pendingNode;
  p.api.stream=async(value,_config,{onEvent})=>{
    p.sent.push(value);
    return readAssistantEvents(response(encode(events())),{...value,max_output_tokens:512,release_status:'local_experimental'},event=>{
      onEvent(event);
      if(event.kind==='preview'){
        assert.equal(p.workspace.state.turns.length,0);pendingNode=find(p.root,'pending');
        assert.match(p.root.textContent,/临时 <img/);assert.equal(walk(p.root).some(n=>n.tagName==='img'),false);
      }
    });
  };
  p.workspace.changeTransport('streaming');p.workspace.state.draft='当前问题';p.workspace.state.confirmed=true;
  await p.workspace.send();assert.equal(find(p.root,'assistant'),pendingNode);assert.match(p.root.textContent,/正式回答/);
  assert.doesNotMatch(p.root.textContent,/临时 <img/);assert.equal(p.sent[0].revision,profile.revision);
  assert.equal(p.workspace.state.turns.length,1);assert.equal(p.timers.length,0);
  p.workspace.changeTransport('normal');p.workspace.state.draft='历史解释';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.sent[1].history.length,1);assert.equal(p.sent[1].revision,'q');
  p.workspace.changeTransport('streaming');stream(p);p.workspace.state.draft='再次查询';p.workspace.state.confirmed=true;await p.workspace.send();
  assert.equal(p.sent[2].history.length,2);assert.equal(p.workspace.state.turns.length,3);
  assert.ok(p.sent.every(v=>!('transport'in v)&&!('mode'in v)&&!('max_output_tokens'in v)));
});
test('preview reset, failures, disconnect, invalid identities, illegal Final and late frames cannot commit',async()=>{
  for(const code of ['TOTAL_TIMEOUT','STREAM_TRUNCATED','TRACE_WRITE_FAILED','TOOL_EXECUTION_ERROR',null,'invalid-final','wrong-epoch']){
    const p=await setup();p.workspace.changeTransport('streaming');const rows=events();
    if(code===null)rows.pop();
    else if(code==='invalid-final')rows[3].result.trace_recorded=false;
    else if(code==='wrong-epoch')rows[2].epoch='old';
    else rows[3]={...rows[3],kind:'error',result:undefined,error_code:code};
    stream(p,rows);p.workspace.state.draft='保留问题';p.workspace.state.confirmed=true;await p.workspace.send();
    assert.equal(p.workspace.state.turns.length,0);assert.equal(p.workspace.state.pending,false);
    assert.equal(p.workspace.state.draft,'保留问题');assert.doesNotMatch(p.root.textContent,/临时 <img|正式回答 🐟/);
    assert.match(p.root.textContent,/临时预览已撤销/);assert.equal(p.sent.length,1);
  }
  const p=await setup();p.workspace.changeTransport('streaming');
  p.api.stream=async(value,_config,{onEvent})=>{
    for(const e of events().slice(0,3))onEvent(e);
    assert.match(p.root.textContent,/临时 <img/);
    onEvent({...events()[1],seq:4,request_index:2});assert.doesNotMatch(p.root.textContent,/临时 <img/);
    return {error_code:'TOTAL_TIMEOUT'};
  };
  p.workspace.state.draft='问题';p.workspace.state.confirmed=true;await p.workspace.send();assert.equal(p.workspace.state.turns.length,0);
});
test('Streaming Stop freezes controls, clears preview, aborts original channel; late final never enters history',async()=>{
  for(const phase of [1,2,3]){
    const p=await setup();p.workspace.changeTransport('streaming');let finish,signal,receive;
    p.api.stream=async(_value,_config,options)=>{signal=options.signal;receive=options.onEvent;
      for(const e of events().slice(0,3))receive(e);return new Promise(resolve=>{finish=resolve;});};
    p.workspace.state.draft='停止测试';p.workspace.state.confirmed=true;const pending=p.workspace.send();await tick();
    receive({...events()[1],request_index:phase,seq:4});receive({...events()[2],request_index:phase,seq:5});
    p.workspace.changeTransport('normal');p.workspace.changeDevice('pond-b');p.workspace.clear();
    assert.equal(p.workspace.state.transport,'streaming');assert.equal(p.workspace.state.device,'pond-a');
    await p.workspace.stop();assert.ok(signal.aborted);assert.doesNotMatch(p.root.textContent,/临时 <img/);
    receive(events()[2]);finish({result:events()[3].result});await pending;
    assert.equal(p.workspace.state.turns.length,0);assert.match(p.root.textContent,/USER_CANCELLED/);
  }
});
test('completed-before-Stop can accept verified final; pagehide cannot; failed cancel stays unknown',async()=>{
  for(const action of ['completed','pagehide','unknown']){
    const p=await setup();p.workspace.changeTransport('streaming');let finish,receive,signal;
    p.api.stream=async(_v,_c,options)=>{receive=options.onEvent;signal=options.signal;
      for(const e of events().slice(0,3))receive(e);return new Promise(resolve=>{finish=resolve;});};
    p.api.cancel=async()=>{if(action==='unknown')throw Error('private-message');return {state:'COMPLETED'};};
    p.workspace.state.draft='问题';p.workspace.state.confirmed=true;const pending=p.workspace.send();await tick();
    if(action==='pagehide')p.workspace.suspend();else await p.workspace.stop();
    finish({result:events()[3].result});await pending;
    assert.equal(p.workspace.state.turns.length,action==='completed'?1:0);
    assert.equal(signal.aborted,action!=='completed');assert.doesNotMatch(p.root.textContent,/private-message/);
  }
});
test('auto-follow, manual scroll protection, marker jump / keyboard and long conversation remain independent of history budget',async()=>{
  const p=await setup();const log=find(p.root,'management-messages');log.scrollHeight=2000;log.clientHeight=400;
  p.api.send=async()=>success('回答');
  for(let i=0;i<14;i++){p.workspace.state.draft='问题 '+i;p.workspace.state.confirmed=true;await p.workspace.send();}
  assert.equal(log.scrollTop,1600);assert.equal(find(p.root,'management-messages'),log);
  log.scrollTop=100;log.events.scroll();assert.equal(p.workspace.state.followLatest,false);
  const last=p.workspace.state.entries.at(-1);last.text+='变长';p.workspace.changeTransport('streaming');assert.equal(log.scrollTop,100);
  const nav=find(p.root,'question-navigation');assert.equal(nav.children.length,14);
  assert.match(nav.children[3].attributes.title,/问题 3/);nav.children[3].events.click();assert.equal(p.workspace.state.followLatest,false);
  nav.children[3].events.keydown({key:'End',preventDefault(){}});assert.ok(nav.children.at(-1).focused);
  find(p.root,'latest-message').events.click();assert.equal(log.scrollTop,1600);assert.equal(p.workspace.state.followLatest,true);
  p.workspace.clear();assert.equal(nav.children.length,0);
});
test('stream epoch/profile rejection refreshes once, clears confirmation and never resends',async()=>{
  for(const code of ['ASSISTANT_SESSION_EXPIRED','ASSISTANT_EXECUTION_PROFILE_CHANGED']){
    const p=await setup();p.workspace.state.draft='原问题';p.workspace.state.confirmed=true;await p.workspace.send();
    p.workspace.changeTransport('streaming');p.api.stream=async()=>{throw Error(code);};
    p.config.epoch=code==='ASSISTANT_SESSION_EXPIRED'?'restarted':'epoch';
    p.workspace.state.draft='保留草稿';p.workspace.state.confirmed=true;await p.workspace.send();
    assert.equal(p.workspace.state.confirmed,false);assert.equal(p.workspace.state.draft,'保留草稿');
    assert.match(p.root.textContent,/重新/);assert.equal(p.workspace.state.turns.length,code==='ASSISTANT_SESSION_EXPIRED'?0:1);
  }
});
test('manual upward reading survives cumulative preview and final while composer / message nodes remain stable',async()=>{
  const p=await setup();p.workspace.changeTransport('streaming');let emit,finish;
  p.api.stream=async(_v,_c,{onEvent})=>{emit=onEvent;return new Promise(resolve=>{finish=resolve;});};
  p.workspace.state.draft='阅读旧消息';p.workspace.state.confirmed=true;const pending=p.workspace.send();await tick();
  const log=find(p.root,'management-messages'),composer=find(p.root,'chat-composer');
  for(const e of events().slice(0,3))emit(e);
  assert.equal(log.scrollTop,600);
  log.scrollTop=30;log.events.scroll();
  emit({...events()[2],seq:4,text:'更长的临时正文'});assert.equal(log.scrollTop,30);
  assert.equal(find(p.root,'chat-composer'),composer);
  const reply=find(p.root,'pending');finish({result:events()[3].result});await pending;
  assert.equal(find(p.root,'assistant'),reply);assert.equal(log.scrollTop,30);
  assert.equal(p.workspace.state.followLatest,false);
});
