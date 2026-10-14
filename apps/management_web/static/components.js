import {metricText,chartGeometry,timeText,qualityNames,freshnessNames,sourceName,connectionName} from './view-model.js';

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
export function trendChart(snapshot,key){
  const data=chartGeometry(snapshot?.trend||[],key);
  if(!data)return empty('暂无可展示的趋势','至少需要两个有效窗口，缺失值不会补成正常数据。','wave');
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 780 258');svg.setAttribute('role','img');svg.setAttribute('aria-label','服务器历史窗口均值，保留来源标识');svg.classList.add('trend-chart');
  const append=(tag,attrs,text)=>{const n=document.createElementNS(svg.namespaceURI,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text)n.textContent=text;svg.append(n);};
  for(let i=0;i<4;i++){const y=53+i*52;append('line',{x1:52,y1:y,x2:742,y2:y,stroke:'#e6edf0','stroke-dasharray':'4 5'});append('text',{x:9,y:y+4,fill:'#81919a','font-size':11},(data.high-i/3*(data.high-data.low)).toFixed(1));}
  for(const segment of data.segments){const path=segment.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');append('path',{d:path,fill:'none',stroke:'#168c83','stroke-width':2.8});}
  for(const[x,y]of data.points)append('circle',{cx:x,cy:y,r:3,fill:'#fff',stroke:'#168c83','stroke-width':1.8});
  [0,3,7,11].forEach(i=>append('text',{x:data.points[Math.min(i,data.points.length-1)][0],y:241,fill:'#81919a','font-size':11,'text-anchor':'middle'},timeText(data.rows[Math.min(i,data.rows.length-1)].observed_at,true)));
  return el('div',{class:'chart-container'},[svg,el('p',{class:'chart-note',text:'北京时间 UTC+8 · '+(snapshot?.source_kind==='simulator'?'模拟上报窗口 · 有界历史 · 非真实设备':'独立 R1 Demo 历史')})]);
}
