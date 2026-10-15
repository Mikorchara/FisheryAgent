// Pure display functions, no source routing or Diagnosis thresholds.
export const routes = [
  {id:'dashboard',title:'综合总览',label:'首页 / 综合总览',eyebrow:'OVERVIEW',icon:'grid',description:'从数据到决策，了解养殖环境的每一个环节。'},
  {id:'monitoring',title:'水质监测',label:'水质监测',eyebrow:'WATER QUALITY',icon:'drop',description:'查看指标、观测来源与数据质量。查询不等于重新采样。'},
  {id:'assistant',title:'AI 智能助手',label:'AI 智能助手',eyebrow:'AI ASSISTANT',icon:'spark',description:'Normal 对话与只读水质查询；系统事实来自统一监测服务。'},
  {id:'video',title:'视频监控',label:'视频监控',eyebrow:'VIDEO MONITORING',icon:'camera',description:'统一查看监控设备、视频接入及检测服务状态。'},
  {id:'events',title:'事件记录',label:'事件记录',eyebrow:'EVENT RECORDS',icon:'bell',description:'按时间、来源与等级查看事件；演示记录不代表真实告警。'},
  {id:'knowledge',title:'资料与知识库',label:'资料与知识库',eyebrow:'KNOWLEDGE & FILES',icon:'book',description:'管理资料元数据与索引状态，文件管理与 AI 检索保持分离。'},
  {id:'settings',title:'系统设置',label:'系统设置',eyebrow:'SYSTEM SETTINGS',icon:'settings',description:'了解设备、模型、规则及权限的配置边界。'},
];
export function routeFor(hash) { return routes.find(r=>r.id===hash.replace(/^#/,'')) || routes[0]; }
export const qualityNames={valid:'有效',partial:'部分缺失',invalid:'无效',missing:'不可用'};
export const freshnessNames={fresh:'新鲜',stale:'已过期',unknown:'未知'};
export function sourceName(kind){return ({simulator:'SIMULATOR 模拟来源',demo:'DEMO 演示',connected:'已接入',mixed:'混合来源'})[kind]||'未声明来源';}
export function connectionName(status){return ({online:'正常上报',offline:'上报中断',never_received:'尚无上报',not_connected:'未接入',connected:'已装配',demo:'演示'})[status]||'状态未知';}
export function eventState(item){return item.lifecycle_state||(item.status==='closed'?'RESOLVED':'ACTIVE');}
export function eventStateName(item){return ({ACTIVE:'异常持续',RESOLVED:'已确认消退',INDETERMINATE:'状态待确认'})[eventState(item)]||'状态未知';}
export function eventSeverityName(item){return ({critical:'严重',warning:'提醒',info:'信息'})[item.severity]||'未知';}
export function metricText(metric) {
  return typeof metric?.value==='number' && Number.isFinite(metric.value) && metric.quality==='valid'
    ? metric.value.toFixed(1) : '—';
}
export function timeText(value,compact=false) {
  if (!value || !Number.isFinite(Date.parse(value))) return '暂无时间';
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',...(compact?{}:{year:'numeric',month:'2-digit',day:'2-digit'}),hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(value))+(compact?'':' 北京时间');
}
export function chartSeries(trend,key) {
  return trend.filter(p=>typeof p[key]==='number' && Number.isFinite(p[key]));
}
export function chartGeometry(trend,key) {
  const rows=chartSeries(trend,key); if (rows.length<2) return null;
  const values=rows.map(p=>p[key]), low=Math.min(...values), high=Math.max(...values), pad=Math.max((high-low)*.4,.1);
  const times=rows.map(r=>Date.parse(r.observed_at)),timed=times.every(Number.isFinite)&&times.at(-1)>times[0];
  const points=values.map((v,i)=>[52+(timed?(times[i]-times[0])/(times.at(-1)-times[0]):i/(values.length-1))*690,208-(v-low+pad)/(high-low+2*pad)*155]);
  const segments=[];
  rows.forEach((row,i)=>{const gap=i>0&&(trend.indexOf(row)!==trend.indexOf(rows[i-1])+1||(timed&&row.window_duration_s&&(times[i]-times[i-1])/1000>row.window_duration_s+.01));if(i===0||gap)segments.push([]);segments.at(-1).push(points[i]);});
  return {points,segments,low:low-pad,high:high+pad,rows};
}
export function filterItems(items,{q='',category='',severity='',status=''}={}) {
  return items.filter(item=>(!q || [item.name,item.title,item.device,item.category].filter(Boolean).join(' ').toLowerCase().includes(q.toLowerCase()))
    && (!category || item.category===category) && (!severity || item.severity===severity) && (!status || item.status===status || item.lifecycle_state===status));
}
export function validateBootstrap(data) {
  if (data?.schema_version!==1 || data.application!=='management-web-r1' || !['demo','simulator','connected','mixed'].includes(data.data_mode)
    || !Array.isArray(data.devices) || !Array.isArray(data.events) || !Array.isArray(data.files)
    || !Array.isArray(data.cameras) || !Array.isArray(data.connections) || typeof data.ai?.connected!=='boolean') throw new Error('INVALID_MANAGEMENT_DATA');
  return data;
}
