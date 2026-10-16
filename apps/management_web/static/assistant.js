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
  const s={device:'',devices:[],preset:'',transport:'normal',config:null,turns:[],entries:[],draft:'',pending:false,
    confirmed:false,control:null,stopRequested:false,cancellation:null,cancelUnknown:false,stopRejected:false,
    status:'就绪',activity:null,lastRun:null,trimmed:false,generation:0,turnSequence:0,followLatest:true};
  const root=el('div',{class:'management-assistant'});
  let composer,statusNode,activityNode,sendButton,stopButton,run=null;
  const safeError=e=>/^[A-Z][A-Z0-9_]{0,63}$/.test(e?.message||'')?e.message:'AI_SERVICE_UNAVAILABLE';
  const preset=()=>s.config?.presets.find(p=>p.preset_id===s.preset);
  const profile=()=>s.transport==='streaming'?preset()?.streaming:preset()?.execution;
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
    if(!s.entries.length){messages.replaceChildren(empty('让问题有依据，让建议可追溯。','可询问当前水质，也可直接讨论溶氧概念。查询不等于采样。','spark'));}
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
            ['评估时间',timeText(tool.evaluated_at)]]:[])])])):[el('p',{class:'muted',text:s.pending?'尚未执行 Tool':'未调用 Tool'})]));
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
    if(statusNode)statusNode.textContent=s.status;
    if(activityNode)showActivity(activityNode,s.activity);
  }
  function render(){
    const scrollPosition=messages.scrollTop;
    const model=preset();
    const streaming=s.transport==='streaming',execution=profile();
    const maxRequests=execution?.max_model_requests??s.config?.max_model_requests??2;
    const blocked=streaming?execution?.can_send!==true:execution?.can_send===false;
    const streamingReason={flag_disabled:'未启用本地 Streaming 试用启动参数，请重启服务器并刷新页面',
      candidate:'此精确范围仍为 candidate，尚未开放本地试用',
      scope_not_published:'模型、Tool Policy 或运行配置未匹配；仅开放 Qwen OFF 与水质查询 + 项目知识两工具',
      runtime_constraints_mismatch:'重试或整 Turn Deadline 不符合本地试用要求'}[execution?.mode_reason]||'精确 Streaming Scope 未匹配';
    const multi=execution?.mode==='BOUNDED_MULTI_ROUND';
    const actual=s.lastRun||{transport:s.transport,multi,maxRequests,tokens:execution?.max_output_tokens};
    const selectField=(label,choices,value,change)=>el('label',{class:'field'},[el('span',{text:label}),
      el('select',{...(s.pending?{disabled:'disabled'}:{}),onchange:e=>change(e.target.value)},choices.map(([id,name])=>
        el('option',{value:id,...(id===value?{selected:'selected'}:{})},[name])))]);
    composer=el('textarea',{rows:3,'aria-label':'消息',placeholder:'输入问题，Ctrl + Enter 发送',text:s.draft,
      ...(s.pending?{disabled:'disabled'}:{}),oninput:e=>{s.draft=e.target.value;},onkeydown:e=>{
        if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();void send();}}});
    const network=el('input',{type:'checkbox',...(s.confirmed?{checked:'checked'}:{}),...(s.pending?{disabled:'disabled'}:{}),
      onchange:e=>{s.confirmed=e.target.checked;}});
    sendButton=el('button',{class:'button primary',text:'发送',...(!s.config||s.pending||blocked?{disabled:'disabled'}:{}),onclick:()=>void send()});
    stopButton=el('button',{class:'button secondary',text:'Stop',...(!s.pending?{disabled:'disabled'}:{}),onclick:()=>void stop()});
    statusNode=el('p',{class:'muted',role:'status',text:s.status});activityNode=el('div');
    root.replaceChildren(el('div',{class:'assistant-layout'},[
      el('section',{class:'card chat-shell'},[
        el('div',{class:'chat-top assistant-controls'},[
          selectField('模型',(s.config?.presets||[]).map(p=>[p.preset_id,p.display_name]),s.preset,changePreset),
          selectField('监测设备',s.devices.map(d=>[d.id,d.name]),s.device,changeDevice),
          selectField('响应模式',[['normal','Normal'],['streaming','Streaming']],s.transport,changeTransport),
          badge(`Thinking OFF · ${streaming?'Streaming':'Normal'}`,'neutral'),
          badge(streaming?`Streaming · ${execution?.release_status==='local_experimental'?'本地实验 · ':''}${execution?.release_status||'unpublished'}${blocked?' · 未开放':''}`:
            blocked?'多轮 Scope / Policy 不匹配':multi?'Multi-Round · 本地实验（未真实验证）':'Single-Round · 1/1/2','neutral'),
          el('button',{class:'button text',text:'清空对话',...(s.pending?{disabled:'disabled'}:{}),onclick:clear})]),lane,
        el('div',{class:'chat-composer'},[composer,
          el('label',{class:'assistant-confirm'},[network,el('span',{text:model?.runtime_type==='local'?
            `LOCAL MODEL REQUEST · 本次最多 ${maxRequests} 次本地模型请求`:`REAL NETWORK REQUEST · 本次最多 ${maxRequests} 次模型请求，Cloud 可能产生费用`})]),
          el('div',{class:'composer-foot'},[latest,sendButton,stopButton]),statusNode,
          ...(s.trimmed?[el('p',{class:'muted',text:'较早对话未发送给模型。页面记录不代表模型记住全部历史。'})]:[])])]),
      el('div',{class:'side-stack'},[card('本次运行',`${s.lastRun?'实际':'待运行'} ${actual.transport} · 冻结设备 · ${actual.multi?2:1}/${actual.multi?2:1}/${actual.maxRequests}${actual.transport==='streaming'?' · '+(actual.tokens??'—')+' tokens/请求':''}`,[activityNode]),
        card('来源与权限','共用 Monitoring SQLite 与领域规则。',[rows([['本轮设备',s.device],['可用 Tool',s.config?.tools.join('、')||'无（受 Tool Policy 限制）'],
          ['监测来源','Simulator · 非真实传感器'],['规则状态','PROTOTYPE']]),el('p',{class:'muted',text:
            streaming&&blocked?'Streaming 不可用：'+streamingReason+'（'+(execution?.mode_reason||'scope_not_published')+'）。不会发起模型请求；切回 Normal 后须重新确认。':
            blocked?'精确 Scope / Policy 未匹配，请检查授权组合并刷新。不会联网或自动降级重跑。':
            '缺失、无效、过期或离线不表示环境正常。项目知识不是当前观测或疾病确诊。临时预览未通过提交门禁；只有完整成功回答进入会话，刷新页面清空。'})])]) ]));
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
    s.transport=value;s.confirmed=false;s.status='就绪';render();
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
    if(streaming?execution?.can_send!==true:execution?.can_send===false){
      s.status=streaming?'ASSISTANT_STREAMING_NOT_RELEASED':'ASSISTANT_MULTI_ROUND_SCOPE_MISMATCH';updateProgress();return;}
    if(!s.confirmed){s.status='请先确认本次模型请求。';updateProgress();return;}
    const config=s.config,model=preset(),history=historyForRequest(s.turns);
    const captured={device_id:s.device,preset_id:s.preset,revision:execution?.revision||model.revision,epoch:config.epoch,question,history};
    s.pending=true;s.stopRequested=false;s.cancellation=null;s.cancelUnknown=false;s.stopRejected=false;
    s.control=null;s.activity=null;s.status='Preparing';
    s.lastRun={transport:s.transport,multi:execution?.mode==='BOUNDED_MULTI_ROUND',
      maxRequests:execution?.max_model_requests??config.max_model_requests??2,tokens:execution?.max_output_tokens};
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
    }finally{if(timer)clearInterval(timer);s.pending=false;s.confirmed=false;s.control=null;run=null;render();}
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
    changeTransport,
    suspend(){
      if(!s.pending)return;
      if(run){run.detached=true;run.controller?.abort();}
      withdrawPreview(s.entries[s.entries.length-1]);
      void stop(); // Existing cancel API uses keepalive, never starts another model request.
    },state:s};
}
