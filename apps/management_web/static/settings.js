import {el,card,button,rows,empty} from './components.js';

const settingSections=[['general','常规设置'],['models','AI 模型管理'],['credentials','API 密钥'],
  ['budgets','回答与执行预算'],['tools','Assistant Tool 授权'],['rag','RAG 检索设置']];
const settingErrors={SETTINGS_CHANGED:'配置已被修改。请重新读取后再保存。',SETTINGS_BUSY:'其他窗口正在保存，请稍后重新读取。',SETTINGS_MODE_UNAVAILABLE:'该模型或响应模式当前不可用，请检查服务器试用开关和工具授权。',
  SETTINGS_DEVICE_UNAVAILABLE:'该监测设备已不可用。',INVALID_SETTINGS:'配置格式不正确。',ENV_REVISION_CONFLICT:'密钥配置已变化，请重新读取后再操作。',
  PROCESS_ENV_READ_ONLY:'此密钥由启动环境提供，网页不能修改。',CREDENTIAL_READ_ONLY:'密钥由启动环境提供或私有存储不可用，网页不能修改。',
  INVALID_CREDENTIAL_VALUE:'密钥不能为空，不能包含换行或控制字符，最长 4096 字节。',ENV_PERMISSION_ERROR:'私有凭据目录权限不安全，未执行写入。',
  ENV_LOCK_UNAVAILABLE:'凭据正在被其他窗口修改，请稍后重新读取。',ENV_RECOVERY_REQUIRED:'凭据保存需人工恢复，请联系维护者。'};

export function createSettingsWorkspace(api,toolPolicy){
  const root=el('div',{class:'settings-center'}),notice=el('p',{role:'status','aria-live':'polite'});
  let config=null,loaded=false,selected='general',draft=null,busy=false;
  const panels=new Map(),tabs=new Map();
  const nav=el('nav',{class:'card settings-nav','aria-label':'设置分类'},settingSections.map(([id,name])=>{
    const tab=button(name,()=>show(id),'text');tabs.set(id,tab);return tab;
  }));
  const body=el('div',{class:'settings-body'});
  const reload=el('div',{class:'settings-actions'});
  function askReload(){
    if(busy)return;
    reload.replaceChildren(el('span',{text:'重新读取将放弃本页未保存输入。'}),
      button('确认重新读取',()=>{void load();resetReload();}),button('取消',resetReload,'text'));
  }
  function resetReload(){reload.replaceChildren(button('重新读取设置',askReload,'text'));}
  resetReload();
  root.append(el('div',{class:'settings-toolbar'},[notice,reload]),el('div',{class:'settings-layout'},[nav,body]));
  const error=e=>settingErrors[e?.message]||'操作未完成，请检查本机配置后重新读取。';
  function show(id){selected=id;for(const [key,panel] of panels)panel.hidden=key!==id;
    for(const [key,tab] of tabs){tab.className=`button ${key===id?'selected':'text'}`;tab.setAttribute('aria-current',key===id?'page':'false');}}
  function selectField(label,choices,value,change){return el('label',{class:'field'},[el('span',{text:label}),
    el('select',{'aria-label':label,onchange:e=>change(e.target.value)},choices.map(([id,name])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name])))]);}
  function build(){
    panels.clear();body.replaceChildren();draft={...config.preferences};
    const feedback=el('p',{role:'status'});
    const unavailableDefault=el('p',{class:'warning-text',text:'已保存的默认组合当前不可用。请检查工具授权或试用开关，不会自动启用实验功能。'});
    unavailableDefault.hidden=config.default_available;
    const edit=(key,value)=>{draft[key]=value;feedback.textContent='有未保存更改。';};
    const model=selectField('默认 AI 模型',config.models.map(m=>[m.preset_id,m.name]),draft.preset_id,v=>edit('preset_id',v));
    const general=card('常规设置','保存为下次打开页面的默认值；当前聊天和执行中的请求保持原状。',[
      el('div',{class:'settings-fields'},[model,
        selectField('默认监测设备',config.devices.map(d=>[d.id,d.name]),draft.device_id,v=>edit('device_id',v)),
        selectField('默认响应模式',[['normal','Normal'],['streaming','Streaming']],draft.transport,v=>edit('transport',v))]),
      el('label',{class:'settings-check'},[el('input',{type:'checkbox',...(draft.show_details?{checked:'checked'}:{}),
        onchange:e=>edit('show_details',e.target.checked)}),el('span',{text:'聊天默认展开运行详情'})]),
      button('保存常规设置',async()=>{
        if(busy)return;busy=true;feedback.textContent='正在保存…';
        const submitted={...draft};
        try{const next=await api.save({epoch:config.epoch,revision:config.revision,preferences:submitted},config);
          config=next;unavailableDefault.hidden=config.default_available;
          feedback.textContent=JSON.stringify(draft)===JSON.stringify(submitted)?'已保存，下次打开页面生效。':'已保存提交时的设置；当前仍有未保存更改。';}
        catch(e){feedback.textContent=error(e);}finally{busy=false;}
      },'primary'),feedback,unavailableDefault]);
    panels.set('general',general);
    panels.set('models',card('AI 模型管理','连接地址和模型身份由维护者固定；本页不发起连接测试。',[
      ...config.models.map(m=>card(m.name,`${m.provider} · ${m.kind==='local'?'本机服务':'模型服务'}`,([
        rows([['模型 ID',m.model_id],['连接地址',m.connection],['Thinking','OFF'],
          ['Tool Calling 能力',m.capabilities.tool_calling],['Streaming 协议能力',m.capabilities.streaming],
          ['Normal',m.modes.normal.can_send?'已开放（按授权工具）':'当前不可用'],
          ['Streaming',m.modes.streaming.can_send?'本地实验可用':'未开放或条件不匹配'],['连接状态','未测试；保存配置不会连接模型']]),
        button('选择为默认',()=>{edit('preset_id',m.preset_id);model.children[1].value=m.preset_id;show('general');}),
        ...(m.kind==='cloud'?[button('管理 API 密钥',()=>show('credentials'),'text')]:[])]))),
      el('p',{class:'muted',text:'添加、修改地址或禁用模型暂未开放。管理 Assistant 仅装配固定 Qwen/Ollama 预设；自定义模型尚需独立能力与工具发布验证。DeepSeek Backend 适配保留，但未接入本页可执行模型列表。'})]));
    const credentialCards=config.credentials.map(item=>{
      let current=item,working=false,clearPending=false;
      const status=el('p'),feedback=el('p',{role:'status'}),actions=el('div',{class:'settings-actions'});
      const input=el('input',{type:'password',autocomplete:'new-password',spellcheck:'false','aria-label':`${item.provider} API Key`,maxlength:4096,
        ...(!item.editable?{disabled:'disabled'}:{})});
      async function change(action){
        if(working||busy)return;working=true;busy=true;input.disabled=true;feedback.textContent='正在保存…';
        // Only this explicit handler reads the field; never localStorage, URL or a log.
        const secret=action==='remove'?null:input.value;
        input.value='';
        try{const result=await api.credential({epoch:config.epoch,provider:current.provider,action,
          revision:current.revision,secret,confirm_clear:action==='remove'},config);
          current=result.credential;feedback.textContent=action==='remove'?'密钥已清除。':'密钥已安全保存，下一次请求使用新凭据。';}
        catch(e){feedback.textContent=error(e);}finally{working=false;busy=false;clearPending=false;input.disabled=!current.editable;update();}
      }
      function update(){status.textContent=`${current.availability==='PRESENT'?'已配置':current.availability==='MISSING'?'未配置':'存储不可用'} · ${current.source==='PROCESS_ENV'?'启动环境（只读）':current.editable?'用户私有文件':'只读'}；未测试连接`;
        const save=button('保存 / 替换密钥',()=>{if(!working)void change('save');},'primary');save.disabled=!current.editable||working;
        const clear=button('清除密钥',()=>{clearPending=true;update();});clear.disabled=!current.editable||!current.exists||working;
        actions.replaceChildren(save,clear,...(clearPending?[el('span',{text:'确认清除该 Provider 的私有密钥？'}),
          button('确认清除',()=>{if(!working)void change('remove');}),button('取消',()=>{clearPending=false;update();},'text')]:[]));}
      update();
      return card(item.provider==='dashscope'?'Qwen / DashScope':'DeepSeek（保留的 Provider 配置）','仅显示状态，不回显、下载或缓存完整密钥。',[
        status,el('label',{class:'field'},[el('span',{text:'新 API Key'}),input]),actions,feedback]);
    });
    panels.set('credentials',card('API 密钥','PROCESS_ENV 优先于私有 PROJECT_ENV；环境变量由启动方管理。已启动请求保留原凭据快照。',[
      ...credentialCards,el('p',{class:'muted',text:'Ollama 无需 API Key。此入口仅供本机受控开发使用，不是生产账户权限系统。'})]));
    panels.set('budgets',card('回答与执行预算','每请求输出上限与整个对话轮次的执行上限是不同限制。',[
      ...config.models.flatMap(m=>['normal','streaming'].map(mode=>{const b=m.modes[mode];return card(`${m.name} · ${mode==='normal'?'Normal':'Streaming'}`,b.can_send?'当前有效配置':'当前不可用；不会因查看预算而开放',[
        rows([['最大输出 Tokens / 请求',b.max_output_tokens??'Provider 默认（未显式设置）'],['最大模型请求 / Turn',b.max_model_requests],
          ['Tool Calls / Rounds',`${b.max_tool_calls} / ${b.max_tool_rounds}`],['整 Turn Deadline',`${b.deadline_s} 秒`],['自动重试',b.retry]]),
        el('p',{class:'muted',text:'当前精确发布范围只批准固定输出预算，暂无其他可编辑选项。调整数值需维护者新增验证范围；本页不会改写已有资格。'})]);}))]));
    panels.set('tools',card('Assistant Tool 授权','沿用已有管理端授权；修改只影响后续请求。',[toolPolicy.mount()]));
    panels.set('rag',card('RAG 检索设置','只展示实际能力；知识内容请到“资料与知识库”管理。',[
      rows([['检索方式',config.rag.method],['Top-K',config.rag.top_k],['单 Evidence 文本上限',`${config.rag.max_evidence_chars} 字符`],['索引','启用内容的不可变快照，按内容版本更新']]),
      el('p',{class:'muted',text:'Embedding、向量/混合检索、Chunk 和索引策略尚未开放配置；本页不调用 LLM。'})]));
    for(const panel of panels.values())body.append(panel);show(selected);
  }
  async function load(){
    if(busy)return;
    notice.textContent='正在读取设置…';
    try{config=await api.read();build();notice.textContent='本机设置 · 修改不会自动调用模型。';}
    catch(e){notice.textContent=error(e);panels.clear();body.replaceChildren();
      for(const [id,name] of settingSections){const panel=card(name,'请确认服务器已启用 Assistant。',[
        ...(id==='tools'?[toolPolicy.mount()]:[empty('设置暂不可用','请检查本机服务配置。'),button('重新读取',load)])]);
        panels.set(id,panel);body.append(panel);}
      show(selected);}
  }
  return {mount(){if(!loaded){loaded=true;void load();}return root;},load,show};
}
