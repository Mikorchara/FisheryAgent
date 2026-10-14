import {el,icon,card,badge,empty,button,link,rows,metricCards,metadata,table,trendChart} from './components.js';
import {routes,routeFor,timeText,filterItems,validateBootstrap,qualityNames,freshnessNames,sourceName,connectionName} from './view-model.js';
import {services} from './services.js';

const $=id=>document.getElementById(id);
const state={data:null,device:'demo-a',view:'available',metric:'dissolved_oxygen_mg_l',camera:'demo-camera-a',
  eventFilters:{q:'',severity:'',status:''},fileFilters:{q:'',category:''},settings:'devices',draft:'',revision:0};
const severity=item=>badge(item.severity==='warning'?'提醒':'信息',item.severity==='warning'?'warning':'neutral');
const status=item=>badge(item.source_kind==='simulator'?(item.status==='pending'?'信号未消退':'已消退'):(item.status==='pending'?'待处理（演示）':'已处理（演示）'),item.status==='pending'?'warning':'neutral');

function select(label,choices,value,onchange){return el('label',{class:'field'},[el('span',{text:label}),el('select',{onchange:e=>onchange(e.target.value)},
  choices.map(([id,text])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[text])))]);}
function search(label,value,oninput){return el('label',{class:'field search-field'},[el('span',{text:label}),el('input',{type:'search',value,placeholder:'输入名称或关键字',oninput:e=>oninput(e.target.value)})]);}
function details(title,content){$('dialog-title').textContent=title;$('dialog-body').replaceChildren(...content);$('details-dialog').showModal();}
function eventDetail(item){details(item.title,[badge(sourceName(item.source_kind),'demo'),rows([['记录编号',item.id],['时间',timeText(item.occurred_at)],['设备',item.device],['类型',item.type],['等级',item.severity==='warning'?'提醒':'信息'],['状态',item.source_kind==='simulator'?(item.status==='pending'?'当前信号':'已消退'):'演示处理状态'],['关联批次',item.batch_id],['接收时间',timeText(item.received_at)],['最近信号',timeText(item.last_observed_at)],['规则版本',item.rule_version]]),el('p',{text:item.description}),
  empty('暂无关联媒体','这里将展示关联截图与视频片段；R1 未生成或保存媒体。','camera')]);}
function fileDetail(item){details(item.name,[badge('DEMO','demo'),rows([['分类',item.category],['格式',item.format],['来源',item.source],['索引状态','未建立'],['文件大小','未上传'],['检索能力','未接入']]),el('p',{text:item.description}),el('button',{class:'button secondary',disabled:'disabled',text:'下载不可用 · 演示元数据'})]);}
function eventsTable(items){return table(['事件 / 类型','设备','时间','等级','状态','操作'],items,item=>[
  el('div',{class:'table-title'},[el('strong',{text:item.title}),el('small',{text:`${item.id} · ${item.type} · ${sourceName(item.source_kind)}`})]),item.device,timeText(item.occurred_at),severity(item),status(item)],eventDetail);}

function trend(){return card('历史趋势','已存储的窗口均值；不代表连续实时采样。',[trendChart(state.data.monitoring,state.metric)],
  select('指标',[['dissolved_oxygen_mg_l','溶解氧'],['temperature_c','水温'],['ph','pH']],state.metric,value=>{state.metric=value;render();}));}
function videoPlaceholder(compact=false){return el('div',{class:`video-placeholder ${compact?'compact':''}`},[
  el('div',{class:'video-corner',text:'演示预览区域 / 无视频流'}),el('span',{class:'video-symbol'},[icon('camera')]),el('h3',{text:'等待接入监控设备'}),
  el('p',{text:'未接入真实视频；模拟视觉统计展示在下方。'}),badge('NOT CONNECTED','neutral')]);}

function dashboard(){
  const d=state.data, snapshot=d.monitoring;
  return [el('div',{class:'overview-strip'},[
    el('div',{},[el('span',{class:'strip-icon'},[icon('link')]),el('div',{},[el('strong',{text:'数据连接概况'}),el('small',{text:d.data_mode==='simulator'?'统一监测存储 · 模拟器来源':'独立 Demo adapter 已就绪'})])]),
    el('div',{class:'strip-number'},[el('strong',{text:String(d.devices.length)}),el('span',{text:'监测区域'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'真实设备接入'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'已连接 AI 服务'})]),badge(sourceName(d.data_mode),'demo')]),
    el('div',{class:'section-caption'},[el('h2',{text:'水质指标概览'}),link('查看水质监测','monitoring')]),metadata(snapshot),metricCards(snapshot),
    el('div',{class:'dashboard-grid'},[trend(),card('视觉监测概况','只有模拟窗口统计，真实视频 / NPU 未接入。',[rows([['设备',d.cameras[0]?.name||'无设备'],['上报状态',connectionName(d.cameras[0]?.status)],['视觉新鲜度',freshnessNames[d.cameras[0]?.freshness]||'未知'],['窗口帧数',d.cameras[0]?.summary?.frames_processed??'暂无上报']]),videoPlaceholder(true),el('div',{class:'card-foot'},[el('span',{text:'无实际视频流'}),link('视觉窗口详情','video')])])]),
    el('div',{class:'dashboard-grid bottom-grid'},[card('最近事件','关联实际接收批次；模拟事件不是疾病确诊。',[eventsTable(d.events.slice(0,5))],link('全部记录','events')),
      el('div',{class:'side-stack'},[card('AI 智能助手','从环境事实到可解释的辅助建议。',[el('div',{class:'assistant-entry'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('p',{text:'新工作区已就绪。AI 服务接入后，复用现有 Assistant 与 Tool Runtime。'}),el('a',{href:'#assistant',class:'button primary'},['打开助手工作区',icon('arrow')])])]),
        card('连接状态','未连接不代表设备离线。',[el('div',{class:'connection-list'},d.connections.map(c=>el('div',{class:'connection-row'},[
          el('span',{text:c.name}),badge(connectionName(c.status),c.status==='online'?'success':c.status==='offline'?'warning':'neutral')])))] )])])];
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
  trend(),card('服务器规则结果','由 DiagnosisService 产生，页面不重复判断。',snapshot?.findings?.length?snapshot.findings.map(f=>el('p',{class:'muted',text:`${f.code} · ${f.message}`})):[el('p',{class:'muted',text:snapshot?.observed_at?'未发现规则异常；不代表疾病诊断。':'NO_DATA · 尚无水质上报。'})]),
  card('观测信息','窗口均值与单次观测有明确区别。',[rows([['来源',snapshot?.source],['上报状态',connectionName(snapshot?.connectivity)],['聚合方式',snapshot?.aggregation==='window_mean'?'窗口有效样本均值':'R1 Demo'],['窗口开始',timeText(snapshot?.window?.start)],['窗口结束',timeText(snapshot?.window?.end)],['观测时间',timeText(snapshot?.observed_at)],['服务器接收',timeText(snapshot?.received_at)],['查询时间',timeText(snapshot?.evaluated_at)],['批次',snapshot?.batch_id],['规则版本',snapshot?.rule_version]]),
    el('details',{class:'data-details'},[el('summary',{text:'样本与统计详情'}),table(['指标','有效 / 总数','无效样本','最小','最大','最新'],snapshot?.metrics||[],m=>[m.label,m.valid_samples===null?'—':`${m.valid_samples} / ${m.sample_count}`,m.invalid_samples??'—',m.minimum??'—',m.maximum??'—',m.latest??'—'])]),
    el('details',{class:'data-details'},[el('summary',{text:'已存储历史表'}),table(['观测时间','水温 °C','pH','溶解氧 mg/L'],snapshot?.trend||[],p=>[timeText(p.observed_at),p.temperature_c??'—',p.ph??'—',p.dissolved_oxygen_mg_l??'—'])])])];}

function assistant(){return [el('div',{class:'assistant-layout'},[
  el('section',{class:'card chat-shell'},[el('div',{class:'chat-top'},[el('div',{},[icon('spark'),el('strong',{text:'渔业助手'})]),badge('服务未接入','neutral')]),
    el('div',{class:'chat-messages'},[el('div',{class:'chat-welcome'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('h2',{text:'让问题有依据，让建议可追溯。'}),el('p',{text:'R1 先建立对话容器。接入后，消息与只读工具通过应用层服务执行，不在页面内运行模型。'}),
      el('div',{class:'suggestions'},['当前水质有哪些需要关注的指标？','如何理解溶解氧？','查找相关养殖资料'].map(text=>button(text,()=>{state.draft=text;$('assistant-draft').value=text;})))])]),
    el('div',{class:'chat-composer'},[el('label',{for:'assistant-draft',text:'消息草稿',class:'sr-only'}),el('textarea',{id:'assistant-draft',rows:3,placeholder:'可以编辑草稿；AI 服务接入后再发送。',text:state.draft,oninput:e=>{state.draft=e.target.value;}}),
      el('div',{class:'composer-foot'},[el('span',{text:'尚未连接 AI · 不会产生模型请求'}),el('button',{class:'button primary',disabled:'disabled',text:'发送 · 尚未接入'})])])]),
  el('div',{class:'side-stack'},[card('模型与响应','应用服务提供模型清单与执行状态。',[rows([['模型','尚未加载'],['响应模式','待接入 Normal / Streaming'],['运行状态','未连接']])]),
    card('工具执行','未来仅展示安全 Activity。',[empty('暂无执行记录','Tool 调用、步骤和来源证明将在服务接入后展示。','settings')]),
    card('开发验证','与管理平台的正式工作区分开。',[el('p',{class:'muted',text:'现有 AI Prototype Web 保留在独立端口，模型和凭据由原 Runtime 管理。'}),el('a',{class:'text-link',href:'http://127.0.0.1:8765',target:'_blank',rel:'noopener noreferrer',text:'打开现有 AI 原型 ↗'})])])])];}

function video(){const cameras=state.data.cameras;const camera=cameras.find(c=>c.id===state.camera)||cameras[0];const summary=camera?.summary;
  const behaviors={normal_activity:'正常活动',reduced_activity:'活动减少',feeding:'摄食',feeding_anomaly:'摄食异常',unknown:'未知'};
  const anomalies={suspected_lesion:'疑似病灶',surface_anomaly:'体表异常',suspected_dead:'疑似死亡个体'};
  return [el('div',{class:'video-layout'},[
    card('监控预览','未播放任何视频流。',[videoPlaceholder(),el('div',{class:'card-foot'},[el('span',{text:camera?.name||'无设备'}),badge('视频未接入','neutral')])]),
    el('div',{class:'side-stack'},[card('监测设备','视觉与水质共享设备和时间窗。',[el('div',{class:'camera-list'},cameras.map(c=>button(c.name,()=>{state.camera=c.id;render();},state.camera===c.id?'selected':'secondary')))]),
      card('视觉数据状态','统计来自模拟器，不是真实 NPU 推理。',[rows([['来源',sourceName(camera?.source_kind)],['上报状态',connectionName(camera?.status)],['新鲜度',freshnessNames[camera?.freshness]||'未知'],['检测信号',camera?.signal_status==='no_obvious_anomaly'?'未出现所列异常信号（模拟）':camera?.signal_status==='suspected_anomaly'?'疑似异常（模拟，非确诊）':'暂无信号'],['观测时间',timeText(camera?.observed_at)],['接收时间',timeText(camera?.received_at)]])])])]),
    ...(summary?[card('疾病与异常检测信号','窗口内出现该信号的帧数；类别可重叠，不能作为最终疾病诊断。',[
      badge('SIMULATOR · 非诊断','demo'),rows(Object.entries(anomalies).map(([key,label])=>[label,`${summary.anomaly_counts[key]} / ${summary.frames_processed} 帧`]))]),
      card('行为识别','窗口内帧比例，不是绝对行为结论。',[rows(Object.entries(behaviors).map(([key,label])=>[label,`${(summary.behavior_ratios[key]*100).toFixed(1)}%`]))]),
      card('体长与可见数量','无标定时不显示厘米值；可见鱼数不代表鱼池存量。',[rows([
        ['平均体长',summary.length.average_length_cm===null?'不可测量':`${summary.length.average_length_cm} cm（模拟标定）`],
        ['有效体长样本',summary.length.length_sample_count],['标定',summary.length.calibration==='uncalibrated'?'未标定':'纯模拟标定'],
        ['画面平均可见数',summary.visible_fish_count??'缺失'],['模型版本',summary.model_version],['窗口开始',timeText(camera.window?.start)],
        ['窗口结束',timeText(camera.window?.end)],['关联批次',camera.batch_id]])])]
      :[card('视觉窗口汇总','没有补造另一通道数据。',[empty('NO_DATA · 暂无视觉上报','启动模拟器后显示窗口统计；不会生成假录像。','camera')])])];}

function events(){const filters=state.eventFilters;const body=el('div',{id:'events-table'},[eventsTable(filterItems(state.data.events,filters))]);const update=()=>body.replaceChildren(eventsTable(filterItems(state.data.events,filters)));
  return [el('div',{class:'filters'},[search('搜索事件',filters.q,v=>{filters.q=v;update();}),select('事件等级',[['','全部等级'],['warning','提醒'],['info','信息']],filters.severity,v=>{filters.severity=v;update();}),
    select('处理状态',[['','全部状态'],['pending','当前信号 / 待处理'],['closed','已消退 / 已处理']],filters.status,v=>{filters.status=v;update();}),button('重置筛选',()=>{state.eventFilters={q:'',severity:'',status:''};render();})]),
    card('事件列表',`${state.data.events.length} 条记录 · 模拟信号，不具备生产处理工作流`,[body]),
    el('p',{class:'footnote',text:'R1 仅提供查询与详情。事件处理、截图和视频片段存储尚未实现。'})];}

function knowledge(){const filters=state.fileFilters;const list=()=>table(['文件','分类','来源','索引状态','操作'],filterItems(state.data.files,filters),item=>[
  el('div',{class:'table-title'},[el('strong',{text:item.name}),el('small',{text:`${item.format} · DEMO 元数据`})]),item.category,'独立 Demo',badge('未建立','neutral')],fileDetail);
  const body=el('div',{},[list()]);const update=()=>body.replaceChildren(list());
  return [el('div',{class:'knowledge-banner'},[icon('book'),el('div',{},[el('h2',{text:'资料管理 ≠ 知识检索'}),el('p',{text:'原始文件、文件元数据、索引任务和 AI 检索分别管理。R1 没有上传或建立新 RAG。'})])]),
    el('div',{class:'filters'},[search('搜索资料',filters.q,v=>{filters.q=v;update();}),select('分类',[['','全部分类'],['养殖资料','养殖资料'],['设备说明','设备说明']],filters.category,v=>{filters.category=v;update();}),
      el('button',{class:'button secondary',disabled:'disabled',text:'上传文件 · 未实现'})]),card('资料列表','演示条目不对应可下载文件。',[body])];}

function settings(){const sections=[['devices','设备与数据源','设备通信、数据库与来源映射由服务适配器提供。'],['models','AI 模型配置','模型、凭据和执行合同继续由现有 AI Runtime 负责。'],
  ['rules','告警规则','尚未接入管理配置，不在网页中复制或修改诊断阈值。'],['users','用户与权限','未实现身份认证、账户或角色授权。'],['system','系统信息','R1 · Flask + 原生 ES Modules · 独立本地应用。']];
  const selected=sections.find(s=>s[0]===state.settings);
  return [el('div',{class:'settings-layout'},[el('div',{class:'card settings-nav'},sections.map(([id,label])=>button(label,()=>{state.settings=id;render();},state.settings===id?'selected':'text'))),
    card(selected[1],'管理员配置区域',[el('p',{class:'settings-description',text:selected[2]}),badge('只读 / 尚未接入','neutral'),rows([['认证状态','未启用'],['配置保存','不可用'],['生产连接','未接入']]),
      el('button',{class:'button secondary',disabled:'disabled',text:'配置操作尚未开放'})])]),
    card('开发者功能','不属于管理员生产权限。',[el('p',{class:'muted',text:'当前只有独立 Demo 视图。原 Prototype 的模型验证、Tool Trace 和实验界面继续留在开发应用，不作为管理后台权限系统。'})])];}

const pages={dashboard,monitoring,assistant,video,events,knowledge,settings};
function render(passive=false){if(!state.data)return;if(state.readFailed){$('content').replaceChildren(empty('读取失败 · 上次显示已失效','请恢复服务器连接，不将缓存当作当前数据。'));return;}const route=routeFor(location.hash);$('page-title').textContent=route.title;$('page-eyebrow').textContent=route.eyebrow;$('page-description').textContent=route.description;$('breadcrumb').textContent=route.title;
  document.title=`${route.title} · 鱼境`;$('content').replaceChildren(...pages[route.id]());
  document.querySelectorAll('#navigation a').forEach(a=>{const active=a.hash===`#${route.id}`;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  if(!passive){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}}
let refreshing=false;
async function refresh(force=false){
  if(refreshing&&!force)return;
  const revision=state.revision,device=state.device;
  refreshing=true;
  try{
    const data=validateBootstrap(await services.bootstrap(state.data?device:undefined));
    if(revision!==state.revision)return;
    if(data.data_mode==='demo'&&state.view!=='available')data.monitoring=await services.monitoring(device,state.view);
    if(revision!==state.revision)return;
    const recovered=state.readFailed;state.readFailed=false;state.data=data;
    if(!data.devices.some(d=>d.id===state.device))state.device=data.devices[0]?.id||'';
    if(!data.cameras.some(c=>c.id===state.camera))state.camera=data.cameras[0]?.id||'';
    $('source-label').textContent=sourceName(data.data_mode);
    $('source-notice').textContent=data.data_mode==='simulator'?'水质与视觉来自模拟器 HTTP 上报，非真实设备或疾病诊断。页面每 5 秒读取统一存储；AI 尚未接入。':'独立 R1 Demo；不是传感器、NPU 或正式 AI 数据。';
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
window.addEventListener('pagehide',()=>{clearInterval(poll);poll=null;});
window.addEventListener('pageshow',()=>{startPolling();});
