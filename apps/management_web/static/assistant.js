import {el,card,badge,button,rows,empty} from './components.js';
import {timeText} from './view-model.js';

// Page Session only. No Provider logic, raw Tool data, or persistent browser storage.
export function historyForRequest(turns){
  const history=turns.slice(-64).map(({user,assistant,completed_at})=>({user,assistant,completed_at}));
  while(history.length&&new TextEncoder().encode(JSON.stringify(history)).length>16*1024)history.shift();
  return history;
}

export function createAssistantWorkspace(api,options={}){
  const confirm=options.confirm||((text)=>window.confirm(text));
  const s={device:'',devices:[],preset:'',config:null,turns:[],entries:[],draft:'',pending:false,
    confirmed:false,control:null,stopRequested:false,cancellation:null,cancelUnknown:false,stopRejected:false,
    status:'就绪',activity:null,trimmed:false,generation:0,turnSequence:0};
  const root=el('div',{class:'management-assistant'});
  let composer,statusNode,activityNode,sendButton,stopButton;
  const safeError=e=>/^[A-Z][A-Z0-9_]{0,63}$/.test(e?.message||'')?e.message:'AI_SERVICE_UNAVAILABLE';
  const preset=()=>s.config?.presets.find(p=>p.preset_id===s.preset);
  function showActivity(target,activity){
    const steps=activity?.steps||[];
    const tools=steps.filter(step=>step.kind==='tool');
    target.replaceChildren(...(tools.length?tools.map(tool=>el('details',{class:'data-details'},[
      el('summary',{text:`${tool.display_name||tool.tool_name||'Tool'} · ${tool.state} · ${tool.result_status||'—'}`}),
      rows([['实际执行',tool.handler_started?'是':'否'],['耗时',tool.duration_ms===null?'—':`${tool.duration_ms} ms`],
        ['质量',tool.quality||'—'],['新鲜度',tool.freshness||'—'],['观测时间',timeText(tool.observed_at)],
        ['评估时间',timeText(tool.evaluated_at)]])])):[el('p',{class:'muted',text:s.pending?'尚未执行 Tool':'未调用 Tool'})]));
    target.append(el('details',{class:'data-details'},[el('summary',{text:'本次运行详情'}),
      ...steps.map(step=>el('div',{},[
        el('p',{class:'muted',text:step.kind==='model'?`Request #${step.request_index} · ${step.state} · ${step.outcome||''}`:
          `${step.tool_name||'Tool'} · ${step.state}`}),
        ...(step.argument_diagnostic?[rows([['参数拒绝原因',step.argument_diagnostic.reason],
          ['校验阶段',step.argument_diagnostic.stage],['参数字节数（有界）',step.argument_diagnostic.argument_bytes??'—'],
          ['成员数（有界）',step.argument_diagnostic.object_member_count??'—']])]:[])])),
      rows([['请求数',activity?.counts?.model_requests_started??0],['实际 Tool',activity?.counts?.tools_executed??0],
        ['Tokens',activity?.aggregate_usage?.total_tokens??'—'],['总耗时',activity?.total_latency_ms===null||activity?.total_latency_ms===undefined?'—':`${activity.total_latency_ms} ms`]])]));
  }
  function updateProgress(){
    if(statusNode)statusNode.textContent=s.status;
    if(activityNode)showActivity(activityNode,s.activity);
  }
  function render(){
    const model=preset();
    const selectField=(label,choices,value,change)=>el('label',{class:'field'},[el('span',{text:label}),
      el('select',{...(s.pending?{disabled:'disabled'}:{}),onchange:e=>change(e.target.value)},choices.map(([id,name])=>
        el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name])))]);
    const messages=el('div',{class:'management-messages','aria-live':'polite'},s.entries.map(entry=>el('article',
      {class:`management-message ${entry.kind}`},[el('strong',{text:entry.kind==='user'?'你':entry.kind==='assistant'?'渔业助手':'运行状态'}),
        el('p',{text:entry.text}),...(entry.activity?[el('details',{class:'data-details'},[
          el('summary',{text:entry.activity.counts.tools_executed?'已使用水质查询 Tool':'未调用 Tool'}),
          (()=>{const node=el('div');showActivity(node,entry.activity);return node;})()])]:[])])));
    if(!s.entries.length)messages.append(empty('让问题有依据，让建议可追溯。','可询问当前水质，也可直接讨论溶氧概念。当前观测来自模拟器；查询不等于采样。','spark'));
    composer=el('textarea',{rows:3,'aria-label':'消息',placeholder:'输入问题，Ctrl + Enter 发送',text:s.draft,
      ...(s.pending?{disabled:'disabled'}:{}),oninput:e=>{s.draft=e.target.value;},onkeydown:e=>{
        if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();void send();}}});
    const network=el('input',{type:'checkbox',...(s.confirmed?{checked:'checked'}:{}),...(s.pending?{disabled:'disabled'}:{}),
      onchange:e=>{s.confirmed=e.target.checked;}});
    sendButton=el('button',{class:'button primary',text:'发送',...(!s.config||s.pending?{disabled:'disabled'}:{}),onclick:()=>void send()});
    stopButton=el('button',{class:'button secondary',text:'Stop',...(!s.pending?{disabled:'disabled'}:{}),onclick:()=>void stop()});
    statusNode=el('p',{class:'muted',role:'status',text:s.status});activityNode=el('div');
    root.replaceChildren(el('div',{class:'assistant-layout'},[
      el('section',{class:'card chat-shell'},[
        el('div',{class:'chat-top assistant-controls'},[
          selectField('模型',(s.config?.presets||[]).map(p=>[p.preset_id,p.display_name]),s.preset,changePreset),
          selectField('监测设备',s.devices.map(d=>[d.id,d.name]),s.device,changeDevice),badge('Thinking OFF · Normal','neutral'),
          el('button',{class:'button text',text:'清空对话',...(s.pending?{disabled:'disabled'}:{}),onclick:clear})]),messages,
        el('div',{class:'chat-composer'},[composer,
          el('label',{class:'assistant-confirm'},[network,el('span',{text:model?.runtime_type==='local'?
            'LOCAL MODEL REQUEST · 本次最多 2 次本地模型请求':'REAL NETWORK REQUEST · 本次最多 2 次模型请求，Cloud 可能产生费用'})]),
          el('div',{class:'composer-foot'},[el('span',{text:'仅完整成功回答进入会话；刷新页面清空。'}),sendButton,stopButton]),statusNode,
          ...(s.trimmed?[el('p',{class:'muted',text:'较早对话未发送给模型。页面记录不代表模型记住全部历史。'})]:[])])]),
      el('div',{class:'side-stack'},[card('本次运行','冻结设备上下文 · 1 Tool / 1 Round / 2 Requests',[activityNode]),
        card('来源与权限','共用 Monitoring SQLite 与领域规则。',[rows([['本轮设备',s.device],['可用 Tool',s.config?.tools.join('、')||'无（受 Tool Policy 限制）'],
          ['数据来源','Simulator · 非真实传感器'],['规则状态','PROTOTYPE']]),el('p',{class:'muted',text:'缺失、无效、过期或离线数据不表示环境正常。评分、知识检索和 Streaming 本阶段未接入。'})])]) ]));
    updateProgress();
  }
  async function load(){
    const version=++s.generation,previousEpoch=s.config?.epoch;s.config=null;s.confirmed=false;render();
    try{
      const config=await api.bootstrap(s.device);
      if(version!==s.generation)return;
      if(previousEpoch&&previousEpoch!==config.epoch){s.turns=[];s.entries=[];s.activity=null;}
      s.config=config;
      if(!config.presets.some(p=>p.preset_id===s.preset))s.preset=config.default_preset_id;
      s.status='就绪';
    }catch(e){if(version!==s.generation)return;s.status=safeError(e);}
    render();
  }
  function reset(){s.turns=[];s.entries=[];s.activity=null;s.trimmed=false;s.confirmed=false;}
  function clear(){if(s.pending)return;if(s.turns.length&&!confirm('清空 Assistant 对话？监测数据保持不变。'))return;reset();s.status='对话已清空';render();}
  function changePreset(id){
    if(s.pending)return;
    if(s.turns.length&&!confirm('切换模型将开始新的 Assistant 会话。')){render();return;}
    reset();s.preset=id;s.status='就绪';render();
  }
  function changeDevice(id){
    if(s.pending)return;
    if(s.turns.length&&!confirm('切换监测设备将开始新的 Assistant 会话。')){render();return;}
    reset();s.device=id;options.onDevice?.(id);void load();
  }
  async function send(){
    const question=s.draft.trim();
    if(s.pending||!question||!s.config)return;
    if(!s.confirmed){s.status='请先确认本次模型请求。';updateProgress();return;}
    const config=s.config,model=preset(),history=historyForRequest(s.turns);
    const captured={device_id:s.device,preset_id:s.preset,revision:model.revision,epoch:config.epoch,question,history};
    s.pending=true;s.stopRequested=false;s.cancellation=null;s.cancelUnknown=false;s.stopRejected=false;
    s.control=null;s.activity=null;s.status='Preparing';
    const sequence=++s.turnSequence;
    s.entries.push({kind:'user',text:question});render();
    let timer;
    try{
      s.control=await api.prepare(config);
      if(s.stopRequested){await api.cancel(s.control,config);throw new Error('USER_CANCELLED');}
      const control=s.control;
      timer=setInterval(async()=>{
        if(!s.pending||sequence!==s.turnSequence)return;
        try{const info=await api.state(control,config);if(!s.pending||sequence!==s.turnSequence)return;
          if(info.activity&&(info.activity.revision??0)>=(s.activity?.revision??0))s.activity=info.activity;
          s.status=s.stopRequested?'取消中…':info.phase||info.state;updateProgress();}catch(_){/* Final POST remains authoritative. */}
      },500);
      const response=await api.send({...captured,...s.control,confirm_network:true},config);
      if(s.cancellation)await s.cancellation;
      const result=response.result;s.activity=result.activity||s.activity;
      if(!result.successful_turn)throw new Error(result.error_code||'AI_SERVICE_UNAVAILABLE');
      if(s.stopRequested)throw new Error(s.cancelUnknown?'CANCELLATION_STATUS_UNKNOWN':'USER_CANCELLED');
      s.turns.push({user:question,assistant:result.final_text,completed_at:result.completed_at});
      s.entries.push({kind:'assistant',text:result.final_text,activity:result.activity});s.draft='';
      s.status=s.stopRejected?'Completed · 已在 Stop 前完成':'Completed';
      s.trimmed=result.history_trimmed||history.length<s.turns.length-1;
    }catch(e){
      if(s.control&&!s.stopRequested&&!s.cancellation)try{await api.cancel(s.control,config);}catch(_){/* Bounded registry TTL handles an unreachable control API. */}
      const code=safeError(e);s.status=code;
      s.entries.push({kind:'status',text:code==='USER_CANCELLED'?'USER_CANCELLED · 未提交半成品。远端计算/计费是否停止：UNKNOWN':
        code==='INVALID_TOOL_ARGUMENTS'?'INVALID_TOOL_ARGUMENTS · 工具参数未通过校验，被拒绝的 Tool 未执行；可展开本次运行详情查看原因。':code});
      if(['ASSISTANT_SESSION_EXPIRED','AI_ACCESS_DENIED'].includes(code)){
        reset();await load();s.status=code==='ASSISTANT_SESSION_EXPIRED'?
          'Assistant 后端已重启，请重新发送当前问题。':'Assistant 会话已失效，请重新发送当前问题。';
      }else if(code==='ASSISTANT_EXECUTION_PROFILE_CHANGED'){
        await load();s.status='运行配置或权限已变化，请重新确认。';
      }
    }finally{if(timer)clearInterval(timer);s.pending=false;s.confirmed=false;s.control=null;render();}
  }
  async function stop(){
    if(!s.pending||s.stopRequested)return;s.stopRequested=true;s.status='取消中…';updateProgress();
    if(s.control){
      s.cancellation=api.cancel(s.control,s.config).then(info=>{
        if(['COMPLETED','FAILED'].includes(info.state)){s.stopRequested=false;s.stopRejected=true;}
      }).catch(()=>{s.cancelUnknown=true;s.status='取消状态未知，请等待本次请求结束。';updateProgress();});
      await s.cancellation;
    }
  }
  return {mount(devices,device){s.devices=devices;
      if(!s.device){s.device=device;void load();}
      else if(device!==s.device&&!s.pending){reset();s.device=device;void load();}
      return root;},send,stop,clear,changePreset,changeDevice,
    state:s};
}
