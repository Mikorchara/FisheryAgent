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
  const s={device:'',devices:[],preset:'',transport:'normal',nextAction:'',config:null,turns:[],entries:[],draft:'',pending:false,
    confirmed:false,control:null,stopRequested:false,cancellation:null,cancelUnknown:false,stopRejected:false,
    status:'就绪',activity:null,lastRun:null,trimmed:false,generation:0,turnSequence:0,followLatest:true};
  const root=el('div',{class:'management-assistant'});
  let composer,statusNode,activityNode,sendButton,stopButton,run=null,confirmationKey='';
  const safeError=e=>/^[A-Z][A-Z0-9_]{0,63}$/.test(e?.message||'')?e.message:'AI_SERVICE_UNAVAILABLE';
  const preset=()=>s.config?.presets.find(p=>p.preset_id===s.preset);
  const historical=()=>s.nextAction==='history_query';
  const profile=()=>{
    if(!historical())return s.transport==='streaming'?preset()?.streaming:preset()?.execution;
    const h=s.config?.history_query;
    return h&&h.preset_id===s.preset&&s.transport==='normal'?h:
      {...h,can_send:false,mode_reason:'HISTORY_CANDIDATE_SCOPE_MISMATCH'};
  };
  const blocked=()=>!s.config||((s.transport==='streaming'||historical())?
    profile()?.can_send!==true:profile()?.can_send===false);
  const binding=()=>JSON.stringify([s.config?.epoch,s.preset,s.device,s.transport,s.nextAction,
    profile()?.revision||preset()?.revision,profile()?.max_output_tokens,profile()?.max_model_requests,
    s.config?.tools,blocked()]);
  function unavailable(){
    if(!s.config)return '正在读取可用能力，请稍候。';
    if(historical()){
      if(s.transport!=='normal')return '历史查询暂不支持 Streaming，请主动切换到 Normal，或取消本次历史查询。';
      if(s.preset!==s.config?.history_query?.preset_id)return '历史查询仅支持 Qwen 3.8 Flash，请选择该模型，或取消本次历史查询。';
      return {HISTORY_TRIAL_DISABLED:'历史查询尚未在服务器启用。请使用 --assistant-history-trial 重启，再刷新页面。',
        HISTORY_TOOL_NOT_AUTHORIZED:'历史查询尚未授权。请到系统设置勾选历史水质并保存，再返回确认。',
        HISTORY_CANDIDATE_NOT_RELEASED:'历史查询仍待试用批准，当前不能发送。',
        HISTORY_CANDIDATE_SCOPE_MISMATCH:'历史查询运行配置不匹配，请联系维护者检查配置。'}[profile()?.mode_reason]||'历史查询当前不可用，请刷新可用状态。';
    }
    if(s.transport==='streaming')return {flag_disabled:'Streaming 尚未在服务器启用，请启用本地试用参数后刷新，或主动切回 Normal。',
      candidate:'此模型的 Streaming 尚未开放，请主动切回 Normal。',
      scope_not_published:'Streaming 仅开放 Qwen 与当前水质、项目知识两工具。请检查设置中的授权组合，或主动切回 Normal。',
      runtime_constraints_mismatch:'Streaming 执行配置不匹配，请联系维护者。'}[profile()?.mode_reason]||'当前模型或工具组合不支持 Streaming。请检查授权，或主动切回 Normal。';
    return '当前模型与工具授权组合不匹配，请检查系统设置并刷新。不会自动切换执行方式。';
  }
  // Retain the transcript and each message node. Preview -> Final updates in place.
  const messages=el('div',{class:'management-messages',role:'log','aria-label':'聊天记录','aria-live':'polite',tabindex:0});
  const navigation=el('nav',{class:'question-navigation','aria-label':'问题导航'});
  const latest=el('button',{class:'button text latest-message',text:'回到最新',onclick:()=>{s.followLatest=true;follow();}});
  const lane=el('div',{class:'chat-lane'},[messages,navigation]);
  const messageNodes=new Map(),markers=new Map();
  const bottom=()=>Math.max(0,messages.scrollHeight-messages.clientHeight);
  function follow(){
    if(s.followLatest)messages.scrollTop=bottom();
    latest.hidden=s.followLatest;
  }
  messages.addEventListener('scroll',()=>{s.followLatest=bottom()-messages.scrollTop<=40;latest.hidden=s.followLatest;});
  function jump(entry){
    const node=messageNodes.get(entry)?.node;if(!node)return;
    s.followLatest=false;
    messages.scrollTop+=node.getBoundingClientRect().top-messages.getBoundingClientRect().top-12;
    node.focus({preventScroll:true});latest.hidden=false;
  }
  function syncMessages(){
    const previous=messages.scrollTop;
    for(const [entry,value] of messageNodes)if(!s.entries.includes(entry)){value.node.remove();messageNodes.delete(entry);}
    if(!s.entries.length){messages.replaceChildren(empty('让问题有依据，让建议可追溯。',historical()?
      '下一条将查询过去10、30或60分钟水质及覆盖限制。取消历史查询可恢复普通提问。':
      '可询问当前水质，也可直接讨论溶氧概念。查询不等于采样。','spark'));}
    else if(!messageNodes.size)messages.replaceChildren();
    for(const entry of s.entries){
      let view=messageNodes.get(entry);
      if(!view){
        const title=el('strong'),body=el('p'),details=el('div');
        const node=el('article',{tabindex:-1},[title,body,details]);
        view={node,title,body,details,activity:null};messageNodes.set(entry,view);messages.append(node);
      }
      view.node.className=`management-message ${entry.kind}`;
      view.node.setAttribute('aria-busy',entry.kind==='pending'?'true':'false');
      view.title.textContent=entry.kind==='user'?'你':entry.kind==='assistant'?'渔业助手':entry.kind==='pending'?'渔业助手 · 临时预览（未提交）':'运行状态';
      const text=entry.text||(entry.kind==='pending'?'正在准备回答…':'');
      if(view.body.textContent!==text)view.body.textContent=text;
      if(view.activity!==entry.activity){
        view.activity=entry.activity;view.details.replaceChildren();
        if(entry.activity){const content=el('div');showActivity(content,entry.activity);
          view.details.append(el('details',{class:'data-details'},[
            el('summary',{text:entry.activity.counts.tools_executed?`使用了 ${entry.activity.counts.tools_executed} 个 Tool`:'未调用 Tool'}),content]));}
      }
    }
    const questions=s.entries.filter(entry=>entry.kind==='user');
    for(const [entry,node] of markers)if(!questions.includes(entry)){node.remove();markers.delete(entry);}
    questions.forEach((entry,i)=>{
      if(markers.has(entry))return;
      const preview=entry.text.replace(/\s+/g,' ').slice(0,72);
      const node=el('button',{class:'question-marker',text:String(i+1),title:preview,
        'aria-label':`问题 ${i+1}：${preview}`,onclick:()=>jump(entry),onkeydown:e=>{
          const current=s.entries.filter(item=>item.kind==='user');
          const keys={ArrowDown:i+1,ArrowUp:i-1,Home:0,End:current.length-1};
          if(e.key in keys){e.preventDefault();const target=current[Math.max(0,Math.min(current.length-1,keys[e.key]))];
            jump(target);const marker=markers.get(target);marker?.focus({preventScroll:true});
            const rect=marker?.getBoundingClientRect(),bounds=navigation.getBoundingClientRect();
            if(rect&&(rect.top<bounds.top||rect.bottom>bounds.bottom))navigation.scrollTop+=rect.top-bounds.top;}
        }});
      markers.set(entry,node);navigation.append(node);
    });
    messages.scrollTop=previous;follow();
  }
  function showActivity(target,activity){
    const expanded=new Set(Array.from(target.children).filter(node=>node.open).map(node=>node.getAttribute('data-activity-key')));
    const steps=activity?.steps||[];
    const tools=steps.filter(step=>step.kind==='tool');
    target.replaceChildren(...(tools.length?tools.map(tool=>el('details',{class:'data-details'},[
      el('summary',{text:`${tool.display_name||tool.tool_name||'Tool'} · ${tool.state} · ${tool.result_status||'—'}`}),
      rows([['实际执行',tool.handler_started?'是':'否'],['耗时',tool.duration_ms===null?'—':`${tool.duration_ms} ms`],
        ...(tool.tool_name==='search_fishery_knowledge'?
          [['来源类型','项目背景知识 · 不代表当前观测或疾病确诊'],['命中条数',tool.evidence_count??'—'],
            ['检索状态',tool.result_status==='NO_MATCH'?'检索完成 · 无合格命中':tool.result_status==='OK'?'检索完成':'未完成检索']]:
          tool.tool_name==='get_current_water_quality'?
          [['质量',tool.quality||'—'],['新鲜度',tool.freshness||'—'],['观测时间',timeText(tool.observed_at)],
            ['评估时间',timeText(tool.evaluated_at)]]:tool.tool_name==='get_water_quality_history'?
          [['来源类型','历史窗口统计 · 不是当前观测'],['查询状态',tool.result_status==='NO_DATA'?'查询完成 · 无匹配历史':
            tool.result_status==='PARTIAL'?'查询完成 · 数据覆盖或质量有限':tool.result_status==='OK'?'查询完成 · 可靠历史':'未完成查询']]:[])])])):[el('p',{class:'muted',text:s.pending?'尚未执行 Tool':'未调用 Tool'})]));
    target.append(el('details',{class:'data-details'},[el('summary',{text:'本次运行详情'}),
      ...steps.map(step=>el('div',{},[
        el('p',{class:'muted',text:step.kind==='model'?`Request #${step.request_index} · ${step.state} · ${step.outcome||''}`:
          `${step.tool_name||'Tool'} · ${step.state}`}),
        ...(step.argument_diagnostic?[rows([['参数拒绝原因',step.argument_diagnostic.reason],
          ['校验阶段',step.argument_diagnostic.stage],['参数字节数（有界）',step.argument_diagnostic.argument_bytes??'—'],
          ['成员数（有界）',step.argument_diagnostic.object_member_count??'—']])]:[])])),
      rows([['请求数',activity?.counts?.model_requests_started??0],['实际 Tool',activity?.counts?.tools_executed??0],
        ['Tokens',activity?.aggregate_usage?.total_tokens??'—'],['总耗时',activity?.total_latency_ms===null||activity?.total_latency_ms===undefined?'—':`${activity.total_latency_ms} ms`]])]));
    Array.from(target.children).forEach((node,i)=>{
      const key=i<tools.length?`tool-${i}-${tools[i].tool_name}`:'run-details';
      node.setAttribute('data-activity-key',key);if(expanded.has(key))node.open=true;
    });
  }
  function updateProgress(){
    if(statusNode)statusNode.textContent=!s.pending&&blocked()?unavailable():s.status;
    if(activityNode)showActivity(activityNode,s.activity);
  }
  function render(){
    const scrollPosition=messages.scrollTop;
    const model=preset();
    const streaming=s.transport==='streaming',execution=profile();
    const maxRequests=execution?.max_model_requests??s.config?.max_model_requests??2;
    const cannotSend=blocked(),key=binding();
    if(cannotSend||key!==confirmationKey)s.confirmed=false;
    confirmationKey=key;
    const multi=execution?.mode==='BOUNDED_MULTI_ROUND';
    const actual=s.lastRun||{transport:s.transport,multi,maxRequests,tokens:execution?.max_output_tokens,historical:historical()};
    const selectField=(label,choices,value,change,disabled=false)=>el('label',{class:'field'},[el('span',{text:label}),
      el('select',{...(s.pending||disabled?{disabled:'disabled'}:{}),onchange:e=>change(e.target.value)},choices.map(([id,name])=>
        el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name])))]);
    composer=el('textarea',{rows:3,'aria-label':'消息',placeholder:'输入问题，Ctrl + Enter 发送',text:s.draft,
      ...(s.pending?{disabled:'disabled'}:{}),oninput:e=>{s.draft=e.target.value;},onkeydown:e=>{
        if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();void send();}}});
    const network=el('input',{type:'checkbox',...(s.confirmed?{checked:'checked'}:{}),...(s.pending||cannotSend?{disabled:'disabled'}:{}),
      onchange:e=>{s.confirmed=!blocked()&&e.target.checked;confirmationKey=binding();render();}});
    sendButton=el('button',{class:'button primary',text:'发送',...(!s.confirmed||s.pending||cannotSend?{disabled:'disabled'}:{}),onclick:()=>void send()});
    stopButton=el('button',{class:'button secondary',text:'Stop',...(!s.pending?{disabled:'disabled'}:{}),onclick:()=>void stop()});
    statusNode=el('p',{class:'muted',role:'status',text:cannotSend?unavailable():s.status});activityNode=el('div');
    root.replaceChildren(el('div',{class:'assistant-layout'},[
      el('section',{class:'card chat-shell'},[
        el('div',{class:'chat-top assistant-controls'},[
          selectField('模型',(s.config?.presets||[]).map(p=>[p.preset_id,p.display_name]),s.preset,changePreset),
          selectField('监测设备',s.devices.map(d=>[d.id,d.name]),s.device,changeDevice),
          selectField('响应模式',[['normal','Normal'],['streaming','Streaming']],s.transport,changeTransport),
          badge(`Thinking OFF · ${streaming?'Streaming':'Normal'}`,'neutral'),
          badge(historical()?`历史查询 · 本地实验${cannotSend?' · 不可用':''}`:
            streaming?`Streaming · 本地实验${cannotSend?' · 不可用':''}`:
            cannotSend?'当前配置不可用':multi?'多轮 · 本地实验':'单轮','neutral'),
          el('button',{class:'button text',text:'清空对话',...(s.pending?{disabled:'disabled'}:{}),onclick:clear})]),lane,
        el('div',{class:'chat-composer'},[
          el('div',{class:'actions'},[el('button',{class:'button secondary',text:historical()?'取消历史查询':'历史查询',
            ...(s.pending?{disabled:'disabled'}:{}),onclick:()=>historyQuery(!historical())}),
            el('button',{class:'button text',text:'刷新可用状态',...(s.pending?{disabled:'disabled'}:{}),onclick:()=>void load()})]),
          el('p',{class:'muted',text:historical()?'下一条：历史水质查询（10 / 30 / 60 分钟）。成功后恢复普通提问。':
            '普通提问：模型自行选择已授权的当前水质或项目知识工具。历史水质请使用“历史查询”。'}),
          ...(cannotSend?[el('p',{class:'notice warning',role:'alert',text:unavailable()})]:[]),composer,
          el('label',{class:'assistant-confirm'},[network,el('span',{text:model?.runtime_type==='local'?
            `LOCAL MODEL REQUEST · 本次最多 ${maxRequests} 次本地模型请求`:`REAL NETWORK REQUEST · 本次最多 ${maxRequests} 次模型请求${historical()?' · 每请求最多 '+execution?.max_output_tokens+' output tokens':''}，Cloud 可能产生费用`})]),
          el('div',{class:'composer-foot'},[latest,sendButton,stopButton]),statusNode,
          ...(s.trimmed?[el('p',{class:'muted',text:'较早对话未发送给模型。页面记录不代表模型记住全部历史。'})]:[])])]),
      el('div',{class:'side-stack'},[card('本次运行',`${s.lastRun?'实际':'待运行'} ${actual.transport} · 冻结设备 · ${actual.multi?2:1}/${actual.multi?2:1}/${actual.maxRequests}${actual.tokens?' · '+actual.tokens+' tokens/请求':''}${actual.historical?' · 历史单工具':''}`,[activityNode]),
        card('来源与权限',historical()?'Monitoring SQLite · 历史窗口基础统计。':'共用 Monitoring SQLite 与领域规则。',[rows([['本轮设备',s.device],['本次可用工具',cannotSend?'暂不可用':(historical()?execution?.tools:s.config?.tools)?.map(name=>({get_current_water_quality:'当前水质',search_fishery_knowledge:'项目养殖知识',get_water_quality_history:'历史水质'}[name]||name)).join('、')||'无（可直接回答）'],
          ['监测来源','Simulator · 非真实传感器'],['规则状态',historical()?'未重评历史规则':'PROTOTYPE']]),el('p',{class:'muted',text:
            cannotSend?unavailable():
            historical()?'历史窗口均值不是当前观测。无匹配、缺口和无效窗口不能当作正常；不判断持续低氧或恢复。只有完整成功回答进入会话。':
            '缺失、无效、过期或离线不表示环境正常。项目知识不是当前观测或疾病确诊。只有完整成功回答进入会话，刷新页面清空。'}),
          el('p',{class:'muted',text:'历史查询仅在 Qwen / Normal 下单独试用，须由服务器启用并在系统设置授权。Streaming 暂不支持历史水质；三工具自主选择正在独立验证，尚未开放。'})])]) ]));
    messages.scrollTop=scrollPosition;syncMessages();
    updateProgress();
  }
  async function load(){
    const version=++s.generation,previousEpoch=s.config?.epoch;s.config=null;s.confirmed=false;render();
    try{
      const config=await api.bootstrap(s.device);
      if(version!==s.generation)return;
      if(previousEpoch&&previousEpoch!==config.epoch){s.turns=[];s.entries=[];s.activity=null;s.lastRun=null;}
      s.config=config;
      if(!config.presets.some(p=>p.preset_id===s.preset))s.preset=config.default_preset_id;
      s.status='就绪';
    }catch(e){if(version!==s.generation)return;s.status=safeError(e);}
    render();
  }
  function reset(){s.turns=[];s.entries=[];s.activity=null;s.lastRun=null;s.trimmed=false;s.confirmed=false;s.followLatest=true;}
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
  function changeTransport(value){
    if(s.pending||!['normal','streaming'].includes(value)||s.transport===value)return;
    s.transport=value;s.confirmed=false;s.status='响应模式已更新，请重新确认下一条请求。';render();
  }
  function historyQuery(enabled=true){
    if(s.pending)return;
    s.nextAction=enabled?'history_query':'';
    s.confirmed=false;
    s.status=enabled?'下一条将查询历史水质，请核对可用状态并重新确认。':'已取消历史查询，请重新确认下一条请求。';render();
  }
  function withdrawPreview(reply){if(reply?.kind==='pending'){reply.text='';syncMessages();}}
  function receive(event,active,reply){
    if(run!==active||!s.pending||active.sequence!==s.turnSequence||s.stopRequested||s.cancelUnknown||active.detached)return;
    if(event.request_id!==s.control?.request_id||event.epoch!==active.epoch)throw new Error('ASSISTANT_STREAM_EVENT_INVALID');
    if(event.kind==='start')s.status='Streaming · Preparing';
    if(event.kind==='activity'){
      if(event.activity)s.activity=event.activity;
      s.status=event.phase||event.state;
      if(event.activity?.steps.filter(step=>step.kind==='model').at(-1)?.outcome==='tool_calls')withdrawPreview(reply);
    }
    if(event.kind==='preview_reset')withdrawPreview(reply);
    if(event.kind==='preview'){reply.text=event.text;syncMessages();s.status=`Streaming · Request #${event.request_index} · 临时预览`;}
    if(['error','cancelled'].includes(event.kind))withdrawPreview(reply);
    updateProgress();
  }
  async function send(){
    const question=s.draft.trim();
    if(s.pending||!question||!s.config)return;
    const execution=profile(),streaming=s.transport==='streaming';
    if(blocked()){s.confirmed=false;s.status=unavailable();render();return;}
    if(binding()!==confirmationKey){s.confirmed=false;s.status='模型、设备或可用工具已变化，请重新确认。';render();return;}
    if(!s.confirmed){s.status='请先确认本次模型请求。';updateProgress();return;}
    const config=s.config,model=preset(),history=historyForRequest(s.turns);
    const captured={device_id:s.device,preset_id:s.preset,revision:execution?.revision||model.revision,epoch:config.epoch,question,history,
      ...(historical()?{action:'history_query'}:{})};
    s.pending=true;s.stopRequested=false;s.cancellation=null;s.cancelUnknown=false;s.stopRejected=false;
    s.control=null;s.activity=null;s.status='Preparing';
    s.lastRun={transport:s.transport,multi:execution?.mode==='BOUNDED_MULTI_ROUND',
      maxRequests:execution?.max_model_requests??config.max_model_requests??2,tokens:execution?.max_output_tokens,historical:historical()};
    const sequence=++s.turnSequence;
    const active={sequence,transport:s.transport,epoch:config.epoch,config,controller:streaming?new AbortController():null,detached:false};
    run=active;
    const reply={kind:'pending',text:''};
    s.entries.push({kind:'user',text:question},reply);s.followLatest=true;render();
    let timer;
    try{
      s.control=await api.prepare(config);
      if(s.stopRequested||active.detached){await api.cancel(s.control,config);throw new Error('USER_CANCELLED');}
      const control=s.control;
      if(!streaming)timer=setInterval(async()=>{
        if(!s.pending||sequence!==s.turnSequence)return;
        try{const info=await api.state(control,config);if(!s.pending||sequence!==s.turnSequence)return;
          if(info.activity&&(info.activity.revision??0)>=(s.activity?.revision??0))s.activity=info.activity;
          s.status=s.stopRequested?'取消中…':info.phase||info.state;updateProgress();}catch(_){/* Final POST remains authoritative. */}
      },500);
      const value={...captured,...s.control,confirm_network:true};
      const response=streaming?await api.stream(value,config,{signal:active.controller.signal,profile:execution,
        onEvent:event=>receive(event,active,reply)}):await api.send(value,config);
      if(s.cancellation)await s.cancellation;
      if(active.detached)throw new Error('ASSISTANT_STREAM_INTERRUPTED');
      const result=response.result;
      if(!result)throw new Error(response.error_code||'AI_SERVICE_UNAVAILABLE');
      s.activity=result.activity||s.activity;
      if(!result.successful_turn)throw new Error(result.error_code||'AI_SERVICE_UNAVAILABLE');
      if(s.stopRequested)throw new Error(s.cancelUnknown?'CANCELLATION_STATUS_UNKNOWN':'USER_CANCELLED');
      s.turns.push({user:question,assistant:result.final_text,completed_at:result.completed_at});
      Object.assign(reply,{kind:'assistant',text:result.final_text,activity:result.activity});s.draft='';
      s.status=s.stopRejected?'Completed · 已在 Stop 前完成':`Completed · ${streaming?'Streaming':'Normal'}`;
      s.trimmed=result.history_trimmed||history.length<s.turns.length-1;
      if(captured.action==='history_query'){s.nextAction='';s.status='历史查询已完成 · 下一条恢复普通提问';}
    }catch(e){
      if(s.control&&!s.stopRequested&&!s.cancellation)try{await api.cancel(s.control,config);}catch(_){/* Bounded registry TTL handles an unreachable control API. */}
      const safe=safeError(e);
      const code=active.detached?'ASSISTANT_STREAM_INTERRUPTED':s.stopRequested?(s.cancelUnknown?'CANCELLATION_STATUS_UNKNOWN':'USER_CANCELLED'):
        streaming&&safe==='AI_SERVICE_UNAVAILABLE'?'ASSISTANT_STREAM_INTERRUPTED':safe;s.status=code;
      Object.assign(reply,{kind:'status',activity:s.activity,text:code==='USER_CANCELLED'?'USER_CANCELLED · 未提交半成品。远端计算/计费是否停止：UNKNOWN':
        code==='INVALID_TOOL_ARGUMENTS'?'INVALID_TOOL_ARGUMENTS · 工具参数未通过校验，被拒绝的 Tool 未执行；可展开本次运行详情查看原因。':
        `${code} · 未提交回答；临时预览已撤销。`});
      if(['ASSISTANT_SESSION_EXPIRED','AI_ACCESS_DENIED'].includes(code)){
        reset();await load();s.status=code==='ASSISTANT_SESSION_EXPIRED'?
          'Assistant 后端已重启，请重新发送当前问题。':'Assistant 会话已失效，请重新发送当前问题。';
      }else if(code==='ASSISTANT_EXECUTION_PROFILE_CHANGED'){
        await load();s.status='运行配置或权限已变化，请重新确认。';
      }
    }finally{if(timer)clearInterval(timer);s.pending=false;s.confirmed=false;s.control=null;run=null;render();
      if(s.reloadPolicy){s.reloadPolicy=false;void load();}}
  }
  async function stop(){
    if(!s.pending||s.stopRequested)return;s.stopRequested=true;s.status='取消中…';
    withdrawPreview(s.entries[s.entries.length-1]);updateProgress();
    if(s.control){
      s.cancellation=api.cancel(s.control,s.config).then(info=>{
        if(['COMPLETED','FAILED'].includes(info.state)){s.stopRequested=false;s.stopRejected=true;}
        else run?.controller?.abort();
      }).catch(()=>{s.cancelUnknown=true;run?.controller?.abort();s.status='取消状态未知，请等待本次请求结束。';updateProgress();});
      await s.cancellation;
    }
  }
  return {mount(devices,device){s.devices=devices;
      if(!s.device){s.device=device;void load();}
      else if(device!==s.device&&!s.pending){reset();s.device=device;void load();}
      return root;},send,stop,clear,changePreset,changeDevice,
    changeTransport,historyQuery,
    policyChanged(){s.confirmed=false;if(s.pending){s.reloadPolicy=true;return;}if(s.device)void load();},
    suspend(){
      if(!s.pending)return;
      if(run){run.detached=true;run.controller?.abort();}
      withdrawPreview(s.entries[s.entries.length-1]);
      void stop(); // Existing cancel API uses keepalive, never starts another model request.
    },state:s};
}
