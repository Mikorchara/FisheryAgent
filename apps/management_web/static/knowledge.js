import {el,card,button,badge,rows,table,empty} from './components.js';
import {timeText} from './view-model.js';

// Content operations only. This page never requests a model or changes retrieval settings.
export function createKnowledgeWorkspace(api){
  const root=el('div',{class:'knowledge-management'});
  const s={data:null,token:null,q:'',category:'',status:'',offset:0,selected:null,form:null,
    busy:false,loaded:false,message:'',testQuery:'',hits:null,confirmation:null};
  let loading=0;
  const statusName=value=>({ACTIVE:'启用',DISABLED:'已停用',DELETED:'已删除（可恢复）'}[value]||'未知');
  const describeError=error=>({KNOWLEDGE_CONFLICT:'内容已被其他窗口修改。请刷新并重新打开编辑，当前草稿已保留。',
    KNOWLEDGE_STORAGE_ERROR:'保存或读取失败，原有内容未被覆盖。请稍后重试。',
    KNOWLEDGE_NOT_CONNECTED:'知识内容服务未接入，请检查管理服务器启动方式。',
    KNOWLEDGE_ACCESS_DENIED:'页面授权已过期，请刷新知识列表后重试。',
    INVALID_KNOWLEDGE_CONTENT:'请检查标题、分类和正文；正文最多 6000 字，不能包含非法字符。',
    KNOWLEDGE_LIMIT:'知识条目已达上限（200 条，含可恢复删除），请联系维护者。',
    BUILTIN_KNOWLEDGE_READ_ONLY:'内置知识正文只读，可以停用。',
    INVALID_KNOWLEDGE_QUERY:'检索关键词无效，请使用 1–512 字的单行文字。'}[error?.message]||'知识操作失败，请刷新后重试。');
  const field=(label,value,change,maximum,multiline=false)=>el('label',{class:'field'},[
    el('span',{text:label}),el(multiline?'textarea':'input',{'aria-label':label,maxlength:maximum,
      ...(multiline?{rows:10,text:value}:{value}),...(s.busy?{disabled:'disabled'}:{}),oninput:e=>change(e.target.value)})]);
  async function load(){
    const generation=++loading;s.busy=true;s.confirmation=null;render();
    try{
      const data=await api.list({q:s.q,category:s.category,status:s.status,offset:s.offset});
      if(generation!==loading)return;
      s.data=data;s.token=data.write_token;s.loaded=true;
    }catch(e){if(generation===loading){s.message=describeError(e);s.data=null;}}
    finally{if(generation===loading){s.busy=false;render();}}
  }
  async function detail(item){
    if(s.busy)return;s.busy=true;render();
    try{s.selected=await api.get(item.id);s.form=null;s.message='';s.confirmation=null;}catch(e){s.message=describeError(e);}
    finally{s.busy=false;render();}
  }
  async function save(){
    if(s.busy||!s.form||!s.token)return;
    const form={...s.form},value={title:form.title,category:form.category,body:form.body};
    s.busy=true;render();
    try{
      s.selected=form.id?await api.edit(form.id,{...value,version:form.version},s.token):await api.create(value,s.token);
      s.form=null;s.message='知识已保存，后续检索使用新版本。';s.hits=null;await load();
    }catch(e){s.message=describeError(e);}finally{s.busy=false;render();}
  }
  async function setStatus(item,status){
    if(s.busy||!s.token)return;
    s.confirmation=null;
    s.busy=true;render();
    try{s.selected=await api.status(item.id,{version:item.version,status},s.token);s.hits=null;
      s.message=`知识已${statusName(status)}。`;await load();
    }catch(e){s.message=describeError(e);}finally{s.busy=false;render();}
  }
  async function searchTest(){
    if(s.busy||!s.token)return;s.busy=true;s.hits=null;render();
    try{s.hits=await api.search({query:s.testQuery},s.token);s.message='检索完成，未调用模型。';}
    catch(e){s.message=describeError(e);}finally{s.busy=false;render();}
  }
  function render(){
    const disabled=s.busy?{disabled:'disabled'}:{};
    const action=(text,fn,tone='secondary')=>el('button',{class:'button '+tone,type:'button',...disabled,text,onclick:fn});
    const filter=(label,choices,value,change)=>el('label',{class:'field'},[el('span',{text:label}),
      el('select',{'aria-label':label,...disabled,onchange:e=>{change(e.target.value);s.offset=0;void load();}},
        choices.map(([id,name])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name]))) ]);
    const list=s.data?table(['标题','分类','来源','状态','更新时间','操作'],s.data.items,item=>[
      el('strong',{text:item.title}),item.category,item.origin==='builtin'?'内置项目知识':'用户创建',
      badge(statusName(item.status),item.status==='ACTIVE'?'success':'neutral'),
      item.updated_at?timeText(item.updated_at):'随项目发布'],item=>void detail(item)):
      empty(s.busy?'正在加载知识':'知识列表暂不可用','请刷新重试；不会显示假知识内容。','book');
    const editor=s.form?card(s.form.id?'编辑知识':'新增知识','正文作为不可信背景资料，不会成为系统指令。',[
      field('知识标题',s.form.title,v=>s.form.title=v,120),field('知识分类',s.form.category,v=>s.form.category=v,40),
      field('知识正文',s.form.body,v=>s.form.body=v,6000,true),
      el('div',{class:'actions'},[action('保存知识',()=>void save(),'primary'),action('取消编辑',()=>{s.form=null;render();})])]):null;
    const item=s.selected;
    const details=item&&!s.form?card(item.title,item.origin==='builtin'?'内置项目知识 · 正文只读':'用户创建的知识',[
      rows([['分类',item.category],['状态',statusName(item.status)],['内容来源',item.source_id],['来源版本',item.source_version],
        ['记录版本',item.version],['更新时间',item.updated_at?timeText(item.updated_at):'随项目发布']]),
      el('pre',{class:'knowledge-body',text:item.body}),el('div',{class:'actions'},[
        ...(item.origin==='user'?[action('编辑知识',()=>{s.form={...item};s.message='';s.confirmation=null;render();})]:[]),
        action(item.status==='ACTIVE'?'停用知识':'恢复启用',()=>{s.confirmation={item,status:item.status==='ACTIVE'?'DISABLED':'ACTIVE'};render();}),
        ...(item.origin==='user'&&item.status!=='DELETED'?[action('删除知识',()=>{s.confirmation={item,status:'DELETED'};render();},'text')]:[])])]):null;
    const confirmation=s.confirmation?el('div',{class:'notice warning knowledge-confirm',role:'alert'},[
      el('p',{text:`确认${{DELETED:'删除（可恢复）',DISABLED:'停用',ACTIVE:'恢复启用'}[s.confirmation.status]}“${s.confirmation.item.title}”？停用或删除后不再参与后续检索。`}),
      el('div',{class:'actions'},[action('确认'+{DELETED:'删除',DISABLED:'停用',ACTIVE:'恢复'}[s.confirmation.status],()=>void setStatus(s.confirmation.item,s.confirmation.status),'primary'),
        action('取消操作',()=>{s.confirmation=null;render();})])]):null;
    root.replaceChildren(card('知识内容','内置资料与用户知识统一检索。删除可恢复；本机编辑权限不等于生产权限。',[
      el('div',{class:'knowledge-toolbar actions'},[action('新增知识',()=>{s.form={title:'',category:'养殖知识',body:''};s.selected=null;s.confirmation=null;s.message='';render();},'primary'),
        action('刷新知识',()=>void load())]),
      el('div',{class:'filters'},[field('搜索知识内容',s.q,v=>s.q=v,128),action('查询内容',()=>{s.offset=0;void load();}),
        filter('知识分类筛选',[['','全部分类'],...(s.data?.categories||[]).map(v=>[v,v])],s.category,v=>s.category=v),
        filter('知识状态',[['','全部状态'],['ACTIVE','启用'],['DISABLED','已停用'],['DELETED','已删除（可恢复）']],s.status,v=>s.status=v)]),
      el('p',{role:'status',class:'notice',text:s.message||(s.busy?'正在处理…':'')})]),
      ...(editor?[editor]:details?[details]:[]),...(confirmation?[confirmation]:[]),card('知识列表','仅启用的内容参与 AI 检索。', [list,
      ...(s.data?[el('div',{class:'actions knowledge-pagination'},[
        el('span',{text:`共 ${s.data.total} 条 · 当前 ${s.data.total?s.offset+1:0}–${Math.min(s.offset+50,s.data.total)}`}),
        ...(s.offset>0?[action('上一页',()=>{s.offset=Math.max(0,s.offset-50);void load();})]:[]),
        ...(s.offset+50<s.data.total?[action('下一页',()=>{s.offset+=50;void load();})]:[])])]:[])]),
      card('检索测试','与 AI Knowledge Tool 查询同一内容，不调用 LLM；只显示有限片段与来源。',[
        field('检索关键词',s.testQuery,v=>s.testQuery=v,512),action('测试检索',()=>void searchTest()),
        ...(s.hits?[s.hits.evidence.length?el('div',{class:'knowledge-hits'},s.hits.evidence.map(hit=>el('article',{},[
          el('strong',{text:hit.category}),el('p',{text:hit.text}),el('small',{text:`来源：${hit.source} · 版本 ${hit.source_version}`})]))):
          empty('没有合格命中','请更换关键词；停用或删除的内容不参与检索。','book')]:[]) ]));
  }
  return {mount(){if(!s.loaded&&!s.busy)void load();return root;},load,state:s};
}
