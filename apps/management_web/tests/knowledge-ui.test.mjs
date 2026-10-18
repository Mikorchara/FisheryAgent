import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const walk=n=>[n,...n.children.flatMap(walk)];
const value={id:'user-'+'a'.repeat(32),title:'蓝莓浮岛',category:'用户资料',body:'正文 <script>不可执行</script>',
  version:1,status:'ACTIVE',updated_at:'2026-10-18T01:00:00Z',origin:'user',source_id:'management:knowledge/example',source_version:'1'};
function fixture(){
  const records=[structuredClone(value)],calls=[];
  const api={exportUrl:(format,status)=>'/api/knowledge/export?'+new URLSearchParams({format,status}),list:async filters=>{calls.push(['list',filters]);return {items:structuredClone(records),total:records.length,categories:['用户资料'],write_token:'fictional-token',limit:50,offset:0};},
    get:async id=>{calls.push(['get',id]);return structuredClone(records.find(r=>r.id===id));},
    create:async(body,token)=>{calls.push(['create',body,token]);const item={...value,...body};records.push(item);return structuredClone(item);},
    edit:async(id,body,token)=>{calls.push(['edit',id,body,token]);const item=records.find(r=>r.id===id);Object.assign(item,body,{version:item.version+1});return structuredClone(item);},
    status:async(id,body,token)=>{calls.push(['status',id,body,token]);const item=records.find(r=>r.id===id);Object.assign(item,body,{version:item.version+1});return structuredClone(item);},
    search:async(body,token)=>{calls.push(['search',body,token]);return {status:'OK',evidence:[{id:value.id,text:value.body,category:value.category,source:value.source_id,source_version:'1'}]};}};
  const context=vm.createContext({Node:Element,Intl,Date,console,
    document:{createElement:tag=>new Element(tag),createElementNS:(_ns,tag)=>new Element(tag),createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}}});
  for(const file of ['view-model.js','components.js','knowledge.js']){
    const source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  context.api=api;
  const workspace=vm.runInContext('createKnowledgeWorkspace(api)',context),root=workspace.mount();
  const click=text=>walk(root).find(n=>n.tagName==='button'&&n.textContent===text).events.click();
  const fill=(label,text)=>walk(root).find(n=>n.getAttribute('aria-label')===label).events.input({target:{value:text}});
  return {api,workspace,root,calls,click,fill,ready:tick};
}
test('mount/search/filter/refresh never writes or invokes a model; content-only UI',async()=>{
  const p=fixture();await p.ready();p.workspace.mount();assert.deepEqual(p.calls.map(c=>c[0]),['list']);
  assert.match(p.root.textContent,/知识内容|用户创建|蓝莓浮岛/);assert.doesNotMatch(p.root.textContent,/Embedding|Top-K|Reranker|API Key/);
  p.fill('搜索知识内容','银鳞');p.click('查询内容');await p.ready();
  assert.equal(p.calls.at(-1)[1].q,'银鳞');assert.ok(p.calls.every(c=>c[0]==='list'));
  assert.equal(walk(p.root).some(n=>n.tagName==='script'),false);
});
test('create then edit sends explicit content and version; drafts are not auto-saved',async()=>{
  const p=fixture();await p.ready();p.click('新增知识');p.fill('知识标题','新标题');p.fill('知识分类','用户资料');p.fill('知识正文','新正文');
  assert.equal(p.calls.some(c=>c[0]==='create'),false);p.click('保存知识');await p.ready();
  assert.equal(p.calls.find(c=>c[0]==='create')[2],'fictional-token');assert.match(p.root.textContent,/知识已保存/);
  p.click('编辑知识');p.fill('知识正文','更新正文');p.click('保存知识');await p.ready();
  const edit=p.calls.find(c=>c[0]==='edit');assert.equal(edit[2].version,1);assert.equal(edit[2].body,'更新正文');
  assert.equal(p.workspace.state.selected.version,2);
});
test('disable/delete confirmation and recovery preserve records; imported builtins allow editing and deletion',async()=>{
  const p=fixture();await p.ready();p.click('查看详情');await p.ready();
  p.click('停用知识');await p.ready();assert.equal(p.calls.some(c=>c[0]==='status'),false);
  p.click('取消操作');assert.equal(p.workspace.state.confirmation,null);
  p.click('停用知识');p.click('确认停用');await p.ready();assert.equal(p.workspace.state.selected.status,'DISABLED');
  p.click('恢复启用');p.click('确认恢复');await p.ready();p.click('删除知识');p.click('确认删除');await p.ready();assert.equal(p.workspace.state.selected.status,'DELETED');
  p.click('恢复启用');p.click('确认恢复');await p.ready();assert.equal(p.workspace.state.selected.status,'ACTIVE');
  p.api.get=async()=>({...value,origin:'builtin'});p.click('查看详情');await p.ready();
  assert.match(p.root.textContent,/修改不回写/);assert.equal(walk(p.root).some(n=>n.tagName==='button'&&n.textContent==='编辑知识'),true);
  assert.equal(walk(p.root).some(n=>n.tagName==='button'&&n.textContent==='删除知识'),true);
});
test('conflict/error keeps draft, shows bounded error without raw private messages, and never retries',async()=>{
  const p=fixture();await p.ready();p.click('查看详情');await p.ready();p.click('编辑知识');p.fill('知识正文','保留草稿');
  let attempts=0;p.api.edit=async()=>{attempts++;throw Error('KNOWLEDGE_CONFLICT');};p.click('保存知识');await p.ready();
  assert.equal(attempts,1);assert.match(p.root.textContent,/其他窗口修改/);assert.equal(p.workspace.state.form.body,'保留草稿');
  p.api.edit=async()=>{throw Error('private path and credential');};p.click('保存知识');await p.ready();
  assert.doesNotMatch(p.root.textContent,/private path|credential/);assert.equal(p.workspace.state.form.body,'保留草稿');
});
test('test retrieval displays actual bounded evidence as text, source version and NO_MATCH without LLM',async()=>{
  const p=fixture();await p.ready();p.fill('检索关键词','蓝莓浮岛');p.click('测试检索');await p.ready();
  assert.equal(p.calls.at(-1)[0],'search');assert.equal(p.calls.at(-1)[1].query,'蓝莓浮岛');
  assert.match(p.root.textContent,/正文 <script>|版本 1|未调用模型/);assert.equal(walk(p.root).some(n=>n.tagName==='script'),false);
  p.api.search=async()=>({status:'NO_MATCH',evidence:[]});p.click('测试检索');await p.ready();assert.match(p.root.textContent,/没有合格命中/);
});

test('export controls select format and explicit status without writes or model calls',async()=>{
  const p=fixture();await p.ready();
  const choose=(label,value)=>walk(p.root).find(n=>n.getAttribute('aria-label')===label).events.change({target:{value}});
  choose('导出格式','markdown');choose('导出范围','all');
  const link=walk(p.root).find(n=>n.tagName==='a'&&n.textContent==='导出知识库');
  assert.equal(link.getAttribute('href'),'/api/knowledge/export?format=markdown&status=all');
  assert.ok(p.calls.every(c=>c[0]==='list'));
});
