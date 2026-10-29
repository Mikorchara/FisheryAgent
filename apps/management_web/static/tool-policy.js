import {el,button,rows} from './components.js';

const labels={get_current_water_quality:'当前水质',search_fishery_knowledge:'项目养殖知识',
  get_water_quality_history:'历史水质（本地实验）',score_current_water_quality:'实验评分（兼容配置，无 Handler）'};

function validatePolicy(value){
  if(!value||typeof value.epoch!=='string'||typeof value.revision!=='string'||typeof value.browser_token!=='string'||
    !['INHERITED_SHARED_POLICY','MANAGEMENT_OVERRIDE'].includes(value.source)||
    !Array.isArray(value.selected_tools)||value.selected_tools.length>4||
    !value.selected_tools.every(name=>Object.hasOwn(labels,name))||new Set(value.selected_tools).size!==value.selected_tools.length||
    !Array.isArray(value.tools)||value.tools.length!==4||!value.tools.every(tool=>tool&&Object.hasOwn(labels,tool.name))||
    new Set(value.tools.map(tool=>tool.name)).size!==4)throw new Error('INVALID_TOOL_POLICY_RESPONSE');
  return value;
}

// Local development authorization only; publication/assembly remain server decisions.
export function createToolPolicySettings(api,{onSaved=()=>{}}={}){
  const root=el('div',{class:'tool-policy-panel'});let config=null,selected=new Set(),busy=false,loaded=false,message='';
  function render(){
    root.replaceChildren(el('p',{text:'本机开发授权，尚未实现生产账户权限。保存只影响管理 Assistant；不修改旧 Prototype 或 Analysis。'}),
      el('p',{class:'muted',text:'授权、工具装配和模型发布分别校验。服务器启用Qwen三工具本地试用后，模型在已授权工具中自行选择；普通聊天不需要历史查询快捷操作。未启用该试用时，历史不会进入原两工具范围。'}),
      ...(config?[rows([['选择来源',config.source==='MANAGEMENT_OVERRIDE'?'管理端独立配置':'只读继承原有选择'],
        ['三工具本地试用',`Normal：${config.tool_trials?.normal_enabled?'已启用':'未启用'} · Streaming：${config.tool_trials?.streaming_enabled?'已启用':'未启用'}`]]),
      el('div',{class:'tool-policy-list',role:'group','aria-label':'允许 Assistant 使用的工具'},config.tools.map(tool=>el('label',{class:'tool-policy-option'},[
        el('input',{type:'checkbox',...(selected.has(tool.name)?{checked:'checked'}:{}),
          ...(busy||tool.compatibility_only?{disabled:'disabled'}:{}),
          'aria-label':labels[tool.name]||tool.name,onchange:e=>{
            if(e.target.checked)selected.add(tool.name);else selected.delete(tool.name);}}),
        el('span',{text:labels[tool.name]||tool.name})])))]:[]),
      el('p',{class:'tool-policy-status',role:'status',text:message}),
      el('div',{class:'settings-actions'},[el('button',{class:'button primary',text:'保存 Tool 授权',
        ...(!config||busy?{disabled:'disabled'}:{}),onclick:()=>void save()}),
        button('重新读取',()=>void load())]));
  }
  async function load(){if(busy)return;busy=true;message='读取中…';render();
    try{config=validatePolicy(await api.toolPolicy());selected=new Set(config.selected_tools);message='保存后需重新确认下一次模型请求。';}
    catch{config=null;message='授权配置读取失败，请检查服务或配置文件。';}finally{busy=false;render();}}
  async function save(){if(busy||!config)return;busy=true;message='保存中…';render();
    try{config=validatePolicy(await api.saveToolPolicy({epoch:config.epoch,revision:config.revision,
      selected_tools:[...selected]},config));selected=new Set(config.selected_tools);
      message='已保存；正在运行的 Turn 保持冻结授权，下一条请求使用新配置。';onSaved();}
    catch(e){message=e.message==='TOOL_POLICY_REVISION_MISMATCH'?
      '配置已被其他窗口修改，请重新读取后再保存。':'保存失败，未确认写入；请重新读取配置。';}
    finally{busy=false;render();}}
  return {mount(){if(!loaded){loaded=true;void load();}return root;},load};
}
