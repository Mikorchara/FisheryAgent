import test from 'node:test';
import assert from 'node:assert/strict';
import {fixture,success,tick,activity} from './assistant-fixture.mjs';
const walk=n=>[n,...n.children.flatMap(walk)];
const find=(root,cls)=>walk(root).find(n=>n.className?.split(' ').includes(cls));

test('fullscreen/reading are view-only; preserve transcript DOM, draft, confirmation and manual scroll',async()=>{
  const p=fixture();await p.ready();
  p.workspace.state.draft='长回答';p.workspace.state.confirmed=true;
  p.api.send=async value=>{p.sent.push(value);return success('长回答\n'.repeat(300));};
  await p.workspace.send();
  const pane=find(p.root,'management-messages'),message=find(p.root,'assistant');
  pane.scrollTop=123;pane.events.scroll();
  p.workspace.state.draft='下一问';p.workspace.state.confirmed=true;
  for(const mode of ['fullscreen','reading']){
    p.workspace.changeView(mode);assert.match(p.root.className,new RegExp('view-'+mode));
    assert.equal(find(p.root,'management-messages'),pane);assert.equal(find(p.root,'assistant'),message);
    assert.equal(p.workspace.state.confirmed,true);assert.equal(p.workspace.state.draft,'下一问');
    assert.equal(p.workspace.state.turns.length,1);assert.equal(p.sent.length,1);
  }
  p.workspace.exitView();assert.equal(p.workspace.state.viewMode,'fullscreen');assert.equal(pane.scrollTop,123);
  p.root.events.keydown({key:'Escape',preventDefault(){}});
  assert.equal(p.workspace.state.viewMode,'normal');assert.equal(pane.scrollTop,123);
  assert.equal(p.workspace.state.followLatest,false);assert.equal(p.cancelled.length,0);
});

test('switching views during a pending multi-tool turn keeps one handle, one final and usable Stop',async()=>{
  const p=fixture();await p.ready();let resolve;
  const details=activity();details.counts.tools_executed=2;
  details.steps.splice(2,0,{kind:'tool',tool_name:'search_fishery_knowledge',handler_started:true,state:'COMPLETED',result_status:'OK'});
  p.api.send=value=>{p.sent.push(value);return new Promise(done=>resolve=done);};
  p.workspace.state.draft='两工具';p.workspace.state.confirmed=true;const running=p.workspace.send();await tick();
  const handle=p.workspace.state.control;
  p.workspace.changeView('fullscreen');p.workspace.changeView('reading');
  assert.equal(p.workspace.state.control,handle);assert.equal(p.workspace.state.pending,true);
  assert.ok(walk(p.root).some(n=>n.tagName==='button'&&n.textContent==='Stop'&&!n.attributes.disabled));
  resolve(success('最终完整回答',details));await running;
  assert.equal(p.workspace.state.turns.length,1);assert.equal(p.sent.length,1);assert.equal(p.cancelled.length,0);
  assert.match(p.root.textContent,/使用了 2 个 Tool/);
  p.workspace.exitView();p.workspace.exitView();assert.equal(p.workspace.state.turns.length,1);
});

test('reading mode does not compromise cancellation or commit a late final',async()=>{
  const p=fixture();await p.ready();let resolve;
  p.api.send=value=>{p.sent.push(value);return new Promise(done=>resolve=done);};
  p.workspace.state.draft='停止';p.workspace.state.confirmed=true;const running=p.workspace.send();await tick();
  p.workspace.changeView('reading');await p.workspace.stop();resolve(success());await running;
  assert.equal(p.workspace.state.turns.length,0);assert.equal(p.cancelled.length,1);
  assert.match(p.root.textContent,/USER_CANCELLED/);p.workspace.exitView();assert.equal(p.sent.length,1);
});
