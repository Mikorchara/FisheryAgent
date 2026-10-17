// Python supplies real management HTTP/SSE frames from a network-blocked Fake SDK.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {fixture} from './assistant-fixture.mjs';
import {response} from './assistant-stream-fixture.mjs';
const {readAssistantEvents}=await import('data:text/javascript;base64,'+fs.readFileSync(new URL('../static/assistant-events.js',import.meta.url)).toString('base64'));
const {config,frames,request_id,tools,requests}=JSON.parse(fs.readFileSync(0,'utf8'));
const p=fixture(c=>Object.assign(c,config));await p.ready();
p.api.prepare=async()=>({request_id,control_token:'offline-control'});
let previews=0,resets=0;
p.api.stream=async(value,_c,{onEvent,profile})=>readAssistantEvents(response(frames,{chunkSize:11}),{
  ...value,max_output_tokens:profile.max_output_tokens,release_status:profile.release_status},event=>{
  onEvent(event);if(event.kind==='preview')previews++;if(event.kind==='preview_reset')resets++;
  assert.equal(p.workspace.state.turns.length,0,'preview/activity must not commit a Turn');
});
p.workspace.changeTransport('streaming');p.workspace.state.draft='离线协议集成';
await p.workspace.send();
assert.equal(p.workspace.state.turns.length,1,p.workspace.state.status);
assert.equal(p.workspace.state.entries.filter(e=>e.kind==='assistant').length,1);
assert.equal(p.workspace.state.activity.counts.tools_executed,tools);
assert.equal(p.workspace.state.activity.counts.model_requests_started,requests);
assert.ok(previews>0);assert.ok(resets>=requests);
assert.ok(p.root.textContent.includes(`Request #${requests}`));
assert.equal('confirmed' in p.workspace.state,false);
console.log(JSON.stringify({completed:true,requests,tools,previews,resets}));
