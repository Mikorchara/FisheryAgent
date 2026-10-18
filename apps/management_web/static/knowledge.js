import {el,card,badge,rows,table,empty} from './components.js';
import {timeText} from './view-model.js';

// Content operations only. Search controls stay mounted while results update.
export function createKnowledgeWorkspace(api){
  const root=el('div',{class:'knowledge-management'});
  const s={data:null,token:null,q:'',category:'',status:'',offset:0,selected:null,form:null,
    busy:false,loading:false,searchPending:false,loaded:false,message:'',testQuery:'',hits:null,
    confirmation:null,exportFormat:'json',exportStatus:'active'};
  const view=typeof window==='undefined'?null:window;
  const frame=typeof requestAnimationFrame==='function'?requestAnimationFrame:fn=>fn();
  let generation=0,timer=null,composing=false,originalForm=null,returnPoint=null;
  let panelControls=[],rowControls=[],rowButtons=new Map();
  let saveButton=null,retrievalButton=null;
  const baseControls=[];
  const statusName=value=>({ACTIVE:'启用',DISABLED:'已停用',DELETED:'已删除（可恢复）'}[value]||'未知');
  const describeError=error=>({KNOWLEDGE_CONFLICT:'内容已被其他窗口修改。请刷新并重新打开编辑，当前草稿已保留。',
    KNOWLEDGE_STORAGE_ERROR:'保存或读取失败，原有内容未被覆盖。请稍后重试。',
    KNOWLEDGE_NOT_CONNECTED:'知识内容服务未接入，请检查管理服务器启动方式。',
    KNOWLEDGE_ACCESS_DENIED:'页面授权已过期，请刷新知识列表后重试。',
    INVALID_KNOWLEDGE_CONTENT:'请检查标题、分类和正文；正文最多 6000 字，不能包含非法字符。',
    KNOWLEDGE_LIMIT:'知识条目已达上限（200 条，含可恢复删除），请联系维护者。',
    INVALID_KNOWLEDGE_QUERY:'检索关键词无效，请使用 1–512 字的单行文字。'}[error?.message]||'知识操作失败，请刷新后重试。');
  const action=(text,fn,tone='secondary',controls=panelControls)=>{
    const node=el('button',{class:'button '+tone,type:'button',text,onclick:fn});controls.push(node);return node;
  };
  const field=(label,value,change,maximum,multiline=false)=>{
    const control=el(multiline?'textarea':'input',{'aria-label':label,maxlength:maximum,
      ...(multiline?{rows:10,text:value}:{value}),oninput:e=>change(e.target.value)});
    return {control,node:el('label',{class:'field'},[el('span',{text:label}),control])};
  };
  const panelHost=el('div',{class:'knowledge-panel-host'});
  const confirmationHost=el('div');
  const listHost=el('div',{class:'knowledge-list-results'});
  const pagination=el('div',{class:'actions knowledge-pagination'});
  const notice=el('p',{role:'status',class:'notice'});
  const hitHost=el('div');

  function updateState(){
    for(const control of [...baseControls,...panelControls,...rowControls]){
      if(s.busy||(!s.token&&(control===saveButton||control===retrievalButton)))control.setAttribute('disabled','disabled');
      else control.removeAttribute('disabled');
    }
    notice.textContent=s.busy?'正在处理…':s.searchPending?'等待搜索…':s.loading?'正在搜索…':s.message;
    listHost.setAttribute('aria-busy',String(s.loading||s.searchPending));
  }
  function cancelTimer(){if(timer!==null){clearTimeout(timer);timer=null;}}
  function searchChanged(immediate=false){
    cancelTimer();++generation; // Invalidate an old response before the debounce elapses.
    s.offset=0;s.message='';s.loading=false;s.searchPending=!immediate;
    if(immediate)void load();else{updateState();timer=setTimeout(()=>{timer=null;void load();},300);}
  }
  async function load(){
    cancelTimer();const current=++generation;
    const filters={q:s.q,category:s.category,status:s.status,offset:s.offset};
    s.loading=true;s.searchPending=false;updateState();
    try{
      const data=await api.list(filters);
      if(current!==generation)return;
      s.data=data;s.token=data.write_token;s.loaded=true;
      updateCategories();renderList();
    }catch(e){if(current===generation){s.message=describeError(e);s.data=null;renderList();}}
    finally{if(current===generation){s.loading=false;updateState();}}
  }
  function rememberList(node,key){
    returnPoint={node,key,top:node?.getBoundingClientRect().top??0,
      x:view?.scrollX??0,y:view?.scrollY??0,left:listHost.children[0]?.scrollLeft??0};
  }
  function showPanel(focus){
    const panel=panelHost.children[0];
    frame(()=>{if(panel&&panelHost.contains(panel)){
      panel.scrollIntoView?.({block:'start',behavior:'auto'});
      (focus||panel).focus({preventScroll:true});
    }});
  }
  function restoreList(){
    const point=returnPoint;returnPoint=null;
    frame(()=>{
      const target=point&&(root.contains(point.node)?point.node:rowButtons.get(point.key));
      if(target){
        target.focus({preventScroll:true});
        const top=(view?.scrollY??0)+target.getBoundingClientRect().top-point.top;
        view?.scrollTo?.({left:point.x,top,behavior:'instant'});
        if(listHost.children[0])listHost.children[0].scrollLeft=point.left;
      }else search.control.focus();
    });
  }
  const dirty=()=>s.form&&originalForm&&['title','category','body'].some(key=>s.form[key]!==originalForm[key]);
  function guardDraft(next){
    if(s.busy)return;
    if(dirty()){
      s.confirmation={kind:'discard',next};renderConfirmation();
    }else next();
  }
  function closeDetail(){guardDraft(()=>{
    s.selected=null;s.form=null;s.confirmation=null;originalForm=null;
    renderPanel();renderConfirmation();restoreList();
  });}
  function beginEdit(item){
    s.form={...item};originalForm={...item};s.confirmation=null;s.message='';
    const focus=renderPanel();renderConfirmation();updateState();showPanel(focus);
  }
  async function open(item,editing,event){
    const trigger=event?.currentTarget;
    guardDraft(async()=>{
      rememberList(trigger,item.id+':'+(editing?'edit':'view'));
      s.busy=true;updateState();
      try{
        s.selected=await api.get(item.id);s.form=null;originalForm=null;s.confirmation=null;s.message='';
        if(editing)beginEdit(s.selected);else{renderPanel();renderConfirmation();showPanel();}
      }catch(e){s.message=describeError(e);}finally{s.busy=false;updateState();}
    });
  }
  async function save(){
    if(s.busy||!s.form||!s.token)return;
    const form={...s.form},value={title:form.title,category:form.category,body:form.body};
    s.confirmation=null;renderConfirmation();
    s.busy=true;updateState();
    try{
      s.selected=form.id?await api.edit(form.id,{...value,version:form.version},s.token):await api.create(value,s.token);
      s.form=null;originalForm=null;s.message='知识已保存，后续检索使用新版本。';s.hits=null;
      renderPanel();renderHits();await load();showPanel();
    }catch(e){s.message=describeError(e);}finally{s.busy=false;updateState();}
  }
  async function setStatus(item,status){
    if(s.busy||!s.token)return;
    s.confirmation=null;renderConfirmation();s.busy=true;updateState();
    try{
      s.selected=await api.status(item.id,{version:item.version,status},s.token);s.hits=null;
      s.message=`知识状态：${statusName(status)}。`;renderPanel();renderHits();await load();
    }catch(e){s.message=describeError(e);}finally{s.busy=false;updateState();}
  }
  function renderConfirmation(){
    const confirmation=s.confirmation;
    if(!confirmation){confirmationHost.replaceChildren();return;}
    const discard=confirmation.kind==='discard';
    const label={DELETED:'删除',DISABLED:'停用',ACTIVE:'恢复'}[confirmation.status];
    const confirm=el('button',{class:'button primary',type:'button',text:discard?'放弃修改':'确认'+label,
      onclick:()=>{
        if(s.busy)return;
        if(discard){s.form=null;originalForm=null;s.confirmation=null;renderPanel();renderConfirmation();confirmation.next();}
        else void setStatus(confirmation.item,confirmation.status);
      }});
    const cancel=el('button',{class:'button secondary',type:'button',text:discard?'继续编辑':'取消操作',onclick:()=>{
      s.confirmation=null;renderConfirmation();
      if(discard)showPanel();else panelHost.children[0]?.focus({preventScroll:true});
    }});
    const message=discard?'有未保存的修改，是否放弃编辑？不会自动保存。':
      `确认${label}${confirmation.status==='DELETED'?'（可恢复）':''}“${confirmation.item.title}”？停用或删除后不再参与后续检索。`;
    const panel=el('div',{class:'notice warning knowledge-confirm',role:'alert'},[
      el('p',{text:message}),el('div',{class:'actions'},[confirm,cancel])]);
    confirmationHost.replaceChildren(panel);
    frame(()=>{panel.scrollIntoView?.({block:'nearest'});confirm.focus({preventScroll:true});});
  }
  function renderPanel(){
    panelControls=[];saveButton=null;let panel,focus;
    if(s.form){
      const title=field('知识标题',s.form.title,v=>s.form.title=v,120);
      const category=field('知识分类',s.form.category,v=>s.form.category=v,40);
      const body=field('知识正文',s.form.body,v=>s.form.body=v,6000,true);
      panelControls.push(title.control,category.control,body.control);focus=title.control;
      panel=card(s.form.id?'编辑知识':'新增知识','正文作为不可信背景资料，不会成为系统指令。',[
        title.node,category.node,body.node,el('div',{class:'actions'},[
          saveButton=action('保存知识',()=>void save(),'primary'),action('取消编辑',()=>guardDraft(()=>{
            s.form=null;originalForm=null;s.confirmation=null;renderPanel();renderConfirmation();
            if(s.selected)showPanel();else restoreList();
          }))])]);
    }else if(s.selected){
      const item=s.selected;
      panel=card(item.title,item.origin==='builtin'?'内置导入 · 修改不回写原始文件':'用户创建的知识',[
        rows([['分类',item.category],['状态',statusName(item.status)],['内容来源',item.source_id],['来源版本',item.source_version],
          ['原始来源',item.original_source_id||item.source_id],['原始来源版本',item.original_source_version||item.source_version],
          ['记录版本',item.version],['更新时间',item.updated_at?timeText(item.updated_at):'随项目发布']]),
        el('pre',{class:'knowledge-body',text:item.body}),el('div',{class:'actions'},[
          action('编辑知识',()=>beginEdit(item)),
          action(item.status==='ACTIVE'?'停用知识':'恢复启用',()=>{
            s.confirmation={item,status:item.status==='ACTIVE'?'DISABLED':'ACTIVE'};renderConfirmation();}),
          ...(item.status!=='DELETED'?[action('删除知识',()=>{s.confirmation={item,status:'DELETED'};renderConfirmation();},'text')]:[])]),
        el('div',{class:'knowledge-detail-footer'},[action('确定',closeDetail,'primary')])]);
    }
    if(panel){panel.setAttribute('tabindex','-1');panel.setAttribute('aria-label',s.form?'知识编辑':'知识详情');}
    panelHost.replaceChildren(...(panel?[panel]:[]));updateState();return focus;
  }
  function renderList(){
    const left=listHost.children[0]?.scrollLeft??0;rowControls=[];rowButtons=new Map();
    const rowAction=(item,editing,title=false)=>{
      const node=action(title?item.title:editing?'编辑':'查看',e=>void open(item,editing,e),'text',rowControls);
      if(title)node.className='knowledge-title';
      else rowButtons.set(item.id+':'+(editing?'edit':'view'),node);
      return node;
    };
    const list=s.data?table(['标题','分类','来源','状态','更新时间','操作'],s.data.items,item=>[
      rowAction(item,false,true),item.category,item.origin==='builtin'?'内置导入':'用户创建',
      badge(statusName(item.status),item.status==='ACTIVE'?'success':'neutral'),
      item.updated_at?timeText(item.updated_at):'随项目发布',
      el('div',{class:'knowledge-row-actions'},[rowAction(item,false),rowAction(item,true)])]):
      empty(s.loading?'正在加载知识':'知识列表暂不可用','请刷新重试；不会显示假知识内容。','book');
    listHost.replaceChildren(list);list.scrollLeft=left;
    pagination.replaceChildren(...(s.data?[
      el('span',{text:`共 ${s.data.total} 条 · 当前 ${s.data.total?s.offset+1:0}–${Math.min(s.offset+50,s.data.total)}`}),
      ...(s.offset>0?[action('上一页',()=>{s.offset=Math.max(0,s.offset-50);void load();},'secondary',rowControls)]:[]),
      ...(s.offset+50<s.data.total?[action('下一页',()=>{s.offset+=50;void load();},'secondary',rowControls)]:[])]:[]));
    updateState();
  }
  async function searchTest(){
    if(s.busy||!s.token)return;s.busy=true;s.hits=null;renderHits();updateState();
    try{s.hits=await api.search({query:s.testQuery},s.token);s.message='检索完成，未调用模型。';renderHits();}
    catch(e){s.message=describeError(e);}finally{s.busy=false;updateState();}
  }
  function renderHits(){
    hitHost.replaceChildren(...(s.hits?[s.hits.evidence.length?el('div',{class:'knowledge-hits'},s.hits.evidence.map(hit=>el('article',{},[
      el('strong',{text:hit.category}),el('p',{text:hit.text}),el('small',{text:`来源：${hit.source} · 版本 ${hit.source_version}`})]))):
      empty('没有合格命中','请更换关键词；停用或删除的内容不参与检索。','book')]:[]));
  }
  function selectField(label,choices,value,change){
    const control=el('select',{'aria-label':label,onchange:e=>change(e.target.value)},
      choices.map(([id,name])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name])));
    return {control,node:el('label',{class:'field'},[el('span',{text:label}),control])};
  }
  const search=field('搜索知识内容',s.q,value=>{s.q=value;if(!composing)searchChanged(value==='');},128);
  search.control.setAttribute('type','search');
  search.control.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.isComposing&&!composing){e.preventDefault();searchChanged(true);}});
  search.control.addEventListener('compositionstart',()=>{composing=true;cancelTimer();++generation;});
  search.control.addEventListener('compositionend',e=>{composing=false;s.q=e.target.value;searchChanged(s.q==='');});
  const categories=selectField('知识分类筛选',[['','全部分类']],s.category,value=>{s.category=value;searchChanged(true);});
  const statuses=selectField('知识状态',[['','全部状态'],['ACTIVE','启用'],['DISABLED','已停用'],['DELETED','已删除（可恢复）']],
    s.status,value=>{s.status=value;searchChanged(true);});
  function updateCategories(){
    const values=[...new Set([...(s.data?.categories||[]),...(s.category?[s.category]:[])])];
    categories.control.replaceChildren(...[['','全部分类'],...values.map(v=>[v,v])].map(([id,name])=>
      el('option',{value:id,...(id===s.category?{selected:'selected'}:{})},[name])));
  }
  const download=el('a',{class:'button primary',href:api.exportUrl(s.exportFormat,s.exportStatus),download:'',text:'下载知识库',onclick:()=>{exportMenu.open=false;}});
  const exportChoice=(label,choices,key)=>selectField(label,choices,s[key],value=>{
    s[key]=value;download.setAttribute('href',api.exportUrl(s.exportFormat,s.exportStatus));});
  const exportSummary=el('summary',{class:'button secondary',text:'导出知识库'});
  const exportMenu=el('details',{class:'knowledge-export'},[exportSummary,
    el('div',{class:'knowledge-export-menu',role:'group','aria-label':'知识导出选项'},[
      exportChoice('导出格式',[['json','JSON'],['markdown','Markdown']],'exportFormat').node,
      exportChoice('导出范围',[['active','当前启用知识'],['all','全部知识（含停用和删除）']],'exportStatus').node,download])]);
  root.addEventListener('click',e=>{if(!exportMenu.contains(e.target))exportMenu.open=false;});
  root.addEventListener('keydown',e=>{if(e.key==='Escape'&&exportMenu.open){exportMenu.open=false;exportSummary.focus({preventScroll:true});}});
  const testQuery=field('检索关键词',s.testQuery,value=>s.testQuery=value,512);
  const advanced=el('details',{class:'card knowledge-advanced'},[
    el('summary',{text:'高级功能 · 检索测试'}),
    el('p',{text:'与 AI Knowledge Tool 查询同一内容，不调用 LLM；只显示有限片段与来源。'}),
    testQuery.node,retrievalButton=action('测试检索',()=>void searchTest(),'secondary',baseControls),hitHost]);
  root.append(card('知识内容','内置资料与用户知识统一检索。删除可恢复；本机编辑权限不等于生产权限。',[
    el('div',{class:'knowledge-toolbar actions'},[
      action('新增知识',e=>{
        const trigger=e.currentTarget;
        guardDraft(()=>{rememberList(trigger,null);s.selected=null;beginEdit({title:'',category:'养殖知识',body:''});});
      },'primary',baseControls),action('刷新知识',()=>void load(),'secondary',baseControls)]),
    el('div',{class:'knowledge-filters'},[search.node,categories.node,statuses.node]),notice],exportMenu),
    panelHost,confirmationHost,card('知识列表','仅启用的内容参与 AI 检索。',[listHost,pagination]),advanced);
  renderList();updateState();
  return {mount(){if(!s.loaded&&!s.loading&&!s.searchPending)void load();return root;},load,state:s};
}
