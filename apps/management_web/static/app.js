import {el,icon,card,badge,empty,button,link,rows,metricCards,metadata,table,trendChart} from './components.js';
import {routes,routeFor,timeText,filterItems,validateBootstrap,qualityNames,freshnessNames} from './view-model.js';
import {services} from './services.js';

const $=id=>document.getElementById(id);
const state={data:null,device:'demo-a',view:'available',metric:'dissolved_oxygen_mg_l',camera:'demo-camera-a',
  eventFilters:{q:'',severity:'',status:''},fileFilters:{q:'',category:''},settings:'devices',draft:'',revision:0};
const severity=item=>badge(item.severity==='warning'?'提醒':'信息',item.severity==='warning'?'warning':'neutral');
const status=item=>badge(item.status==='pending'?'待处理（演示）':'已处理（演示）',item.status==='pending'?'warning':'neutral');

function select(label,choices,value,onchange){return el('label',{class:'field'},[el('span',{text:label}),el('select',{onchange:e=>onchange(e.target.value)},
  choices.map(([id,text])=>el('option',{value:id,...(id===value?{selected:'selected'}:{})},[text])))]);}
function search(label,value,oninput){return el('label',{class:'field search-field'},[el('span',{text:label}),el('input',{type:'search',value,placeholder:'输入名称或关键字',oninput:e=>oninput(e.target.value)})]);}
function details(title,content){$('dialog-title').textContent=title;$('dialog-body').replaceChildren(...content);$('details-dialog').showModal();}
function eventDetail(item){details(item.title,[badge('DEMO','demo'),rows([['记录编号',item.id],['时间',timeText(item.occurred_at)],['设备',item.device],['类型',item.type],['等级',item.severity==='warning'?'提醒':'信息'],['处理状态',item.status==='pending'?'待处理（演示）':'已处理（演示）']]),el('p',{text:item.description}),
  empty('暂无关联媒体','这里将展示关联截图与视频片段；R1 未生成或保存媒体。','camera')]);}
function fileDetail(item){details(item.name,[badge('DEMO','demo'),rows([['分类',item.category],['格式',item.format],['来源',item.source],['索引状态','未建立'],['文件大小','未上传'],['检索能力','未接入']]),el('p',{text:item.description}),el('button',{class:'button secondary',disabled:'disabled',text:'下载不可用 · 演示元数据'})]);}
function eventsTable(items){return table(['事件 / 类型','设备','时间','等级','状态','操作'],items,item=>[
  el('div',{class:'table-title'},[el('strong',{text:item.title}),el('small',{text:`${item.id} · ${item.type} · DEMO`})]),item.device,timeText(item.occurred_at),severity(item),status(item)],eventDetail);}

function trend(){return card('历史趋势','演示观测序列，不用于生产诊断。',[trendChart(state.data.monitoring,state.metric)],
  select('指标',[['dissolved_oxygen_mg_l','溶解氧'],['temperature_c','水温'],['ph','pH']],state.metric,value=>{state.metric=value;render();}));}
function videoPlaceholder(compact=false){return el('div',{class:`video-placeholder ${compact?'compact':''}`},[
  el('div',{class:'video-corner',text:'演示预览区域 / 无视频流'}),el('span',{class:'video-symbol'},[icon('camera')]),el('h3',{text:'等待接入监控设备'}),
  el('p',{text:'没有实时画面，也没有 NPU 推理结果。'}),badge('NOT CONNECTED','neutral')]);}

function dashboard(){
  const d=state.data, snapshot=d.monitoring;
  return [el('div',{class:'overview-strip'},[
    el('div',{},[el('span',{class:'strip-icon'},[icon('link')]),el('div',{},[el('strong',{text:'数据连接概况'}),el('small',{text:'独立 Demo adapter 已就绪'})])]),
    el('div',{class:'strip-number'},[el('strong',{text:'1'}),el('span',{text:'演示数据源'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'真实设备接入'})]),
    el('div',{class:'strip-number'},[el('strong',{text:'0'}),el('span',{text:'已连接 AI 服务'})]),badge('DEMO','demo')]),
    el('div',{class:'section-caption'},[el('h2',{text:'水质指标概览'}),link('查看水质监测','monitoring')]),metadata(snapshot),metricCards(snapshot),
    el('div',{class:'dashboard-grid'},[trend(),card('视频监控','设备与推理服务尚未连接。',[videoPlaceholder(true),el('div',{class:'card-foot'},[el('span',{text:'演示摄像头 A'}),link('设备预览','video')])])]),
    el('div',{class:'dashboard-grid bottom-grid'},[card('最近事件','以下为独立演示记录。',[eventsTable(d.events)],link('全部记录','events')),
      el('div',{class:'side-stack'},[card('AI 智能助手','从环境事实到可解释的辅助建议。',[el('div',{class:'assistant-entry'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('p',{text:'新工作区已就绪。AI 服务接入后，复用现有 Assistant 与 Tool Runtime。'}),el('a',{href:'#assistant',class:'button primary'},['打开助手工作区',icon('arrow')])])]),
        card('连接状态','未连接不代表设备离线。',[el('div',{class:'connection-list'},d.connections.map(c=>el('div',{class:'connection-row'},[
          el('span',{text:c.name}),badge(c.status==='demo'?'演示':'未接入',c.status==='demo'?'demo':'neutral')])))] )])])];
}

async function changeMonitoring(){
  const revision=++state.revision;
  try{const snapshot=await services.monitoring(state.device,state.view);if(revision!==state.revision)return;state.data.monitoring=snapshot;render();}
  catch(_){if(revision!==state.revision)return;$('content').replaceChildren(empty('数据暂不可用','未使用默认值替代数据。请重新选择演示状态。'));}
}
function monitoring(){const snapshot=state.data.monitoring;return [el('div',{class:'filters'},[
  select('观测区域',state.data.devices.map(d=>[d.id,d.name]),state.device,value=>{state.device=value;changeMonitoring();}),
  select('演示数据状态',[['available','可用'],['stale','过期'],['partial','部分缺失'],['invalid','无效'],['missing','无数据']],state.view,value=>{state.view=value;changeMonitoring();}),
  el('p',{class:'filter-hint',text:'只切换独立 Demo 视图，不采集或写入正式 Snapshot。'})]),metadata(snapshot),metricCards(snapshot),
  ...(snapshot?.quality==='valid'&&snapshot?.freshness==='fresh'?[]:[el('div',{class:'data-warning',text:`数据状态：${qualityNames[snapshot?.quality]||'不可用'} / ${freshnessNames[snapshot?.freshness]||'未知'}。请保留质量和时间信息，勿当作有效实时观测。`})]),
  trend(),card('观测信息','值与来源一起传递，不由前端重新诊断。',[rows([['来源',snapshot?.source],['来源类型',snapshot?.source_kind],['观测时间',timeText(snapshot?.observed_at)],['查询时间',timeText(snapshot?.evaluated_at)],['质量',qualityNames[snapshot?.quality]],['新鲜度',freshnessNames[snapshot?.freshness]]]),
    el('details',{class:'data-details'},[el('summary',{text:'查看演示趋势数据表'}),table(['观测时间','水温 °C','pH','溶解氧 mg/L'],snapshot?.trend||[],p=>[timeText(p.observed_at),p.temperature_c,p.ph,p.dissolved_oxygen_mg_l])])])];}

function assistant(){return [el('div',{class:'assistant-layout'},[
  el('section',{class:'card chat-shell'},[el('div',{class:'chat-top'},[el('div',{},[icon('spark'),el('strong',{text:'渔业助手'})]),badge('服务未接入','neutral')]),
    el('div',{class:'chat-messages'},[el('div',{class:'chat-welcome'},[el('span',{class:'assistant-emblem'},[icon('spark')]),el('h2',{text:'让问题有依据，让建议可追溯。'}),el('p',{text:'R1 先建立对话容器。接入后，消息与只读工具通过应用层服务执行，不在页面内运行模型。'}),
      el('div',{class:'suggestions'},['当前水质有哪些需要关注的指标？','如何理解溶解氧？','查找相关养殖资料'].map(text=>button(text,()=>{state.draft=text;$('assistant-draft').value=text;})))])]),
    el('div',{class:'chat-composer'},[el('label',{for:'assistant-draft',text:'消息草稿',class:'sr-only'}),el('textarea',{id:'assistant-draft',rows:3,placeholder:'可以编辑草稿；AI 服务接入后再发送。',text:state.draft,oninput:e=>{state.draft=e.target.value;}}),
      el('div',{class:'composer-foot'},[el('span',{text:'尚未连接 AI · 不会产生模型请求'}),el('button',{class:'button primary',disabled:'disabled',text:'发送 · 尚未接入'})])])]),
  el('div',{class:'side-stack'},[card('模型与响应','应用服务提供模型清单与执行状态。',[rows([['模型','尚未加载'],['响应模式','待接入 Normal / Streaming'],['运行状态','未连接']])]),
    card('工具执行','未来仅展示安全 Activity。',[empty('暂无执行记录','Tool 调用、步骤和来源证明将在服务接入后展示。','settings')]),
    card('开发验证','与管理平台的正式工作区分开。',[el('p',{class:'muted',text:'现有 AI Prototype Web 保留在独立端口，模型和凭据由原 Runtime 管理。'}),el('a',{class:'text-link',href:'http://127.0.0.1:8765',target:'_blank',rel:'noopener noreferrer',text:'打开现有 AI 原型 ↗'})])])])];}

function video(){const cameras=state.data.cameras;const camera=cameras.find(c=>c.id===state.camera)||cameras[0];return [el('div',{class:'video-layout'},[
  card('监控预览','演示占位，未播放任何视频流。',[videoPlaceholder(),el('div',{class:'card-foot'},[el('span',{text:camera?.name||'无设备'}),badge('视频未接入','neutral')])]),
  el('div',{class:'side-stack'},[card('监控设备','演示配置，不代表实际设备。',[el('div',{class:'camera-list'},cameras.map(c=>button(c.name,()=>{state.camera=c.id;render();},state.camera===c.id?'selected':'secondary')))]),
    card('检测服务','硬件推理与网页展示分离。',[rows([['计算板 / NPU','未接入'],['识别状态','无检测结果'],['数据来源','无实际检测包']])])])]),
  card('识别结果与告警','未来接入经规范化的检测事实。',[empty('暂无检测结果','不使用桌面 GPU 监测器代码，也不生成虚构识别框。','camera')])];}

function events(){const filters=state.eventFilters;const body=el('div',{id:'events-table'},[eventsTable(filterItems(state.data.events,filters))]);const update=()=>body.replaceChildren(eventsTable(filterItems(state.data.events,filters)));
  return [el('div',{class:'filters'},[search('搜索事件',filters.q,v=>{filters.q=v;update();}),select('事件等级',[['','全部等级'],['warning','提醒'],['info','信息']],filters.severity,v=>{filters.severity=v;update();}),
    select('处理状态',[['','全部状态'],['pending','待处理'],['closed','已处理']],filters.status,v=>{filters.status=v;update();}),button('重置筛选',()=>{state.eventFilters={q:'',severity:'',status:''};render();})]),
    card('事件列表',`${state.data.events.length} 条独立 Demo 记录 · 不具备生产处理工作流`,[body]),
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
function render(){if(!state.data)return;const route=routeFor(location.hash);$('page-title').textContent=route.title;$('page-eyebrow').textContent=route.eyebrow;$('page-description').textContent=route.description;$('breadcrumb').textContent=route.title;
  document.title=`${route.title} · 鱼境`;$('content').replaceChildren(...pages[route.id]());
  document.querySelectorAll('#navigation a').forEach(a=>{const active=a.hash===`#${route.id}`;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}
async function bootstrap(){try{state.data=validateBootstrap(await services.bootstrap());
  state.device=state.data.devices[0]?.id||'';state.camera=state.data.cameras[0]?.id||'';render();
}catch(_){$('content').replaceChildren(card('工作区暂不可用','没有使用假数据掩盖服务错误。',[empty('服务加载失败','请检查独立管理服务是否已启动。'),button('重新加载',bootstrap)]));}}
$('navigation').append(...routes.map(r=>el('a',{href:`#${r.id}`},[icon(r.icon),el('span',{text:r.label})])));
$('menu-toggle').addEventListener('click',()=>{$('sidebar').classList.toggle('open');$('menu-toggle').setAttribute('aria-expanded',String($('sidebar').classList.contains('open')));});
$('dialog-close').addEventListener('click',()=>$('details-dialog').close());
$('details-dialog').addEventListener('click',e=>{if(e.target===$('details-dialog'))$('details-dialog').close();});
window.addEventListener('hashchange',()=>{render();$('main').focus({preventScroll:true});window.scrollTo(0,0);});
document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();$('main').focus();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
document.addEventListener('click',event=>{if(!$('sidebar').contains(event.target)&&!$('menu-toggle').contains(event.target)){$('sidebar').classList.remove('open');$('menu-toggle').setAttribute('aria-expanded','false');}});
bootstrap();
