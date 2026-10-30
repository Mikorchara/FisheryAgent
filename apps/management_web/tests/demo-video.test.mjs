import test from 'node:test';
import assert from 'node:assert/strict';
import {createLocalVideoPreview} from '../static/components.js';
import {Element} from './dom-fixture.mjs';

function installDOM(){
  const oldDocument=globalThis.document,oldNode=globalThis.Node;
  globalThis.Node=Element;
  globalThis.document={createElement:t=>new Element(t),createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}};
  return ()=>{globalThis.document=oldDocument;globalThis.Node=oldNode;};
}

const walk=n=>[n,...n.children.flatMap(walk)];
test('local player is stable across polling and independent of camera selection',()=>{
  const restore=installDOM();
  try{
    const host=new Element(),preview=createLocalVideoPreview(host),meta={kind:'local_file',url:'/media/local-demo.mp4'};
    preview.update(meta,false);assert.equal(host.children.length,0);
    preview.update(meta,true);
    const video=walk(host).find(n=>n.tagName==='video');assert.ok(video);
    video.currentTime=18;let pauses=0;video.pause=()=>pauses++;
    preview.update(meta,true);preview.update({...meta},true);
    assert.equal(walk(host).find(n=>n.tagName==='video'),video);assert.equal(video.currentTime,18);
    assert.match(host.textContent,/未执行实时视频分析/);
    preview.update(meta,false);assert.equal(host.hidden,true);assert.equal(pauses,1);
    preview.update(meta,true);assert.equal(walk(host).find(n=>n.tagName==='video'),video);
    preview.suspend();assert.equal(pauses,2);
    preview.update(null);assert.equal(host.hidden,true);assert.equal(video.getAttribute('src'),null);
  }finally{restore();}
});

test('media URLs from arbitrary external metadata cannot create a player',()=>{
  const restore=installDOM();
  try{
    for(const url of ['https://evil.invalid/v.mp4','file:///private.mp4','/media/other.mp4']){
      const host=new Element();createLocalVideoPreview(host).update({kind:'local_file',url},true);
      assert.equal(host.hidden,true);assert.equal(host.children.length,0);
    }
  }finally{restore();}
});
