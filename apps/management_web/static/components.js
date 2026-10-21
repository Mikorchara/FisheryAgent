import {metricText,chartGeometry,normalizedChartGeometry,trendMetrics,timeText,qualityNames,freshnessNames,sourceName,connectionName} from './view-model.js';

export function el(tag,attrs={},children=[]) {
  const node=document.createElement(tag);
  for (const [key,value] of Object.entries(attrs)) {
    if (key==='text') node.textContent=value;
    else if (key==='class') node.className=value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2),value);
    else if (value!==null && value!==undefined) node.setAttribute(key,String(value));
  }
  for (const child of children) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
const shapes={grid:['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
  drop:['M12 3C8 8 5 11 5 15a7 7 0 0 0 14 0c0-4-3-7-7-12Z','M8 15a4 4 0 0 0 4 4'],
  spark:['m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8Z'],
  camera:['M3 6h12v12H3z M15 10l6-4v12l-6-4'],bell:['M5 16h14l-2-3V9a5 5 0 0 0-10 0v4z M10 20h4'],
  book:['M3 4h7l2 2 2-2h7v16h-7l-2 1-2-1H3z M12 6v15'],
  settings:['M4 7h16 M4 17h16 M8 4v6 M16 14v6'],arrow:['M4 12h16 m-6-6 6 6-6 6'],
  thermometer:['M10 4a2 2 0 0 1 4 0v10a4 4 0 1 1-4 0Z M12 7v11'],wave:['M2 10c4-6 6 6 10 0s6 6 10 0 M2 17c4-6 6 6 10 0s6 6 10 0'],
  link:['M10 8 8 6a4 4 0 0 0-6 6l3 3 M14 16l2 2a4 4 0 0 0 6-6l-3-3 M8 12h8'],file:['M5 3h9l5 5v13H5z M14 3v5h5 M8 13h8 M8 17h6']};
export function icon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  for(const [k,v] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':1.6,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
  for(const d of shapes[name]||shapes.grid){const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',d);svg.append(p);}
  return svg;
}
export function badge(text,tone='neutral'){return el('span',{class:`badge ${tone}`,text});}
export function card(title,sub,children=[],action=null){return el('section',{class:'card'},[
  el('div',{class:'card-heading'},[el('div',{},[el('h2',{text:title}),sub?el('p',{text:sub}):'']),action||'']),...children]);}
export function empty(title,description,symbol='link'){return el('div',{class:'empty-state'},[
  el('span',{class:'empty-icon'},[icon(symbol)]),el('h3',{text:title}),el('p',{text:description})]);}
export function button(text,onclick,tone='secondary'){return el('button',{class:`button ${tone}`,type:'button',onclick,text});}
export function link(text,route){return el('a',{class:'text-link',href:`#${route}`},[text,icon('arrow')]);}
export function rows(items){return el('dl',{class:'details-grid'},items.flatMap(([name,value])=>[el('dt',{text:name}),el('dd',{text:value??'暂无'})]));}
export function metricCards(snapshot){return el('div',{class:'metric-grid'},(snapshot?.metrics||[]).map((metric,i)=>el('section',{class:'metric-card'},[
  el('div',{class:'metric-heading'},[el('span',{text:metric.label}),el('span',{class:`metric-icon tone-${i}`},[icon(i===0?'thermometer':i===1?'wave':'drop')])]),
  el('div',{class:'metric-value'},[metricText(metric),el('span',{text:metric.unit})]),
  el('div',{class:'metric-footer'},[badge(qualityNames[metric.quality]||'未知',metric.quality==='valid'?'success':'warning'),el('span',{text:snapshot.aggregation==='window_mean'?'窗口均值':'Demo 观测'})])])));}
export function metadata(snapshot){return el('div',{class:'observation-meta'},[
  badge(sourceName(snapshot?.source_kind),'demo'),el('span',{text:snapshot?.source||'无数据来源'}),badge(connectionName(snapshot?.connectivity),'neutral'),
  badge(qualityNames[snapshot?.quality]||'不可用',snapshot?.quality==='valid'?'success':'warning'),
  badge(freshnessNames[snapshot?.freshness]||'未知',snapshot?.freshness==='fresh'?'success':'warning'),
  el('span',{text:`观测 ${timeText(snapshot?.observed_at)}`})]);}
export function table(columns,items,rowValues,onDetail){
  const body=el('tbody');
  items.forEach(item=>{const values=rowValues(item);body.append(el('tr',{},[...values.map(v=>el('td',{},[v instanceof Node?v:String(v??'—')])),
    ...(onDetail?[el('td',{},[button('查看详情',()=>onDetail(item),'text')])]:[])]));});
  if(!items.length)body.append(el('tr',{},[el('td',{colspan:columns.length,text:'没有符合条件的记录。',class:'table-empty'})]));
  return el('div',{class:'table-scroll'},[el('table',{},[el('thead',{},[el('tr',{},columns.map(c=>el('th',{scope:'col',text:c})))]),body])]);
}
export function trendChart(snapshot,key,{rangeSeconds=1800}={}){
  const data=chartGeometry(snapshot?.trend||[],key,{rangeSeconds});
  if(!data)return empty('暂无可展示的趋势','所选范围至少需要两个不同观测时间的有效窗口；缺失值不会补成正常数据。','wave');
  const metric=trendMetrics.find(item=>item.key===key)||{key,label:key,unit:'',color:'#168c83',dash:''};
  return drawTrend(snapshot,data,[{...metric,color:'#168c83',dash:'',data}],false,rangeSeconds);
}
export function normalizedTrendChart(snapshot,{rangeSeconds=1800}={}){
  const data=normalizedChartGeometry(snapshot?.trend||[],{rangeSeconds});
  if(!data)return empty('暂无可比较的趋势','每项指标至少需要两个不同观测时间的有效窗口；缺失/无效值不参与归一化。','wave');
  return drawTrend(snapshot,data,data.series,true);
}
function drawTrend(snapshot,data,series,normalized,rangeSeconds=null){
  const format=value=>new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:8}).format(value);
  const rawValue=(row,metric)=>typeof row[metric.key]==='number'&&Number.isFinite(row[metric.key])
    &&(!row.metric_quality?.[metric.key]||row.metric_quality[metric.key]==='valid')
    ? `${format(row[metric.key])}${metric.unit==='无单位'?'（无单位）':metric.unit?' '+metric.unit:''}`:'不可用';
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 780 276');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');
  svg.setAttribute('aria-label',normalized?'三指标归一化趋势，0至100仅比较趋势；左右方向键查看原始值':'服务器历史窗口均值，保留来源标识；左右方向键查看原始值');svg.classList.add('trend-chart');
  const append=(tag,attrs,text,parent=svg)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;parent.append(n);return n;};
  append('text',{x:52,y:28,fill:'#71848f','font-size':11},normalized?'归一化值（0–100，非适宜度）':`${series[0].label}${series[0].unit?' · '+series[0].unit:''}`);
  for(const tick of data.yTicks){
    append('line',{x1:52,y1:tick.y,x2:742,y2:tick.y,stroke:'#e6edf0','stroke-dasharray':'4 5'});
    append('text',{x:44,y:tick.y+4,fill:'#81919a','font-size':11,'text-anchor':'end'},tick.label);
  }
  for(const item of series){
    if(!item.data)continue;
    const points=item.data.points;
    // Short views emphasize individual observations. Combined/long views keep
    // the existing small points; tight time clusters still reduce all markers.
    const radius=normalized?1.35:rangeSeconds===300?2.5:rangeSeconds===600?2:1.35;
    const longView=rangeSeconds===null||rangeSeconds>=3600;
    const dense=((normalized||longView)&&points.length>120)
      ||points.some((point,i)=>i&&point[0]-points[i-1][0]<(normalized?2.5:Math.max(2.5,radius*2+.5)));
    for(const segment of item.data.segments){const path=segment.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
      append('path',{d:path,fill:'none',stroke:item.color,'stroke-width':2,'stroke-dasharray':item.dash,'vector-effect':'non-scaling-stroke','data-metric':item.key,class:'trend-line'});}
    points.forEach(([x,y],i)=>{
      const dot=append('circle',{cx:x,cy:y,r:dense?0.65:radius,fill:item.color,opacity:dense?0.4:0.85,class:'trend-marker','data-metric':item.key});
      append('title',{},`${timeText(item.data.rows[i].observed_at)} · ${item.label}：${rawValue(item.data.rows[i],item)}`,dot);
    });
  }
  data.xTicks.forEach((tick,i)=>{
    const attrs={x:tick.x,y:241,fill:'#81919a','font-size':11,'text-anchor':i===0?'start':i===data.xTicks.length-1?'end':'middle'};
    append('text',attrs,tick.label);
    if(tick.date)append('text',{...attrs,y:258},tick.date);
  });
  // A single nearest-time cursor keeps dense clusters inspectable without large,
  // overlapping hit circles. Values always come from one actual stored row.
  const samples=new Map();for(const item of series)for(const row of item.data?.rows||[])samples.set(Date.parse(row.observed_at),row);
  const records=[...samples].sort((a,b)=>a[0]-b[0]);
  const focus=append('g',{visibility:'hidden','pointer-events':'none',class:'chart-cursor'});
  const cursor=append('line',{x1:52,x2:52,y1:53,y2:208,stroke:'#92a6ae','stroke-dasharray':'3 4'},null,focus);
  const highlights=series.map(item=>({item,positions:new Map((item.data?.rows||[]).map((row,i)=>[Date.parse(row.observed_at),item.data.points[i]])),
    dot:append('circle',{r:4,fill:'#fff',stroke:item.color,'stroke-width':2,'vector-effect':'non-scaling-stroke',visibility:'hidden',class:'chart-highlight'},null,focus)}));
  const tooltip=el('div',{class:'chart-tooltip',role:'status','aria-live':'polite',hidden:''});
  let selected=-1;
  const show=index=>{
    index=Math.max(0,Math.min(records.length-1,index));
    const [time,row]=records[index],x=52+(time-data.start)/(data.end-data.start)*690;
    selected=index;cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);focus.setAttribute('visibility','visible');
    for(const {positions,dot} of highlights){const point=positions.get(time);dot.setAttribute('visibility',point?'visible':'hidden');
      if(point){dot.setAttribute('cx',point[0]);dot.setAttribute('cy',point[1]);}}
    tooltip.replaceChildren(el('strong',{text:timeText(row.observed_at)}),...series.map(item=>el('div',{class:'chart-tooltip-row'},[
      el('span',{class:`trend-swatch trend-${item.key}`}),el('span',{text:`${item.label}：${rawValue(row,item)}`})])));
    tooltip.removeAttribute('hidden');
  };
  const hide=()=>{focus.setAttribute('visibility','hidden');tooltip.setAttribute('hidden','');};
  const pointer=event=>{
    const box=svg.getBoundingClientRect();let x=(event.clientX-box.left)*780/box.width;
    const y=(event.clientY-box.top)*276/box.height;
    // Edge markers extend past the plot, and CSS pixel rounding can move a
    // pointer just outside it. Keep endpoints inspectable at every viewport.
    if(x<46||x>748||Number.isFinite(y)&&(y<47||y>214)){hide();return;}
    if(!Number.isFinite(x))return;
    x=Math.max(52,Math.min(742,x));
    const time=data.start+(x-52)/690*(data.end-data.start);
    let nearest=0;for(let i=1;i<records.length;i++)if(Math.abs(records[i][0]-time)<Math.abs(records[nearest][0]-time))nearest=i;
    show(nearest);
  };
  svg.addEventListener('pointermove',pointer);svg.addEventListener('pointerdown',pointer);
  svg.addEventListener('pointerleave',()=>{if(document.activeElement!==svg)hide();});
  svg.addEventListener('focus',()=>show(selected<0?0:selected));svg.addEventListener('blur',hide);
  svg.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End','Escape'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Escape'){hide();return;}
    show(event.key==='Home'?0:event.key==='End'?records.length-1:Math.max(0,selected)+(event.key==='ArrowRight'?1:-1));
  });
  return el('div',{class:'chart-container','data-chart':normalized?'normalized':'single'},[
    ...(normalized?[el('div',{class:'trend-legend'},series.map(item=>el('span',{},[
      el('span',{class:`trend-swatch trend-${item.key}`}),el('span',{text:item.label+(!item.data?'（有效窗口不足）':item.constant?'（无变化，50）':'')})])))]:[]),
    el('div',{class:'chart-viewport'},[svg]),tooltip,
    ...(normalized?[el('p',{class:'chart-note normalization-note',text:'各指标在所选范围内独立归一化：(原值−最小值)/(最大值−最小值)×100；无变化为50。仅比较趋势，不能比较原始大小、实际变化幅度或水质适宜度；切换范围或新极值会重算刻度。'})]:[]),
    el('p',{class:'chart-note',text:'悬停或点击图中位置查看原始值；键盘聚焦图表后可用 ← / → 查看，Esc 关闭提示。'}),
    el('p',{class:'chart-note',text:`北京时间 UTC+8 · ${timeText(new Date(data.start).toISOString())} — ${timeText(new Date(data.end).toISOString())}`}),
    el('p',{class:'chart-note',text:`${snapshot?.source_kind==='simulator'?'模拟上报窗口':'独立 R1 Demo 历史'} · 显示 ${data.displayedCount} / ${data.storedCount} 个存储窗口 · 范围以最后观测为终点，非当前实时数据。会话切换、缺失和中断处不连线。${data.duplicateCount?`同时间记录仅展示最后接收项（${data.duplicateCount} 项折叠）。`:''}${data.invalidTimeCount?`已忽略 ${data.invalidTimeCount} 项无效时间。`:''}`})]);
}
