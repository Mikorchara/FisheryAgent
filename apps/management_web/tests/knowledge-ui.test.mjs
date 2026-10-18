import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {Element} from './dom-fixture.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const walk=n=>[n,...n.children.flatMap(walk)];
const value={id:'user-'+'a'.repeat(32),title:'蓝莓浮岛',category:'用户资料',body:'正文 <script>不可执行</script>',
  version:1,status:'ACTIVE',updated_at:'2026-10-18T01:00:00Z',origin:'user',source_id:'management:knowledge/example',source_version:'1'};
const builtin={...value,id:'builtin-'+'c'.repeat(24),title:'温度背景',category:'水质',origin:'builtin',
  source_id:'legacy:eel_knowledge.json',original_source_id:'legacy:eel_knowledge.json',source_version:'1.0',original_source_version:'1.0'};
function fixture(initial=[value]){
  const records=structuredClone(initial),calls=[],timers=new Map(),scrolls=[],panels=[];
  let now=0,timerId=0;
  const document={activeElement:null};
  const view={scrollX:0,scrollY:0,scrollTo:options=>{scrolls.push(options);view.scrollY=options.top;view.scrollX=options.left;}};
  class KnowledgeElement extends Element{
    constructor(tag){super(tag);if(tag==='details')this.open=false;}
    focus(options){super.focus();document.activeElement=this;this.focusOptions=options;}
    scrollIntoView(options){panels.push({node:this,options});view.scrollY=900;}
  }
  Object.assign(document,{createElement:tag=>new KnowledgeElement(tag),createElementNS:(_ns,tag)=>new KnowledgeElement(tag),
    createTextNode:text=>{const n=new KnowledgeElement('text');n.textContent=text;return n;}});
  const api={exportUrl:(format,status)=>'/api/knowledge/export?'+new URLSearchParams({format,status}),
    list:async filters=>{calls.push(['list',{...filters}]);const selected=records.filter(r=>(!filters.q||(r.title+' '+r.body).includes(filters.q))&&(!filters.category||r.category===filters.category)&&(!filters.status||r.status===filters.status));
      return {items:structuredClone(selected.slice(filters.offset,filters.offset+50)),total:selected.length,categories:[...new Set(records.map(r=>r.category))],write_token:'fictional-token',limit:50,offset:filters.offset};},
    get:async id=>{calls.push(['get',id]);return structuredClone(records.find(r=>r.id===id));},
    create:async(body,token)=>{calls.push(['create',body,token]);const item={...value,...body,id:'user-'+'b'.repeat(32)};records.push(item);return structuredClone(item);},
    edit:async(id,body,token)=>{calls.push(['edit',id,body,token]);const item=records.find(r=>r.id===id);Object.assign(item,body,{version:item.version+1});return structuredClone(item);},
    status:async(id,body,token)=>{calls.push(['status',id,body,token]);const item=records.find(r=>r.id===id);Object.assign(item,body,{version:item.version+1});return structuredClone(item);},
    search:async(body,token)=>{calls.push(['search',body,token]);return {status:'OK',evidence:[{id:value.id,text:value.body,category:value.category,source:value.source_id,source_version:'1'}]};}};
  const context=vm.createContext({Node:Element,document,window:view,Intl,Date,console,
    setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,at:now+ms,delay:ms});return id;},clearTimeout:id=>timers.delete(id)});
  for(const file of ['view-model.js','components.js','knowledge.js']){
    const source=fs.readFileSync(new URL('../static/'+file,import.meta.url),'utf8').replace(/^import .*;\s*$/gm,'').replace(/\bexport /g,'');
    vm.runInContext(source,context,{filename:file});
  }
  context.api=api;
  const workspace=vm.runInContext('createKnowledgeWorkspace(api)',context),root=workspace.mount();
  const nodes=()=>walk(root),button=(text,index=0)=>nodes().filter(n=>n.tagName==='button'&&n.textContent===text)[index];
  const clickNode=node=>{assert.ok(node,'expected control');assert.notEqual(node.getAttribute('disabled'),'disabled');node.events.click({currentTarget:node,target:node});};
  const control=label=>nodes().find(n=>n.getAttribute('aria-label')===label);
  const fill=(label,text)=>{const n=control(label);n.value=text;n.selectionStart=n.selectionEnd=text.length;n.events.input({target:n});return n;};
  const choose=(label,value)=>{const n=control(label);n.value=value;n.events.change({target:n});};
  const hasClass=(n,name)=>(n.className||'').split(' ').includes(name);
  return {api,records,workspace,root,calls,document,view,scrolls,panels,timers,nodes,button,clickNode,control,fill,choose,
    click:(text,index=0)=>clickNode(button(text,index)),ready:tick,
    cls:name=>nodes().find(n=>hasClass(n,name)),
    advance:async ms=>{now+=ms;for(const[id,t]of [...timers])if(t.at<=now){timers.delete(id);t.fn();}await tick();}};
}
const writes=p=>p.calls.filter(c=>['create','edit','status'].includes(c[0]));

test('mount, refresh and title/view access never write or invoke a model; one reusable detail panel',async()=>{
  const p=fixture();await p.ready();p.workspace.mount();assert.deepEqual(p.calls.map(c=>c[0]),['list']);
  assert.equal(p.button('查询内容'),undefined);assert.ok(p.button('查看'));assert.ok(p.button('编辑'));
  p.clickNode(p.cls('knowledge-title'));await p.ready();assert.equal(p.workspace.state.selected.id,value.id);
  assert.equal(p.nodes().filter(n=>n.getAttribute('aria-label')==='知识详情').length,1);
  assert.ok(p.panels.length>0);assert.equal(writes(p).length,0);
  assert.equal(p.nodes().some(n=>n.tagName==='script'),false);
});

test('detail Done closes without writes, preserves filters, list node, horizontal position, scroll and keyboard focus',async()=>{
  const p=fixture();await p.ready();p.fill('搜索知识内容','蓝莓');await p.advance(300);
  p.choose('知识分类筛选','用户资料');await p.ready();p.choose('知识状态','ACTIVE');await p.ready();
  const before=JSON.stringify(p.records),list=p.cls('knowledge-list-results'),opener=p.button('查看');
  list.children[0].scrollLeft=37;p.view.scrollY=640;
  opener.getBoundingClientRect=()=>({top:1000-p.view.scrollY});
  p.click('查看');await p.ready();assert.equal(p.view.scrollY,900);
  p.click('确定');assert.equal(p.workspace.state.selected,null);assert.equal(p.control('知识详情'),undefined);
  assert.equal(p.document.activeElement,opener);assert.equal(p.view.scrollY,640);assert.equal(list.children[0].scrollLeft,37);
  assert.equal(p.cls('knowledge-list-results'),list);assert.equal(p.workspace.state.q,'蓝莓');assert.equal(p.workspace.state.category,'用户资料');assert.equal(p.workspace.state.status,'ACTIVE');
  assert.equal(JSON.stringify(p.records),before);assert.equal(writes(p).length,0);
});

test('300 ms debounce retains the actual input node, focus, caret and latest request',async()=>{
  const p=fixture();await p.ready();const input=p.control('搜索知识内容');input.focus();
  p.fill('搜索知识内容','蓝');await p.advance(200);p.fill('搜索知识内容','蓝莓');
  assert.equal(p.timers.size,1);assert.equal([...p.timers.values()][0].delay,300);
  await p.advance(299);assert.equal(p.calls.length,1);input.selectionStart=input.selectionEnd=1;
  await p.advance(1);assert.equal(p.calls.length,2);assert.equal(p.calls.at(-1)[1].q,'蓝莓');
  assert.equal(p.control('搜索知识内容'),input);assert.equal(p.document.activeElement,input);assert.equal(input.selectionStart,1);
});

test('Enter submits immediately; clear cancels debounce and restores current category and status filters',async()=>{
  const p=fixture([value,builtin]);await p.ready();p.choose('知识分类筛选','水质');await p.ready();
  p.choose('知识状态','ACTIVE');await p.ready();p.fill('搜索知识内容','温度');
  let prevented=false;p.control('搜索知识内容').events.keydown({key:'Enter',preventDefault:()=>prevented=true});await p.ready();
  assert.equal(prevented,true);assert.equal(p.timers.size,0);assert.equal(p.calls.at(-1)[1].q,'温度');
  p.fill('搜索知识内容','');await p.ready();
  assert.equal(p.calls.at(-1)[1].q,'');assert.equal(p.calls.at(-1)[1].category,'水质');assert.equal(p.calls.at(-1)[1].status,'ACTIVE');
  assert.deepEqual(Array.from(p.workspace.state.data.items,r=>r.id),[builtin.id]);
});

test('Chinese composition never queries partial text or treats composition Enter as submit',async()=>{
  const p=fixture();await p.ready();const input=p.control('搜索知识内容');
  input.events.compositionstart();p.fill('搜索知识内容','lan');
  input.events.keydown({key:'Enter',isComposing:true,preventDefault:()=>assert.fail('composition Enter')});
  await p.advance(1000);assert.equal(p.calls.length,1);
  input.value='蓝莓';input.events.compositionend({target:input});await p.advance(300);
  assert.equal(p.calls.length,2);assert.equal(p.calls.at(-1)[1].q,'蓝莓');
});

test('stale responses are rejected as soon as new input arrives, including during debounce and late failures',async()=>{
  const p=fixture();await p.ready();const pending=[];
  p.api.list=filters=>new Promise((resolve,reject)=>pending.push({filters,resolve,reject}));
  p.fill('搜索知识内容','旧');await p.advance(300);p.fill('搜索知识内容','新');
  pending[0].resolve({items:[{...value,title:'过时结果'}],categories:[],total:1,write_token:'old'});await p.ready();
  assert.equal(p.workspace.state.data.items[0].title,value.title);assert.equal(p.workspace.state.token,'fictional-token');
  await p.advance(300);p.fill('搜索知识内容','最新');await p.advance(300);
  pending[2].resolve({items:[{...value,title:'最新结果'}],categories:[],total:1,write_token:'latest'});await p.ready();
  pending[1].reject(Error('private stale failure'));await p.ready();
  assert.equal(p.workspace.state.data.items[0].title,'最新结果');assert.equal(p.workspace.state.token,'latest');
  assert.doesNotMatch(p.root.textContent,/private stale failure|过时结果/);
});

test('filtered results can edit directly; save refreshes detail and list without losing search/filter controls',async()=>{
  const p=fixture([value,builtin]);await p.ready();p.fill('搜索知识内容','蓝莓');await p.advance(300);
  p.choose('知识分类筛选','用户资料');await p.ready();const input=p.control('搜索知识内容');
  p.click('编辑');await p.ready();p.fill('知识正文','蓝莓更新正文');p.click('保存知识');await p.ready();
  assert.equal(p.workspace.state.selected.version,2);assert.equal(p.workspace.state.selected.body,'蓝莓更新正文');
  assert.equal(p.calls.at(-1)[1].q,'蓝莓');assert.equal(p.calls.at(-1)[1].category,'用户资料');assert.equal(p.control('搜索知识内容'),input);
  assert.match(p.control('知识详情').textContent,/蓝莓更新正文/);assert.equal(p.workspace.state.data.items[0].version,2);
  assert.equal(writes(p).length,1);p.click('确定');assert.equal(p.document.activeElement,p.button('编辑'));
});

test('unsaved editing cannot silently close, navigate or save; discard confirmation is explicit',async()=>{
  const p=fixture([value,builtin]);await p.ready();p.click('编辑');await p.ready();p.fill('知识正文','保留草稿');
  assert.equal(p.button('确定'),undefined);p.click('取消编辑');assert.equal(p.workspace.state.form.body,'保留草稿');
  p.click('继续编辑');assert.equal(p.workspace.state.form.body,'保留草稿');
  p.click('查看',1);assert.ok(p.workspace.state.confirmation);assert.equal(p.calls.filter(c=>c[0]==='get').length,1);
  p.click('放弃修改');await p.ready();assert.equal(p.workspace.state.selected.id,builtin.id);assert.equal(p.workspace.state.form,null);
  assert.equal(writes(p).length,0);
});

test('create is explicit; refresh/export changes preserve the mounted editor and its draft',async()=>{
  const p=fixture();await p.ready();p.click('新增知识');p.fill('知识标题','新标题');p.fill('知识分类','用户资料');const body=p.fill('知识正文','新正文');
  p.click('刷新知识');await p.ready();p.choose('导出格式','markdown');assert.equal(p.control('知识正文'),body);assert.equal(p.workspace.state.form.body,'新正文');
  assert.equal(writes(p).length,0);p.click('保存知识');await p.ready();assert.equal(p.calls.find(c=>c[0]==='create')[2],'fictional-token');
  assert.match(p.root.textContent,/知识已保存/);assert.equal(p.workspace.state.selected.title,'新标题');
});

test('conflict keeps the same draft DOM, errors are bounded, and failed saves never retry',async()=>{
  const p=fixture();await p.ready();p.click('编辑');await p.ready();const body=p.fill('知识正文','保留草稿');
  let attempts=0;p.api.edit=async()=>{attempts++;throw Error('KNOWLEDGE_CONFLICT');};p.click('保存知识');await p.ready();
  assert.equal(attempts,1);assert.match(p.root.textContent,/其他窗口修改/);assert.equal(p.workspace.state.form.body,'保留草稿');assert.equal(p.control('知识正文'),body);
  p.api.edit=async()=>{throw Error('private path and credential');};p.click('保存知识');await p.ready();
  assert.doesNotMatch(p.root.textContent,/private path|credential/);assert.equal(p.workspace.state.form.body,'保留草稿');
});

test('imported and user records remain editable; confirmed disable/delete and restore preserve normal paths',async()=>{
  const p=fixture([builtin,value]);await p.ready();p.click('查看');await p.ready();assert.match(p.root.textContent,/修改不回写/);
  p.click('编辑知识');p.fill('知识正文','导入资料新版本');p.click('保存知识');await p.ready();assert.equal(p.workspace.state.selected.version,2);
  p.click('停用知识');assert.equal(p.calls.some(c=>c[0]==='status'),false);p.click('取消操作');
  p.click('停用知识');p.click('确认停用');await p.ready();assert.equal(p.workspace.state.selected.status,'DISABLED');
  p.click('恢复启用');p.click('确认恢复');await p.ready();p.click('删除知识');p.click('确认删除');await p.ready();assert.equal(p.workspace.state.selected.status,'DELETED');
  p.click('恢复启用');p.click('确认恢复');await p.ready();assert.equal(p.workspace.state.selected.status,'ACTIVE');
  p.click('确定');p.click('编辑',1);await p.ready();assert.equal(p.workspace.state.form.id,value.id);
});

test('advanced retrieval is collapsed, keeps input mounted, renders safe evidence and NO_MATCH without LLM',async()=>{
  const p=fixture();await p.ready();const advanced=p.cls('knowledge-advanced');assert.equal(advanced.open,false);
  assert.equal(p.calls.some(c=>c[0]==='search'),false);advanced.open=true;
  const input=p.fill('检索关键词','蓝莓浮岛');p.click('测试检索');await p.ready();
  assert.equal(p.control('检索关键词'),input);assert.equal(advanced.open,true);
  assert.equal(p.calls.at(-1)[0],'search');assert.match(p.root.textContent,/正文 <script>|版本 1|未调用模型/);assert.equal(p.nodes().some(n=>n.tagName==='script'),false);
  p.api.search=async()=>({status:'NO_MATCH',evidence:[]});p.click('测试检索');await p.ready();assert.match(p.root.textContent,/没有合格命中/);
});

test('export is a separate popup with explicit format/scope, stable controls, Escape and outside close',async()=>{
  const p=fixture();await p.ready();const menu=p.cls('knowledge-export');assert.equal(menu.open,false);menu.open=true;
  const select=p.control('导出格式');p.choose('导出格式','markdown');p.choose('导出范围','all');
  assert.equal(p.control('导出格式'),select);assert.equal(menu.open,true);
  const link=p.nodes().find(n=>n.tagName==='a'&&n.textContent==='下载知识库');
  assert.equal(link.getAttribute('href'),'/api/knowledge/export?format=markdown&status=all');
  p.root.events.keydown({key:'Escape'});assert.equal(menu.open,false);assert.equal(p.document.activeElement,menu.children[0]);
  menu.open=true;p.root.events.click({target:p.control('搜索知识内容')});assert.equal(menu.open,false);
  assert.ok(p.calls.every(c=>c[0]==='list'));
});
test('editing out of the current search keeps filters and safely returns focus to search',async()=>{
  const p=fixture();await p.ready();p.fill('搜索知识内容','蓝莓');await p.advance(300);
  p.click('编辑');await p.ready();p.fill('知识标题','银鳞温棚');p.fill('知识正文','完全更新的内容');p.click('保存知识');await p.ready();
  assert.equal(p.workspace.state.data.total,0);assert.equal(p.workspace.state.q,'蓝莓');
  p.click('确定');assert.equal(p.document.activeElement,p.control('搜索知识内容'));assert.equal(writes(p).length,1);
});

test('failed navigation after explicit draft discard never leaves an editable dangling form',async()=>{
  const p=fixture([value,builtin]);await p.ready();p.click('编辑');await p.ready();p.fill('知识正文','待放弃草稿');
  p.api.get=async()=>{throw Error('private detail failure');};p.click('查看',1);p.click('放弃修改');await p.ready();
  assert.equal(p.workspace.state.form,null);assert.equal(p.control('知识正文'),undefined);assert.ok(p.control('知识详情'));
  assert.doesNotMatch(p.root.textContent,/private detail failure/);assert.equal(writes(p).length,0);
});
test('explicit Save dismisses an outstanding discard confirmation without running its old action',async()=>{
  const p=fixture();await p.ready();p.click('编辑');await p.ready();p.fill('知识正文','明确保存的草稿');
  p.click('取消编辑');assert.ok(p.workspace.state.confirmation);p.click('保存知识');await p.ready();
  assert.equal(p.workspace.state.confirmation,null);assert.equal(p.cls('knowledge-confirm'),undefined);
  assert.equal(p.workspace.state.selected.body,'明确保存的草稿');assert.equal(p.workspace.state.selected.version,2);
  assert.equal(writes(p).length,1);assert.ok(p.button('确定'));
});
