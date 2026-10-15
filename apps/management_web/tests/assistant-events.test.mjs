import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {events,encode,response,expected} from './assistant-stream-fixture.mjs';
const {readAssistantEvents}=await import('data:text/javascript;base64,'+fs.readFileSync(new URL('../static/assistant-events.js',import.meta.url)).toString('base64'));

test('bounded POST SSE reads fragmented UTF-8 / CRLF / keepalives and closes its reader',async()=>{
  for(const chunkSize of [1,7,65536]){
    const seen=[],source=response(': keep-alive\r\n\r\n'+encode(events()).replace(/\n/g,'\r\n'),{chunkSize});
    const result=await readAssistantEvents(source,expected,e=>seen.push(e.kind));
    assert.equal(result.result.final_text,'正式回答 🐟');assert.equal(source.closed(),true);
    assert.deepEqual(seen,['start','preview_reset','preview','final']);
  }
});
test('duplicate and late identical frames have no effects; gaps, reordered identities and extra terminal fail closed',async()=>{
  const rows=events();const seen=[];
  await readAssistantEvents(response(encode([rows[0],rows[0],rows[1],rows[0],...rows.slice(2),rows[3]])),expected,e=>seen.push(e.seq));
  assert.deepEqual(seen,[1,2,3,4]);
  for(const list of [[rows[1],rows[0]], [rows[0],rows[2]], [...rows,{...rows[3],seq:5}],
    [{...rows[0],epoch:'old'}],[{...rows[0],request_id:'another'}],
    [{...rows[0],execution_revision:'changed'}],[{...rows[0],device_id:'pond-b'}],
    [{...rows[0],max_output_tokens:256}],[{...rows[0],release_status:'released'}]]){
    await assert.rejects(readAssistantEvents(response(encode(list),{chunkSize:65536}),expected),/EVENT_INVALID/);
  }
});
test('unknown kinds, illegal preview/Final, error-success contradictions and corrupt frames cannot commit',async()=>{
  const rows=events();
  const mutations=[e=>e.kind='unknown',e=>e.provisional=false,e=>e.request_index=4,e=>e.text='x'.repeat(16385),
    e=>e.request_index=2];
  for(const mutate of mutations){const copy=structuredClone(rows);mutate(copy[2]);
    await assert.rejects(readAssistantEvents(response(encode(copy)),expected),/EVENT_INVALID/);}
  for(const patch of [{successful_turn:false},{status:'failed'},{trace_recorded:false},{final_finish_reason:'length'},
    {final_text:''},{device_id:'pond-b'},{request_id:'old'},{completed_at:null},{error_code:'TOOL_ERROR'}]){
    const copy=structuredClone(rows);Object.assign(copy[3].result,patch);
    await assert.rejects(readAssistantEvents(response(encode(copy)),expected),/EVENT_INVALID/);
  }
  for(const suffix of ['data: bad\n\n','id: 4\ndata: {}\n\n','retry: 100\n\n'])
    await assert.rejects(readAssistantEvents(response(encode(rows.slice(0,3))+suffix),expected),/EVENT_INVALID/);
  const copy=structuredClone(rows);copy[3].kind='error';
  await assert.rejects(readAssistantEvents(response(encode(copy)),expected),/EVENT_INVALID/);
});
test('disconnect, partial frame, oversized input, invalid UTF-8 and transport failure close resources without retry',async()=>{
  for(const text of [encode(events().slice(0,3)),encode(events()).slice(0,-1),'x'.repeat(512*1024+1)]){
    const source=response(text,{chunkSize:600000});
    await assert.rejects(readAssistantEvents(source,expected),/STREAM_INTERRUPTED|EVENT_INVALID/);assert.ok(source.closed());
  }
  const source=response('');source.body.getReader=()=>({read:async()=>({value:new Uint8Array([255]),done:false}),cancel:async()=>{},releaseLock:()=>{}});
  await assert.rejects(readAssistantEvents(source,expected),/EVENT_INVALID/);
  const broken=response('');let cancelled=false;
  broken.body.getReader=()=>({read:async()=>{throw new Error('offline');},cancel:async()=>{cancelled=true;},releaseLock:()=>{}});
  await assert.rejects(readAssistantEvents(broken,expected),/offline/);assert.ok(cancelled);
});
test('safe error/cancelled terminal has no successful payload, activity revisions cannot go backward',async()=>{
  for(const code of ['USER_CANCELLED','TOTAL_TIMEOUT','STREAM_TRUNCATED','TRACE_WRITE_FAILED']){
    const rows=events().slice(0,3);rows.push({...rows[0],seq:4,kind:code==='USER_CANCELLED'?'cancelled':'error',error_code:code});
    const result=await readAssistantEvents(response(encode(rows)),expected);assert.equal(result.error_code,code);
  }
  const rows=events(),a=structuredClone(rows[3].result.activity);a.state='RUNNING';a.revision=2;
  rows.splice(3,0,{...rows[0],kind:'activity',seq:4,state:'RUNNING',phase:'REQUEST_1',activity:a});rows[4].seq=5;
  await assert.rejects(readAssistantEvents(response(encode(rows)),expected),/EVENT_INVALID/);
});
test('old-request reset cannot retract a newer preview and activity budgets stay frozen',async()=>{
  const base=events(),rows=[...base.slice(0,3),{...base[1],seq:4,request_index:2},
    {...base[1],seq:5,request_index:1},{...base[2],seq:6,request_index:2},{...base[3],seq:7}];
  const seen=[];await readAssistantEvents(response(encode(rows)),expected,e=>seen.push(e.seq));
  assert.deepEqual(seen,[1,2,3,4,6,7]);
  rows.at(-1).result.activity.budget.model_requests=4;
  await assert.rejects(readAssistantEvents(response(encode(rows)),expected),/EVENT_INVALID/);
});
