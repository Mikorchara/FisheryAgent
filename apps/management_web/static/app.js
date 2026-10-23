import {el,icon,card,badge,empty,button,link,rows,metricCards,metadata,table,trendChart,normalizedTrendChart} from './components.js';
import {routes,routeFor,timeText,filterItems,validateBootstrap,qualityNames,freshnessNames,sourceName,connectionName,eventState,eventStateName,eventStateReasonName,eventHandlingName,cycleConfirmationName,eventSeverityName,trendRanges,activeEventOverview} from './view-model.js';
import {services} from './services.js';
import {createAssistantWorkspace} from './assistant.js';
import {createToolPolicySettings} from './tool-policy.js';
import {createKnowledgeWorkspace} from './knowledge.js';
import {createSettingsWorkspace} from './settings.js';

const $=id=>document.getElementById(id);
const state={data:null,device:'demo-a',view:'available',metric:'dissolved_oxygen_mg_l',trendRange:'1800',camera:'demo-camera-a',
  eventFilters:{q:'',severity:'',status:'',lookback_minutes:'all'},eventOffset:0,settings:'devices',draft:'',revision:0};
let eventQueryRevision=0,eventDeletionBusy=false,eventAckBusy=false,eventEndBusy=false;
const assistantWorkspace=createAssistantWorkspace(services.ai,{onDevice:id=>{state.device=id;void changeMonitoring();}});
const toolPolicySettings=createToolPolicySettings(services.ai,{onSaved:()=>assistantWorkspace.policyChanged()});
const knowledgeWorkspace=createKnowledgeWorkspace(services.knowledge);
const settingsWorkspace=createSettingsWorkspace(services.settings,toolPolicySettings,{onBudgetSaved:()=>assistantWorkspace.policyChanged()});
const severity=item=>badge(eventSeverityName(item),item.severity==='critical'?'critical':item.severity==='warning'?'warning':'neutral');
const status=item=>el('div',{class:'event-status'},[
  badge(item.source_kind==='simulator'?eventStateName(item):(item.status==='pending'?'待处理（演示）':'已处理（演示）'),eventState(item)==='RESOLVED'?'resolved':item.status==='closed'?'neutral':'warning'),
  ...(item.source_kind==='simulator'?[badge(eventHandlingName(item),item.handling?.state==='ACKNOWLEDGED'?'success':'neutral')]:[])]);

function select(label,choices,value,onchange){return el('label',{class:'field'},[el('span',{text:label}),el('select',{'aria-label':label,onchange:e=>onchange(e.target.value)},
  choices.map(([id,text])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[text])))]);}
function search(label,value,oninput){return el('label',{class:'field search-field'},[el('span',{text:label}),el('input',{type:'search',value,placeholder:'输入名称或关键字',oninput:e=>oninput(e.target.value)})]);}
function details(title,content){$('dialog-title').textContent=title;$('dialog-body').replaceChildren(...content);$('details-dialog').showModal();}
function eventHandlingPanel(item){
  if(item.source_kind!=='simulator')return [];
  const h=item.handling;
  const reason=({LEGACY_OR_UNSUPPORTED_IDENTITY:item.legacy_closed?
    '旧版已结束记录不支持人工知晓确认；符合清理条件时可在事件列表确认删除。':
    '旧记录缺少可写的稳定周期或规则身份，仅供查看。',
    MANUALLY_ENDED:'提醒已人工结束，知晓记录仅作历史保留。',
    EVENT_ENDED:'规则条件已消退，仅保留历史知晓记录。',NOT_CURRENT_GRADE:'此记录不是当前等级；请从当前等级记录确认风险。'})[item.manual_end?.active?'MANUALLY_ENDED':h?.unavailable_reason];
  return [el('section',{class:'event-handling'},[el('h3',{text:'人工知晓记录'}),
    rows([['人工状态',eventHandlingName(item)],['知晓对象',h?.ended||item.manual_end?.active?'已结束提醒（仅历史）':h?.grade_code?
      (item.family_members?.find(e=>e.code===h.grade_code)?.title||item.title):'尚无可确认的等级'],
      ['本等级确认时间',h?.acked_at?timeText(h.acked_at):'尚未确认'],
      ['最近确认（历史）',h?.latest_ack_at?timeText(h.latest_ack_at):'无确认记录'],
      ['操作来源',h?.action_count?'本机操作（未认证访客）':'尚无操作']]),
    el('p',{class:'muted',text:'知晓不代表异常消退或处理完成，不改变监测状态。风险等级变化后需要重新确认。'}),
    ...(reason?[el('p',{class:'muted',text:reason})]:[]),
    ...(h?.can_ack&&state.data.event_management?.ack_enabled?[button('确认已知晓',()=>requestEventAck(item),'primary')]:[]),
    ...(h?.action_count?[el('p',{text:`共 ${h.action_count} 次确认，显示最近 ${h.history.length} 次；完整记录保留在数据库。`}),
      table(['确认时间','当时事件 / 等级','来源'],h.history,a=>[timeText(a.acted_at),a.event_title||a.grade_code,'本机操作（未认证访客）'])]:[])
  ])];
}
function requestEventAck(item){
  if(eventAckBusy)return;
  const h=item.handling;
  let requestId;
  try{requestId=crypto.randomUUID();}catch(_){details('确认暂不可用',[el('p',{text:'当前浏览器不支持安全请求标识，请使用更新的本机浏览器。'})]);return;}
  const value={event_id:item.id,cycle_id:h.cycle_id,grade_token:h.grade_token,grade_version:h.grade_version,
    revision:h.revision,request_id:requestId};
  const commit=button('确认知晓此风险',async()=>{
    if(eventAckBusy)return;eventAckBusy=true;commit.disabled=true;
    try{
      await services.eventAck(value,state.data.event_management.write_token);
      state.revision++;await refresh(true);
      eventDetail(await services.eventDetail(item.id));
    }catch(_){details('确认未完成',[el('p',{text:'请求结果或事件等级可能已变化，请刷新详情核对。未自动重试，也未修改监测状态。'}),
      button('关闭',()=>$('details-dialog').close())]);}
    finally{eventAckBusy=false;commit.disabled=false;}
  },'primary');
  details('确认已知晓',[el('p',{text:`${item.title}：确认已知晓此风险及当前观测状态？此操作不表示异常消退或处理完成。`}),
    el('p',{class:'muted',text:'来源记录为本机操作，不代表经过认证的工作人员身份。'}),
    button('取消',()=>eventDetail(item),'secondary'),commit]);
}
function eventDetail(item){details(item.title,[badge(sourceName(item.source_kind),'demo'),rows([['记录编号',item.id],['时间',timeText(item.occurred_at)],['设备',item.device],['类型',item.type],['等级',eventSeverityName(item)],['状态',item.source_kind==='simulator'?eventStateName(item):'演示处理状态'],['状态说明',item.source_kind==='simulator'?eventStateReasonName(item):'仅为演示处理状态'],['原因代码',item.state_reason],['规则发布',item.publication_status||'PROTOTYPE'],['关联批次',item.batch_id],['接收时间',timeText(item.received_at)],['最近检出信号',timeText(item.last_observed_at)],['最近有效观测',timeText(item.visual_recovery?.last_valid_observed_at||item.last_observed_at)],['恢复观察',item.visual_recovery?`${item.visual_recovery.clear_count}/${item.visual_recovery.required_clear_windows}（本地实验参数）`:'未记录'],['连续观测段起点',timeText(item.visual_recovery?.segment_started_at)],['观测连续性',item.visual_recovery?.continuity==='interrupted'?'历史观测存在不连续，未知时段不计为已证实持续异常':'以有效窗口为依据'],['最近中断原因',item.visual_recovery?.last_interruption_reason],['规则恢复时间',timeText(item.resolved_at)],['规则版本',item.rule_version],['规则范围',item.rule_identity?.scope?.join(' / ')||'旧记录未记录']]),
  ...(item.risk_family?[el('h3',{text:item.risk_family.label+' · 等级变化'}),
    el('p',{text:item.state_reason==='OTHER_RISK_CONDITION_ACTIVE'?'该等级暂未命中，但同指标仍有其他风险等级；不表示异常已恢复。':'各 code 保留原 ID，事件族只提供关联与当前等级展示。'}),
    el('p',{text:item.risk_family.inferred?'旧事件仅关联当前未结束成员，未重建缺失的历史变化。':`保留首次及最近等级变化；略去 ${item.risk_family.omitted_transitions||0} 次中间变化。`}),
    table(['观测时间','等级 / 变化','原始均值','批次 / Session / 序号'],item.risk_family.transitions||[],t=>[
      timeText(t.observed_at),t.title,t.metric?.mean===null?'缺测':`${t.metric?.mean??'—'} ${t.metric?.unit||''}`,
      `${t.batch_id} / ${t.session_id} / ${t.sequence}`]),
    table(['关联记录','等级','监测状态'],item.family_members||[],e=>[e.title,eventSeverityName(e),eventStateName(e)],
      async e=>{try{eventDetail(await services.eventDetail(e.id));}catch(_){details('关联记录不可用',[el('p',{text:'该历史记录可能已删除或按留存规则裁剪；已保存的变化证据仍保留。'})]);}})]:[]),
  ...eventHandlingPanel(item),
  ...manualEndPanel(item),
  ...(item.source_kind==='simulator'&&state.data.event_management?.enabled?[
    ...(item.can_delete_ack_cycle?[button('删除已结束周期',()=>requestEventDeletion('ack_cycle',item),'danger')]:
      item.deletable?[button('删除此原始记录',()=>requestEventDeletion('single',item),'danger')]:[
      el('p',{class:'muted',text:item.deletion_block_reason==='MANUAL_END_AUDIT_RETAINED'?'人工结束及证据留痕保留，不参与历史清理。':item.deletion_block_reason==='ACK_AUDIT_RETAINED'?'知晓审计留存，不可单条删除；整个周期可靠结束后，可连同确认历史一起明确删除。':'此原始记录当前不满足历史删除条件。'})])]:[]),
  ...(item.channel==='visual'?[el('p',{text:'视觉信号消退仅表示连续可靠观测未再检出该异常信号，不代表疾病治愈或人工处理完成。'})]:[]),el('p',{text:item.description}),
  empty('暂无关联媒体','这里将展示关联截图与视频片段；R1 未生成或保存媒体。','camera')]);}
function manualEndPanel(item){
  const end=item.manual_end;
  if(!end||!end.can_end&&!end.history?.length)return [];
  return [el('section',{class:'event-handling'},[
    el('h3',{text:'人工结束记录'}),
    el('p',{class:'muted',text:end.active?'已人工结束提醒；监测恢复仍未证实。后续再次检出异常将重新提醒。':'人工结束只用于中断、过期或缺测的旧提醒，不代表规则恢复。'}),
    rows([['监测状态',eventState(item)],['人工结束时间',timeText(end.acted_at)]]),
    ...(end.can_end&&state.data.event_management?.manual_end_enabled?[button('人工结束此风险',()=>requestManualEnd(item),'secondary')]:[]),
    ...(end.history?.length?[table(['人工结束时间','原因','操作来源'],end.history,h=>[
      timeText(h.acted_at),h.reason,'本机操作（未认证访客）'])]:[])
  ])];
}
async function requestManualEnd(item){
  if(eventEndBusy)return;
  eventEndBusy=true;
  try{
    const token=state.data.event_management.write_token;
    const plan=await services.manualEndPreview({event_id:item.id},token);
    const input=el('input',{type:'text',value:'',maxlength:'200','aria-label':'人工结束原因',placeholder:'说明停用、失联或人工整理原因（必填）'});
    const reason=el('label',{class:'field'},[el('span',{text:'人工结束原因（最多200字）'}),input]);
    const hint=el('p',{class:'muted'});
    const requestId=crypto.randomUUID();
    const commit=button('确认人工结束',async()=>{
      if(eventEndBusy)return;
      if(!input.value.trim()){hint.textContent='请填写人工结束原因。';return;}
      eventEndBusy=true;commit.disabled=true;
      try{
        await services.manualEnd({event_id:item.id,revision:plan.revision,request_id:requestId,reason:input.value.trim()},token);
        state.revision++;await refresh(true);
        eventDetail(await services.eventDetail(item.id));
      }catch(_){details('人工结束未完成',[el('p',{text:'观测、记录或权限可能已变化。请刷新核对，未自动重试。'}),button('关闭',()=>$('details-dialog').close())]);}
      finally{eventEndBusy=false;commit.disabled=false;}
    },'primary');
    details('确认人工结束失联风险',[
      el('p',{text:`${item.title}：本次涉及 ${plan.count} 条原始记录。结束当前提醒并保留原始证据及操作历史；不删除记录，不代表恢复正常。`} ),
      el('p',{class:'muted',text:'新一次可靠异常观测会重新提醒。本机操作不代表经过认证的工作人员身份。'}),
      reason,hint,el('div',{class:'event-confirm-actions'},[button('取消',()=>eventDetail(item)),commit])]);
  }catch(_){details('当前不能人工结束',[el('p',{text:'此风险可能仍有可靠异常、已经结束或观测已更新。请刷新详情核对。'})]);}
  finally{eventEndBusy=false;}
}
async function showEventDetail(item){
  if(!item.cycle_summary){eventDetail(item);return;}
  try{eventDetail(await services.eventDetail(item.cycle_summary.detail_event_id));}
  catch(_){details('详情暂不可用',[el('p',{text:'请刷新列表后重试；没有修改任何记录。'})]);}
}
function eventsTable(items,maintenance=false){return table(['风险 / 类型','设备','首次发生 / 恢复','等级','状态','是否确认',...(maintenance?['历史清理']:[]),'操作'],items,item=>[
  el('div',{class:'table-title'},[el('strong',{text:item.title}),
    ...(item.cycle_summary?[el('small',{text:`${item.cycle_summary.reading_label}：${item.cycle_summary.reading}`}),
      el('small',{text:`${item.cycle_summary.count} 条原始记录 · ${sourceName(item.source_kind)}`})]:[el('small',{text:`${item.id} · ${item.type} · ${sourceName(item.source_kind)}`})])]),
  item.device,el('div',{class:'cycle-time'},[el('span',{text:timeText(item.occurred_at)}),
    ...(item.cycle_summary?[el('small',{text:item.manual_end?.active?`人工结束：${timeText(item.manual_end.acted_at)}`:item.cycle_summary.ended?`恢复 / 原结束：${timeText(item.resolved_at)}`:`最近观测：${timeText(item.last_observed_at)}`})]:[])]),
  el('div',{class:'cycle-level'},[...(item.cycle_summary?.ended?[el('small',{text:'历史最高等级'})]:[]),severity(item)]),
  item.cycle_summary?badge(eventStateName(item),item.manual_end?.active?'neutral':eventState(item)==='RESOLVED'?'resolved':item.status==='closed'?'neutral':'warning'):status(item),
  badge(cycleConfirmationName(item),cycleConfirmationName(item)==='已确认'?'success':'neutral'),
  ...(maintenance?[item.can_delete_ack_cycle?button('删除已结束周期',()=>requestEventDeletion('ack_cycle',item),'text danger'):
    item.deletable?button('删除记录',()=>requestEventDeletion('single',item),'text danger'):
    item.deletion_block_reason==='MANUAL_END_AUDIT_RETAINED'?'人工结束留痕，保留记录':item.deletion_block_reason==='ACK_AUDIT_RETAINED'?(item.cycle_summary?
      (item.cycle_summary.ended?'周期引用受保护，暂不可删除':'周期未结束，不可删除'):'知晓审计留存，不可删除'):
      item.cycle_summary?'原始记录操作见详情':'不可删除']:[])],showEventDetail);}

function currentAnomalies(data){
  const overview=activeEventOverview(data,state.device);
  const name=data.devices.find(d=>d.id===state.device)?.name||state.device;
  const content=overview.items.length?[
    el('div',{class:'anomaly-summary'},[badge(`${overview.items.length} 项需关注`,'warning'),badge(sourceName(data.data_mode),'demo'),
      el('span',{text:'检测信号用于提示核查，疑似疾病不作为确诊。'})]),
    el('div',{class:'anomaly-list'},overview.items.map(item=>el('article',{class:'anomaly-item','data-event-id':item.id},[
      el('div',{class:'anomaly-heading'},[el('strong',{text:item.overview_title||item.title}),
        item.risk_family&&!item.family_current_code?badge('当前等级未知','neutral'):severity(item),status(item)]),
      el('p',{text:`设备 ${item.device_id||item.device} · 首次发生 ${timeText(item.occurred_at)}`}),
      el('p',{text:`最近有效观测 ${timeText(item.visual_recovery?.last_valid_observed_at||item.last_observed_at)}`}),
      ...(item.family_size>1?[el('p',{text:`关联 ${item.family_size} 条等级记录，详情保留变化证据。`})]:[]),
      ...(item.visual_recovery?.continuity==='interrupted'?[el('p',{class:'muted',text:'历史观测存在不连续；未知时段不计为已证实持续异常。'})]:[]),
      button('查看详情',()=>showEventDetail(item),'text')])))]
    :[badge(sourceName(data.data_mode),'demo'),el('p',{class:'anomaly-empty',text:overview.clear?'当前未见异常信号':'状态未知 · 需要完整、新鲜的水质与视觉观测。'})];
  const section=card('当前异常概况',`区域：${name} · ${overview.items.length?'未结束事件，包含恢复观察与观测中断':'以服务器当前规则和观测质量为依据'}`,content,link('全部事件','events'));
  section.className+=` current-anomalies ${overview.items.length?'needs-attention':overview.clear?'signals-clear':'signals-unknown'}`;
  section.setAttribute('data-current-anomalies','true');
  return section;
}

function trend(){const options={rangeSeconds:state.trendRange==='all'?null:Number(state.trendRange)};
  return el('div',{class:'trend-stack'},[card('历史趋势','已存储的窗口均值；不代表连续实时采样。',[trendChart(state.data.monitoring,state.metric,options)],
    el('div',{class:'chart-controls'},[
    select('指标',[['dissolved_oxygen_mg_l','溶解氧'],['temperature_c','水温'],['ph','pH']],state.metric,value=>{state.metric=value;render();}),
    select('历史范围',trendRanges,state.trendRange,value=>{state.trendRange=value;render();})])),
    card('三指标综合趋势（归一化）','与上图共用时间范围；比较各指标的变化趋势，不比较原始数值大小。',[
      normalizedTrendChart(state.data.monitoring,options)])]);}
function videoPlaceholder(compact=false){return el('div',{class:`video-placeholder ${compact?'compact':''}`},[
  el('div',{class:'video-corner',text:'演示预览区域 / 无视频流'}),el('span',{class:'video-symbol'},[icon('camera')]),el('h3',{text:'等待接入监控设备'}),
  el('p',{text:'未接入真实视频；模拟视觉统计展示在下方。'}),badge('NOT CONNECTED','neutral')]);}

function dashboard(){
  const d=state.data, snapshot=d.monitoring;
  const recentEvents=card('最近事件','按风险周期展示；等级变化与原始证据见详情。',[eventsTable((d.event_cycles||d.events).slice(0,5))],link('全部记录','events'));
  recentEvents.className+=' dashboard-events';
  return [el('div',{class:'overview-strip'},[
    el('div',{},[el('span',{class:'strip-icon'},[icon('link')]),el('div',{},[el('strong',{text:'数据连接概况'}),el('small',{text:d.data_mode==='simulator'?'统一监测存储 · 模拟器来源':'独立 Demo adapter 已就绪'})])]),
    el('div',{class:'strip-number'},[el('strong',{text:String(d.devices.length)}),el('span',{text:'监测区域'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'真实设备接入'})]),
    el('div',{class:'strip-number'},[el('strong',{text:d.ai?.connected?'1':'0'}),el('span',{text:'已启用 AI 服务'})]),badge(sourceName(d.data_mode),'demo')]),
    el('div',{class:'section-caption'},[el('h2',{text:'水质指标概览'}),link('查看水质监测','monitoring')]),metadata(snapshot),metricCards(snapshot),currentAnomalies(d),
    el('div',{class:'dashboard-grid dashboard-overview'},[trend(),
      el('div',{class:'side-stack dashboard-sidebar'},[
        card('视觉监测概况','只有模拟窗口统计，真实视频 / NPU 未接入。',[rows([['设备',d.cameras[0]?.name||'无设备'],['上报状态',connectionName(d.cameras[0]?.status)],['视觉新鲜度',freshnessNames[d.cameras[0]?.freshness]||'未知'],['窗口帧数',d.cameras[0]?.summary?.frames_processed??'暂无上报']]),videoPlaceholder(true),el('div',{class:'card-foot'},[el('span',{text:'无实际视频流'}),link('视觉窗口详情','video')])]),
        card('AI 智能助手','从环境事实到可解释的辅助建议。',[el('div',{class:'assistant-entry'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('p',{text:d.ai?.connected?'Normal 助手已启用；当前水质查询与网页共用监测存储。':'启用 Assistant 后，复用现有模型与只读 Tool Runtime。'}),el('a',{href:'#assistant',class:'button primary'},['打开助手工作区',icon('arrow')])])]),
        card('连接状态','未连接不代表设备离线。',[el('div',{class:'connection-list'},d.connections.map(c=>el('div',{class:'connection-row'},[
          el('span',{text:c.name}),badge(connectionName(c.status),c.status==='online'?'success':c.status==='offline'?'warning':'neutral')])))] )]),recentEvents])];
}

async function changeMonitoring(){
  state.revision++;
  await refresh(true);
}
function monitoring(){const snapshot=state.data.monitoring;return [el('div',{class:'filters'},[
  select('观测区域',state.data.devices.map(d=>[d.id,d.name]),state.device,value=>{state.device=value;changeMonitoring();}),
  ...(state.data.data_mode==='demo'?[select('演示数据状态',[['available','可用'],['stale','过期'],['partial','部分缺失'],['invalid','无效'],['missing','无数据']],state.view,value=>{state.view=value;changeMonitoring();})]:[]),
  el('p',{class:'filter-hint',text:state.data.data_mode==='simulator'?'每 5 秒读取服务器；不会采样或写入数据。':'独立 R1 Demo 视图。'})]),metadata(snapshot),metricCards(snapshot),
  ...(snapshot?.quality==='valid'&&snapshot?.freshness==='fresh'&&snapshot?.connectivity!=='offline'?[]:[el('div',{class:'data-warning',text:`数据状态：${qualityNames[snapshot?.quality]||'不可用'} / ${freshnessNames[snapshot?.freshness]||'未知'} / ${connectionName(snapshot?.connectivity)}。保留历史值和时间，不作为当前有效观测。`})]),
  trend(),card('服务器实验规则结果','PROTOTYPE · 复用 DiagnosisService；页面不重复判断，非生产标准。',snapshot?.findings?.length?snapshot.findings.map(f=>el('p',{class:'muted',text:`${f.code} · ${f.message}`})):[el('p',{class:'muted',text:snapshot?.observed_at?'本轮已评估范围未命中实验规则；不代表疾病诊断。':'NO_DATA · 尚无水质上报。'})]),
  card('观测信息','窗口均值与单次观测有明确区别。',[rows([['来源',snapshot?.source],['上报状态',connectionName(snapshot?.connectivity)],['聚合方式',snapshot?.aggregation==='window_mean'?'窗口有效样本均值':'R1 Demo'],['窗口开始',timeText(snapshot?.window?.start)],['窗口结束',timeText(snapshot?.window?.end)],['观测时间',timeText(snapshot?.observed_at)],['服务器接收',timeText(snapshot?.received_at)],['查询时间',timeText(snapshot?.evaluated_at)],['批次',snapshot?.batch_id],['规则版本',snapshot?.rule_version]]),
    el('details',{class:'data-details'},[el('summary',{text:'样本与统计详情'}),table(['指标','有效 / 总数','无效样本','最小','最大','最新'],snapshot?.metrics||[],m=>[m.label,m.valid_samples===null?'—':`${m.valid_samples} / ${m.sample_count}`,m.invalid_samples??'—',m.minimum??'—',m.maximum??'—',m.latest??'—'])]),
    el('details',{class:'data-details'},[el('summary',{text:'已存储历史表'}),table(['观测时间','水温 °C','pH','溶解氧 mg/L'],snapshot?.trend||[],p=>[timeText(p.observed_at),p.temperature_c??'—',p.ph??'—',p.dissolved_oxygen_mg_l??'—'])])])];}

function assistant(){if(state.data.ai?.connected)return [assistantWorkspace.mount(state.data.devices,state.device)];return [el('div',{class:'assistant-layout'},[
  el('section',{class:'card chat-shell'},[el('div',{class:'chat-top'},[el('div',{},[icon('spark'),el('strong',{text:'渔业助手'})]),badge('服务未接入','neutral')]),
    el('div',{class:'chat-messages'},[el('div',{class:'chat-welcome'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('h2',{text:'让问题有依据，让建议可追溯。'}),el('p',{text:'R1 先建立对话容器。接入后，消息与只读工具通过应用层服务执行，不在页面内运行模型。'}),
      el('div',{class:'suggestions'},['当前水质有哪些需要关注的指标？','如何理解溶解氧？','查找相关养殖资料'].map(text=>button(text,()=>{state.draft=text;$('assistant-draft').value=text;})))])]),
    el('div',{class:'chat-composer'},[el('label',{for:'assistant-draft',text:'消息草稿',class:'sr-only'}),el('textarea',{id:'assistant-draft',rows:3,placeholder:'可以编辑草稿；AI 服务接入后再发送。',text:state.draft,oninput:e=>{state.draft=e.target.value;}}),
      el('div',{class:'composer-foot'},[el('span',{text:'尚未连接 AI · 不会产生模型请求'}),el('button',{class:'button primary',disabled:'disabled',text:'发送 · 尚未接入'})])])]),
  el('div',{class:'side-stack'},[card('模型与响应','应用服务提供模型清单与执行状态。',[rows([['模型','尚未加载'],['响应模式','Normal 默认 · Streaming 受发布门禁控制'],['运行状态','未连接']])]),
    card('工具执行','未来仅展示安全 Activity。',[empty('暂无执行记录','Tool 调用、步骤和来源证明将在服务接入后展示。','settings')]),
    card('开发验证','与管理平台的正式工作区分开。',[el('p',{class:'muted',text:'现有 AI Prototype Web 保留在独立端口，模型和凭据由原 Runtime 管理。'}),el('a',{class:'text-link',href:'http://127.0.0.1:8765',target:'_blank',rel:'noopener noreferrer',text:'打开现有 AI 原型 ↗'})])])])];}

function video(){const cameras=state.data.cameras;const camera=cameras.find(c=>c.id===state.camera)||cameras[0];const summary=camera?.summary;
  const behaviors={normal_activity:'正常活动',reduced_activity:'活动减少',feeding:'摄食',feeding_anomaly:'摄食异常',unknown:'未知'};
  const anomalies={suspected_lesion:'疑似病灶',surface_anomaly:'体表异常',suspected_dead:'疑似死亡个体'};
  return [el('div',{class:'video-layout'},[
    card('监控预览','未播放任何视频流。',[videoPlaceholder(),el('div',{class:'card-foot'},[el('span',{text:camera?.name||'无设备'}),badge('视频未接入','neutral')])]),
    el('div',{class:'side-stack'},[card('监测设备','视觉与水质共享设备和时间窗。',[el('div',{class:'camera-list'},cameras.map(c=>button(c.name,()=>{state.camera=c.id;render();},state.camera===c.id?'selected':'secondary')))]),
      card('视觉数据状态','PROTOTYPE · 统计来自模拟器，不是真实 NPU 推理。',[rows([['来源',sourceName(camera?.source_kind)],['上报状态',connectionName(camera?.status)],['新鲜度',freshnessNames[camera?.freshness]||'未知'],['检测信号',camera?.signal_status==='no_obvious_anomaly'?'未出现所列异常信号（模拟）':camera?.signal_status==='suspected_anomaly'?'疑似异常（模拟，非确诊）':camera?.signal_status==='no_valid_frames'?'无有效帧，信号未知':camera?.signal_status==='indeterminate'?'当前状态待确认':'暂无信号'],['观测时间',timeText(camera?.observed_at)],['接收时间',timeText(camera?.received_at)]])])])]),
    ...(summary?[card('疾病与异常检测信号','窗口内出现该信号的帧数；类别可重叠，不能作为最终疾病诊断。',[
      badge('SIMULATOR · 非诊断','demo'),rows(Object.entries(anomalies).map(([key,label])=>[label,`${summary.anomaly_counts[key]} / ${summary.valid_frames??summary.frames_processed} 有效帧`]))]),
      card('行为识别','窗口内有效帧比例，不是绝对行为结论。',[rows(Object.entries(behaviors).map(([key,label])=>[label,summary.valid_frames===0?'无有效帧':`${(summary.behavior_ratios[key]*100).toFixed(1)}%`]))]),
      card('体长与可见数量','体长按有效检测记录加权；无标定时不显示厘米值；可见鱼数不代表鱼池存量。',[rows([
        ['平均体长',summary.length.average_length_cm===null?'不可测量':`${summary.length.average_length_cm} cm（模拟标定）`],
        [summary.length.valid_frame_count===undefined?'旧窗口体长计数（旧语义）':'有效体长检测记录',summary.length.length_sample_count],['体长有效帧',summary.length.valid_frame_count??'旧窗口未记录'],
        ['有效画面 / 总帧',`${summary.valid_frames??summary.frames_processed} / ${summary.frames_processed}`],['标定',summary.length.calibration==='uncalibrated'?'未标定':'纯模拟标定'],
        ['画面平均可见数',summary.visible_fish_count??'缺失'],['模型版本',summary.model_version],['窗口开始',timeText(camera.window?.start)],
        ['窗口结束',timeText(camera.window?.end)],['关联批次',camera.batch_id]])])]
      :[card('视觉窗口汇总','没有补造另一通道数据。',[empty('NO_DATA · 暂无视觉上报','启动模拟器后显示窗口统计；不会生成假录像。','camera')])])];}

async function requestEventDeletion(scope,item=null){
  if(eventDeletionBusy)return;
  eventDeletionBusy=true;
  const value={scope,...(item?{event_id:item.id}:{})},token=state.data.event_management?.write_token;
  const cancel=()=>{$('details-dialog').close();};
  try{
    const plan=await services.eventDeletionPreview(value,token);
    const finish=()=>{
      const commit=button(scope==='ack_cycle'?'确认删除周期及确认历史':scope==='single'?'确认删除此条事件':`确认清理 ${plan.count} 条记录`,async()=>{
        if(eventDeletionBusy)return;eventDeletionBusy=true;commit.disabled=true;
        try{const result=await services.eventDelete({...value,revision:plan.revision},token);
          $('details-dialog').close();state.eventOffset=0;state.revision++;await refresh(true);
          $('refresh-status').textContent=`已删除 ${result.deleted_count} 条已结束事件记录${scope==='ack_cycle'?`及 ${result.deleted_ack_count} 条确认历史`:''}`;
        }catch(_){details('删除未完成',[el('p',{text:'记录或权限可能已变化。未自动重试；请刷新后重新预览、确认。'}),button('关闭',cancel)]);}
        finally{eventDeletionBusy=false;commit.disabled=false;}
      },'danger');
      details(scope==='ack_cycle'?'永久删除已结束周期':scope==='single'?'确认删除历史事件':'最终确认：清理全部已结束事件',[
        el('p',{text:scope!=='all_resolved'?`${item.title} · ${item.id}`:'范围：全部设备、全部时间的可删除已结束记录，包含符合条件的旧版已结束记录；不受当前筛选或分页影响。'}),
        el('p',{text:`预计删除 ${plan.count} 条。数据库硬删除，应用内不可撤销；水质历史、批次及其他业务数据不受影响。`}),
        ...(scope==='ack_cycle'?[el('p',{text:`同时永久删除该周期的 ${plan.ack_count} 条确认历史及等级关联。此后无法查看该周期的确认时间及当时等级；不会保留可恢复的归档。`})]:[]),
        ...(plan.legacy_count?[el('p',{text:`其中 ${plan.legacy_count} 条为旧版已结束记录，未经新版规则复核；清理不表示已验证恢复，不补造人工确认。`})]:[]),
        el('div',{class:'event-confirm-actions'},[...(plan.count?[commit]:[]),button('取消',cancel)]),
        ...(!plan.count?[el('p',{text:'没有可删除的已结束事件。'})]:[])]);
    };
    if(scope!=='all_resolved')finish();
    else details('清理范围核对',[
      el('p',{text:`全部设备、全部时间，共 ${plan.count} 条可删除的已结束事件，其中 ${plan.legacy_count||0} 条为旧版已结束记录；忽略当前筛选和分页。活动、恢复观察及未结束的未知事件均保留。`}),
      el('div',{class:'event-confirm-actions'},[button('继续核对',finish),button('取消',cancel)])]);
  }catch(_){details('无法准备删除',[el('p',{text:'记录状态或权限不允许操作。请刷新后重新检查。'}),button('关闭',cancel)]);}
  finally{eventDeletionBusy=false;}
}

function events(){const filters=state.eventFilters,maintenance=Boolean(state.data.event_management?.enabled);
  const body=el('div',{id:'events-table'}),count=el('p',{class:'muted'}),pager=el('div',{class:'event-pager'});
  const update=async()=>{
    if(!maintenance){body.replaceChildren(eventsTable(filterItems(state.data.events,filters)));return;}
    const revision=++eventQueryRevision;
    count.textContent='正在查询全部留存事件…';
    try{const data=await services.events({...filters,limit:50,offset:state.eventOffset});
      if(revision!==eventQueryRevision)return;
      if(data.total&&state.eventOffset>=data.total){state.eventOffset=0;return update();}
      body.replaceChildren(eventsTable(data.items,true));
      count.textContent=`共 ${data.total} 条符合条件 · 本页 ${data.items.length} 条 · 已查询全部留存记录（风险周期）`;
      const previous=button('上一页',()=>{state.eventOffset=Math.max(0,state.eventOffset-50);void update();});previous.disabled=state.eventOffset===0;
      const next=button('下一页',()=>{state.eventOffset+=50;void update();});next.disabled=state.eventOffset+50>=data.total;
      pager.replaceChildren(previous,el('span',{text:`第 ${Math.floor(state.eventOffset/50)+1} 页`}),next);
    }catch(_){if(revision!==eventQueryRevision)return;body.replaceChildren(empty('事件查询失败','请刷新重试；不把缓存当作查询结果。'));count.textContent='查询失败';pager.replaceChildren();}
  };
  const change=()=>{state.eventOffset=0;void update();};
  void update();
  return [el('div',{class:'filters'},[search('搜索事件',filters.q,v=>{filters.q=v;change();}),select('事件等级',[['','全部等级'],['critical','严重'],['warning','提醒'],['info','信息']],filters.severity,v=>{filters.severity=v;change();}),
    select('事件状态',state.data.data_mode==='simulator'?[['','全部状态'],['ACTIVE','异常中'],['RESOLVED','已恢复'],['MANUALLY_ENDED','已人工结束'],['INDETERMINATE','状态待核实／旧版未复核']]:[['','全部状态'],['pending','待处理（演示）'],['closed','已处理（演示）']],filters.status,v=>{filters.status=v;change();}),
    ...(maintenance?[select('事件时间范围',[['5','最近 5 分钟'],['10','最近 10 分钟'],['30','最近 30 分钟'],['60','最近 1 小时'],['all','全部记录']],filters.lookback_minutes||'all',v=>{filters.lookback_minutes=v;change();})]:[]),
    button('重置筛选',()=>{state.eventFilters={q:'',severity:'',status:'',lookback_minutes:'all'};state.eventOffset=0;render();})]),
    card('事件列表','PROTOTYPE 模拟信号，不具备生产处理工作流',[count,body,pager],maintenance?button('清理全部已结束事件',()=>requestEventDeletion('all_resolved'),'danger'):null),
    el('p',{class:'footnote',text:'时间按事件关注区间与所选时段相交筛选：未结束的早期事件仍列出；未知时段不表示持续检出。“已确认”仅表示知晓当前／结束前最后等级，不表示恢复或处理完成。普通批量清理保留确认历史；已结束周期可单独明确删除，连同该周期全部确认历史永久清除。'})];}

function knowledge(){return [knowledgeWorkspace.mount()];}

function settings(){return [settingsWorkspace.mount()];}

const pages={dashboard,monitoring,assistant,video,events,knowledge,settings};
function render(passive=false){if(!state.data)return;if(state.readFailed){$('content').replaceChildren(empty('读取失败 · 上次显示已失效','请恢复服务器连接，不将缓存当作当前数据。'));return;}const route=routeFor(location.hash);$('page-title').textContent=route.title;$('page-eyebrow').textContent=route.eyebrow;$('page-description').textContent=route.description;$('breadcrumb').textContent=route.title;
  document.title=`${route.title} · AI 监测系统`;$('content').replaceChildren(...pages[route.id]());
  document.querySelectorAll('#navigation a').forEach(a=>{const active=a.hash===`#${route.id}`;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(!passive){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}}
let refreshing=false;
async function refresh(force=false){
  if(refreshing&&!force)return;
  const revision=state.revision,device=state.device;
  refreshing=true;
  try{
    let data=validateBootstrap(await services.bootstrap(state.data?device:undefined));
    if(!state.data&&data.preferences){
      const defaults=data.preferences;
      if(data.devices.some(d=>d.id===defaults.device_id)){state.device=defaults.device_id;
        data=validateBootstrap(await services.bootstrap(state.device));}
      assistantWorkspace.setDefaults(defaults);
    }
    if(revision!==state.revision)return;
    if(data.data_mode==='demo'&&state.view!=='available')data.monitoring=await services.monitoring(device,state.view);
    if(revision!==state.revision)return;
    const recovered=state.readFailed;state.readFailed=false;state.data=data;
    if(!data.devices.some(d=>d.id===state.device))state.device=data.devices[0]?.id||'';
    if(!data.cameras.some(c=>c.id===state.camera))state.camera=data.cameras[0]?.id||'';
    $('source-label').textContent=sourceName(data.data_mode);
    $('source-notice').textContent=data.data_mode==='simulator'?'水质与视觉来自模拟器 HTTP 上报，非真实设备或疾病诊断。页面与已启用的水质 Tool 共用统一存储。':'独立 R1 Demo；不是传感器、NPU 或正式 AI 数据。';
    document.querySelector('.environment').textContent=data.data_mode==='simulator'?'本机模拟接入':'DEMO 环境';
    $('refresh-status').textContent='服务器状态已更新';
    const active=document.activeElement;
    if(force||!active?.matches('input,select,textarea')){
      if(force||recovered||['dashboard','monitoring','video','events'].includes(routeFor(location.hash).id))render(!force);
    }
  }catch(_){
    if(revision!==state.revision)return;
    state.readFailed=true;$('refresh-status').textContent='读取失败 · 上次显示已失效';
    if(force||!state.data)$('content').replaceChildren(card('工作区暂不可用','不使用假数据掩盖服务错误。',[empty('服务加载失败','请检查管理服务。'),button('重新加载',bootstrap)]));
    else $('content').replaceChildren(empty('读取失败 · 上次显示已失效','请恢复服务器连接，不将缓存当作当前数据。'));
  }finally{refreshing=false;}
}
async function bootstrap(){await refresh(true);}

$('navigation').append(...routes.map(r=>el('a',{href:`#${r.id}`},[icon(r.icon),el('span',{text:r.label})])));
$('menu-toggle').addEventListener('click',()=>{$('sidebar').classList.toggle('open');$('menu-toggle').setAttribute('aria-expanded',String($('sidebar').classList.contains('open')));});
$('dialog-close').addEventListener('click',()=>$('details-dialog').close());
$('details-dialog').addEventListener('click',e=>{if(e.target===$('details-dialog'))$('details-dialog').close();});
window.addEventListener('hashchange',()=>{render();$('main').focus({preventScroll:true});window.scrollTo(0,0);});
document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();$('main').focus();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
document.addEventListener('click',event=>{if(!$('sidebar').contains(event.target)&&!$('menu-toggle').contains(event.target)){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
bootstrap();
let poll;
function startPolling(){if(!poll)poll=setInterval(()=>{if(!document.hidden)refresh();},5000);}
startPolling();
window.addEventListener('pagehide',()=>{clearInterval(poll);poll=null;assistantWorkspace.suspend();});
window.addEventListener('pageshow',()=>{startPolling();});
