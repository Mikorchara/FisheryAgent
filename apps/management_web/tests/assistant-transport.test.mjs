import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {events,encode,response,expected,profile} from './assistant-stream-fixture.mjs';
test('actual service uses one authenticated POST, original abort signal and transport-specific revision; never falls back',async()=>{
  const calls=[];let reply=response(encode(events())),seen=[];
  const context=vm.createContext({TextEncoder,TextDecoder,URLSearchParams,console,
    fetch:async(...args)=>{calls.push(args);return reply;}});
  for(const file of ['assistant-events.js','services.js'])vm.runInContext(
    fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,''),context);
  const api=vm.runInContext('services.ai',context),controller=new AbortController();
  const config={browser_token:'fictional-browser-token'},value={request_id:expected.request_id,epoch:expected.epoch,
    revision:expected.revision,device_id:expected.device_id,question:'offline',confirm_network:true};
  const options={signal:controller.signal,profile,onEvent:e=>seen.push(e.kind)};
  reply.ok=true;
  await api.stream(value,config,options);
  assert.equal(calls[0][0],'/api/ai/messages/stream');assert.equal(calls[0][1].signal,controller.signal);
  assert.equal(calls[0][1].credentials,'same-origin');assert.equal(calls[0][1].headers['X-Management-AI'],config.browser_token);
  assert.equal(JSON.parse(calls[0][1].body).revision,profile.revision);assert.deepEqual(seen,['start','preview_reset','preview','final']);
  for(const code of ['ASSISTANT_EXECUTION_PROFILE_CHANGED','ASSISTANT_SESSION_EXPIRED','ASSISTANT_STREAMING_NOT_RELEASED','AI_ACCESS_DENIED']){
    reply={ok:false,json:async()=>({error_code:code})};await assert.rejects(api.stream(value,config,options),new RegExp(code));
  }
  assert.equal(calls.length,5);assert.ok(calls.every(c=>c[0]==='/api/ai/messages/stream'));
  reply={ok:true,json:async()=>({state:'CANCEL_REQUESTED'})};await api.cancel({request_id:'request',control_token:'control'},config);
  assert.equal(calls.at(-1)[1].keepalive,true);
});
