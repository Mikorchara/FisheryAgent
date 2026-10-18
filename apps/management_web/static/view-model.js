// Pure display functions, no source routing or Diagnosis thresholds.
export const routes = [
  {id:'dashboard',title:'综合总览',label:'首页 / 综合总览',eyebrow:'OVERVIEW',icon:'grid',description:'从数据到决策，了解养殖环境的每一个环节。'},
  {id:'monitoring',title:'水质监测',label:'水质监测',eyebrow:'WATER QUALITY',icon:'drop',description:'查看指标、观测来源与数据质量。查询不等于重新采样。'},
  {id:'assistant',title:'AI 智能助手',label:'AI 智能助手',eyebrow:'AI ASSISTANT',icon:'spark',description:'围绕监测事实与项目知识对话；当前数据来自统一监测服务。'},
  {id:'video',title:'视频监控',label:'视频监控',eyebrow:'VIDEO MONITORING',icon:'camera',description:'统一查看监控设备、视频接入及检测服务状态。'},
  {id:'events',title:'事件记录',label:'事件记录',eyebrow:'EVENT RECORDS',icon:'bell',description:'按时间、来源与等级查看事件；演示记录不代表真实告警。'},
  {id:'knowledge',title:'资料与知识库',label:'资料与知识库',eyebrow:'KNOWLEDGE & FILES',icon:'book',description:'维护项目知识内容、版本与来源，供 AI 只读检索。'},
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
  return trend.filter(p=>typeof p[key]==='number' && Number.isFinite(p[key])
    && (!p.metric_quality?.[key]||p.metric_quality[key]==='valid'));
}
function timeTicks(start,end) {
  const fractional=end-start<4000;
  const day=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit'}).format(value);
  const crossDay=day(start)!==day(end);
  const format=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',
    hourCycle:'h23',...(fractional?{fractionalSecondDigits:3}:{})});
  // Uniform time ticks, never the first few sample indices. Five slots leave
  // enough room for seconds/milliseconds even at the minimum chart width.
  const count=Math.min(5,end-start+1);
  return Array.from({length:count},(_,i)=>{const time=Math.round(start+(end-start)*i/(count-1));
    return {x:52+690*(time-start)/(end-start),time,label:format.format(time),date:crossDay?day(time):null};});
}
export function chartGeometry(trend,key,{rangeSeconds=null}={}) {
  // Parse real timestamps first. Invalid time never receives an invented index.
  const timestamp=value=>typeof value==='string'?Date.parse(value):NaN;
  const ordered=trend.map((row,index)=>({row,index,time:timestamp(row.observed_at),received:timestamp(row.received_at)}))
    .filter(item=>Number.isFinite(item.time))
    .sort((a,b)=>a.time-b.time||(Number.isFinite(a.received)?a.received:0)-(Number.isFinite(b.received)?b.received:0)
      ||String(a.row.batch_id||'').localeCompare(String(b.row.batch_id||''))||a.index-b.index);
  if(!ordered.length)return null;
  // Same-time records cannot be joined vertically or averaged. Display the last
  // received record (even if missing/invalid); keep original server history intact.
  const unique=new Map();for(const item of ordered)unique.set(item.time,item);
  const latest=ordered.at(-1).time;
  const cutoff=Number.isFinite(rangeSeconds)&&rangeSeconds>0?latest-rangeSeconds*1000:-Infinity;
  const selected=[...unique.values()].filter(item=>item.time>=cutoff);
  const valid=chartSeries(selected.map(item=>item.row),key);
  if(valid.length<2)return null;
  const rows=valid,times=rows.map(row=>timestamp(row.observed_at));
  const start=selected[0].time,end=selected.at(-1).time;
  if(end<=start)return null;
  const values=rows.map(row=>row[key]),min=Math.min(...values),max=Math.max(...values);
  const pad=Math.max((max-min)*.15,.05),rough=(max-min+2*pad)/3,power=10**Math.floor(Math.log10(rough));
  const step=([1,2,5,10].find(n=>n*power>=rough)||10)*power;
  const low=Math.floor((min-pad)/step)*step,high=Math.ceil((max+pad)/step)*step;
  const precision=Math.max(0,Math.min(6,-Math.floor(Math.log10(step))));
  const y=value=>208-(value-low)/(high-low)*155;
  const points=values.map((value,i)=>[52+(times[i]-start)/(end-start)*690,y(value)]);
  const yTicks=Array.from({length:Math.round((high-low)/step)+1},(_,i)=>{
    const value=low+i*step;return {y:y(value),label:(Math.abs(value)<step/100?0:value).toFixed(precision)};});
  const positions=new Map(selected.map((item,i)=>[item.row,i])),segments=[];
  rows.forEach((row,i)=>{
    const previous=rows[i-1],windowStart=timestamp(row.window_start);
    const duration=typeof row.window_duration_s==='number'&&row.window_duration_s>0?row.window_duration_s*1000:null;
    const gap=i>0&&(positions.get(row)!==positions.get(previous)+1
      ||(row.session_id&&previous.session_id&&row.session_id!==previous.session_id)
      ||(Number.isFinite(windowStart)?windowStart>times[i-1]+10:duration!==null&&times[i]-times[i-1]>duration+10));
    if(i===0||gap)segments.push([]);segments.at(-1).push(points[i]);
  });
  return {points,segments,low,high,rows,yTicks,xTicks:timeTicks(start,end),start,end,
    duplicateCount:ordered.length-unique.size,invalidTimeCount:trend.length-ordered.length,
    storedCount:trend.length,displayedCount:rows.length};
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
