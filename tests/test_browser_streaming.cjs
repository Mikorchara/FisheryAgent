// Offline browser behavior probe using only Node built-ins; no HTTP connection.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '..', 'src', 'fishery_ai', 'resources', 'web', 'app.js');
const source = fs.readFileSync(sourcePath, 'utf8').replace(/\binit\(\);\s*$/, '');
const html = fs.readFileSync(path.join(__dirname, '..', 'src', 'fishery_ai',
  'resources', 'web', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'src', 'fishery_ai',
  'resources', 'web', 'app.css'), 'utf8');
const knownIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));

function analysisActivityResult(activity) {
  return {runtime:{},usage:{},status:'completed',structured_parse_ok:true,inference:'固定分析',
    generated_text:'{}',recommendations:[],uncertainty:[],rule_results:[],evidence:[],
    observed_facts:{water_quality:{temperature_c:28,ph:7.5,dissolved_oxygen_mg_l:6,
      observed_at:'2026-10-06T05:00:00Z',retrieved_at:'2026-10-06T05:00:00Z',source:'initial-fixture',
      quality:'valid',freshness:'fresh'}},tool_activity:activity};
}

test('Analysis Tool Activity belongs to right formal results and is collapsed by default',()=>{
  assert.ok(html.indexOf('id="analysis-tool-activity"')>html.indexOf('<main class="results"'));
  assert.doesNotMatch(html, /id="analysis-tool-activity"[^>]*\bopen\b/);
  const page=makePage(async()=>{throw new Error('no network')});
  vm.runInContext(`render(${JSON.stringify(analysisActivityResult())},10)`,page.context);
  assert.equal(page.element('analysis-tool-activity').open,false);
  assert.match(page.element('analysis-tool-observation-note').textContent,/未调用/);
});

test('Analysis Tool Activity shows allowed tool, steps, usage and NO_DATA without replacing facts',()=>{
  const page=makePage(async()=>{throw new Error('no network')});
  const activity={enabled:true,allowed_tools:['get_current_water_quality'],called:true,
    tool_name:'get_current_water_quality',arguments_summary:'{}',result_status:'NO_DATA',duration_ms:2,
    request_1:{outcome:'tool_calls',usage:{total_tokens:10}},request_2:{outcome:'final_answer',usage:{total_tokens:20}},
    usage:{request_count:2,usage:{total_tokens:30}},final_finish_reason:'stop',
    tool_result:{status:'NO_DATA',water_quality:null},snapshot_comparison:'no_data'};
  vm.runInContext(`render(${JSON.stringify(analysisActivityResult(activity))},10)`,page.context);
  assert.match(page.element('analysis-tool-summary').children.map(x=>x.textContent).join(' '),/get_current_water_quality/);
  const record=JSON.parse(page.element('analysis-tool-record').textContent);
  assert.equal(record.request_2.outcome,'final_answer');assert.equal(record.usage.usage.total_tokens,30);
  assert.match(page.element('analysis-tool-observation-note').textContent,/NO_DATA.*保留/);
  assert.match(page.element('facts').children.map(x=>x.textContent).join(' '),/initial-fixture/);
});

test('Analysis Tool Activity separates changed tool observation from initial Facts',()=>{
  const page=makePage(async()=>{throw new Error('no network')});
  const result=analysisActivityResult({called:true,allowed_tools:['get_current_water_quality'],snapshot_comparison:'different',
    tool_result:{status:'OK',evaluated_at:'2026-10-06T06:00:00Z',water_quality:{dissolved_oxygen_mg_l:2.2,source:'new-fixture'}}});
  vm.runInContext(`render(${JSON.stringify(result)},10)`,page.context);
  assert.match(page.element('analysis-tool-observation-note').textContent,/不一致.*未合并或覆盖/);
  assert.match(page.element('facts').children.map(x=>x.textContent).join(' '),/initial-fixture/);
  assert.doesNotMatch(page.element('facts').children.map(x=>x.textContent).join(' '),/new-fixture/);
  assert.match(page.element('analysis-tool-record').textContent,/new-fixture/);
  assert.equal(page.element('model-inference').textContent,'固定分析');
});

test('Analysis Tool Activity no call and streaming preparation clear previous execution',()=>{
  const page=makePage(async()=>{throw new Error('no network')});
  vm.runInContext(`render(${JSON.stringify(analysisActivityResult({called:true,tool_result:{status:'OK'}}))},10);
    render(${JSON.stringify(analysisActivityResult({enabled:true,allowed_tools:['get_current_water_quality'],called:false}))},10)`,page.context);
  assert.match(page.element('analysis-tool-observation-note').textContent,/未调用/);
  assert.equal(JSON.parse(page.element('analysis-tool-record').textContent).tool_observation,null);
  vm.runInContext('prepareStreamView()',page.context);
  assert.equal(JSON.parse(page.element('analysis-tool-record').textContent).tool_observation,null);
});

test('Analysis Tool Activity preserves safe error and cancellation display',()=>{
  for(const code of ['OPTION_UNKNOWN','TOOL_ROUND_LIMIT','USER_CANCELLED','TOOL_STREAMING_NOT_IMPLEMENTED']) {
    const page=makePage(async()=>{throw new Error('no network')});
    const result={...analysisActivityResult({enabled:true,called:false,request_1:{outcome:'blocked',error_code:code}}),
      error_code:code,status:code==='USER_CANCELLED'?'cancelled':'failed'};
    vm.runInContext(`render(${JSON.stringify(result)},10)`,page.context);
    assert.match(page.element('model-inference').textContent,new RegExp(code));
    assert.match(page.element('analysis-tool-record').textContent,new RegExp(code));
  }
});

function scenarioFixture(id='normal', source='BUILTIN') {
  return {schema_version:'scenario-template-v1',id,display_name:id,source,
    device_id:'sim-test',observed_age_s:0,water_quality:{
      temperature_c:{state:'NORMAL',value:28},ph:{state:'NORMAL',value:7.5},
      dissolved_oxygen_mg_l:{state:'NORMAL',value:6.4}}};
}

function scenarioPage(fetch) {
  const page=makePage(fetch);
  vm.runInContext(`scenarioTemplates=${JSON.stringify([scenarioFixture(),scenarioFixture('low_oxygen'),scenarioFixture('user-test','USER')])};
    credentialCsrf='offline-csrf';renderScenarioTemplates('normal');bindScenarioControls()`,page.context);
  return page;
}

test('Current query display keeps evaluated_at separate from retrieved_at without changing facts', () => {
  const page = makePage(async () => { throw new Error('no network'); });
  const facts = {water_quality: {temperature_c:28, ph:7.5, dissolved_oxygen_mg_l:2.2,
    quality:'valid', freshness:'stale', observed_at:'2026-10-05T02:00:00Z',
    retrieved_at:'2026-10-05T02:00:00Z', source:'fake:sensor'},
    evaluated_at:'2026-10-05T03:00:00Z'};
  const original = JSON.stringify(facts);
  vm.runInContext(`render(${JSON.stringify({observed_facts:facts, rule_results:[
    {code:'SENSOR_STALE',severity:'warning',message:'过期'}], structured_parse_ok:true})}, 1)`, page.context);
  const rows = page.element('scenario-snapshot').children;
  const values = Object.fromEntries(rows.filter((_, i) => i % 2 === 0)
    .map((row, i) => [row.textContent, rows[i * 2 + 1].textContent]));
  assert.equal(values.retrieved_at, facts.water_quality.retrieved_at);
  assert.equal(values.evaluated_at, facts.evaluated_at);
  assert.equal(values.Freshness, 'stale');
  assert.equal(JSON.stringify(facts), original);
});

test('Scenario custom entry is first and builtin/user templates have separate groups',()=>{
  const page=scenarioPage(async()=>{throw new Error('no network');});
  const choices=page.element('scenario').children;
  assert.equal(choices[0].textContent,'+ 自定义情景...');
  assert.equal(choices[0].value,'__custom__');
  assert.deepEqual(choices.slice(1).map(x=>x.label),['内置模板','我的模板']);
  assert.equal(choices[2].children[0].value,'user-test');
  assert.equal(page.element('scenario-edit').hidden,true);
  assert.equal(page.element('scenario-delete').hidden,true);
});

test('Scenario custom modal cancels without file writes and restores previous selection',async()=>{
  const page=scenarioPage(async()=>{assert.fail('cancel must not fetch');});
  page.element('scenario').value='__custom__';await page.element('scenario').dispatch('change');
  assert.equal(page.element('scenario-modal').open,true);
  assert.equal(page.element('scenario').value,'normal');
  page.element('scenario-name').value='unsaved';
  await page.element('scenario-cancel').dispatch('click');
  assert.equal(page.element('scenario-modal').hidden,true);
  assert.equal(page.element('scenario').value,'normal');
  assert.equal(vm.runInContext('appliedScenarioId',page.context),null);
});

test('Scenario Missing/Invalid disables Value and Only Apply sends a temporary template',async()=>{
  const calls=[];
  const page=scenarioPage(async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body),headers:options.headers});
    return r2Reply({status:'ready',snapshot:{temperature_c:34,ph:null,dissolved_oxygen_mg_l:2.2,quality:'partial',freshness:'stale'},
      rule_results:[{code:'TEMP_CRITICAL_HIGH',severity:'critical',message:'程序结果'}]});
  });
  vm.runInContext('openScenarioModal("create")',page.context);
  page.element('scenario-name').value='临时高温低氧';
  page.element('scenario-temperature_c-value').value='34';
  page.element('scenario-dissolved_oxygen_mg_l-value').value='2.2';
  page.element('scenario-ph-state').value='MISSING';await page.element('scenario-ph-state').dispatch('change');
  assert.equal(page.element('scenario-ph-value').disabled,true);
  page.element('scenario-age').value='301';
  await page.element('scenario-only-apply').dispatch('click');
  assert.deepEqual(calls.map(x=>x.url),['/api/water-quality/apply']);
  assert.deepEqual(calls[0].body.template.water_quality.ph,{state:'MISSING'});
  assert.equal(calls[0].headers['X-CSRF-Token'],'offline-csrf');
  assert.equal(page.element('scenario').value,'__temporary__');
  assert.equal(vm.runInContext('appliedScenarioId',page.context),'__temporary__');
  assert.match(page.element('scenario-findings').children.map(x=>x.textContent).join(' '),/TEMP_CRITICAL_HIGH/);
  assert.equal(page.element('scenario-modal').hidden,true);
});

test('Scenario Save persists then applies server ID; edits retain ID and Save As creates a new one',async()=>{
  const calls=[];
  let saved=scenarioFixture('user-new','USER');
  const page=scenarioPage(async(url,options={})=>{
    const body=options.body ? JSON.parse(options.body):null;
    calls.push({url,method:options.method,body});
    if(options.method==='POST'&&url==='/api/scenario-templates') {
      saved={...body.template,id:'user-new',source:'USER'};return r2Reply({template:saved});
    }
    if(options.method==='PUT') {saved={...body.template,source:'USER'};return r2Reply({template:saved});}
    if(url==='/api/scenario-templates') return r2Reply({templates:[scenarioFixture(),saved]});
    return r2Reply({status:'ready',snapshot:{},rule_results:[]});
  });
  vm.runInContext('openScenarioModal("create")',page.context);page.element('scenario-name').value='保存情景';
  await page.element('scenario-save-apply').dispatch('click');
  assert.deepEqual(calls.slice(0,3).map(x=>x.method),['POST','GET','POST']);
  assert.deepEqual(calls[2].body,{template_id:'user-new'});
  assert.equal(page.element('scenario-edit').hidden,false);
  await page.element('scenario-edit').dispatch('click');page.element('scenario-name').value='修改情景';
  await page.element('scenario-save-apply').dispatch('click');
  const update=calls.find(x=>x.method==='PUT');
  assert.equal(update.url,'/api/scenario-templates/user-new');assert.equal(update.body.template.id,'user-new');
  await page.element('scenario-copy').dispatch('click');
  assert.equal(vm.runInContext('scenarioEditingId',page.context),null);
  assert.match(page.element('scenario-name').value,/副本/);
});

test('Scenario builtin view is readonly with Save As and user deletion retains snapshot',async()=>{
  const calls=[];
  const page=scenarioPage(async(url,options)=>{
    calls.push({url,method:options.method});
    return r2Reply(options.method==='DELETE'?{status:'deleted'}:{templates:[scenarioFixture()]});
  });
  await page.element('scenario-view').dispatch('click');
  assert.equal(page.element('scenario-name').disabled,true);
  assert.equal(page.element('scenario-save-apply').hidden,true);
  assert.equal(page.element('scenario-view-copy').hidden,false);
  await page.element('scenario-view-copy').dispatch('click');
  assert.equal(page.element('scenario-name').disabled,false);
  assert.equal(vm.runInContext('scenarioModalMode',page.context),'copy');
  await page.element('scenario-cancel').dispatch('click');
  page.element('scenario').value='user-test';await page.element('scenario').dispatch('change');
  assert.equal(page.element('scenario-delete').hidden,false);
  vm.runInContext('appliedScenarioId="user-test"',page.context);
  await page.element('scenario-delete').dispatch('click');
  assert.equal(calls[0].url,'/api/scenario-templates/user-test');assert.equal(calls[0].method,'DELETE');
  assert.equal(vm.runInContext('appliedScenarioId',page.context),'user-test');
  assert.match(page.element('scenario-status').textContent,/当前快照未被删除/);
});

test('Scenario Normal requires numeric value and malformed/network errors are visible safely',async()=>{
  let calls=0;
  const page=scenarioPage(async()=>{calls++;throw new Error('fictional private exception');});
  vm.runInContext('openScenarioModal("create")',page.context);page.element('scenario-name').value='test';
  page.element('scenario-ph-value').value='';
  await page.element('scenario-only-apply').dispatch('click');
  assert.equal(calls,0);assert.match(page.element('scenario-modal-status').textContent,/SCENARIO_VALUE_REQUIRED:ph/);
  page.element('scenario-ph-state').value='INVALID';await page.element('scenario-ph-state').dispatch('change');
  await page.element('scenario-only-apply').dispatch('click');
  assert.match(page.element('scenario-modal-status').textContent,/NETWORK_ERROR/);
  assert.doesNotMatch(page.element('scenario-modal-status').textContent,/fictional private exception/);
  assert.equal(page.element('scenario-only-apply').disabled,false);
});

test('Scenario already applied temporary snapshot is analyzed without resending template or scenario',async()=>{
  let sent;
  const page=makePage(async(_url,options)=>{sent=JSON.parse(options.body);return r2Reply({error_code:'OFFLINE_FIXTURE'});});
  setProfile(page);page.element('response-mode').value='normal';page.element('scenario').value='__temporary__';
  vm.runInContext('appliedScenarioId="__temporary__"',page.context);
  await vm.runInContext('analyze()',page.context);
  assert.equal(Object.hasOwn(sent,'scenario'),false);
  assert.equal(Object.hasOwn(sent,'template'),false);
});

function manualV2Draft(overrides={}) {
  return {id:'experiment-'+'a'.repeat(32), name:'Offline V2', service_name:'unregistered label', transport:'openai_chat',
    base_url:'http://127.0.0.1:11434/v1', model:'free-model',credential_ref:'',timeout:30,
    raw_request_body:{model:'free-model',messages:[{role:'user',content:'OK'}],enable_thinking:false},notes:'',...overrides};
}

test('Manual V2 new raw template omits model and Send never rewrites editor JSON',async()=>{
  const calls=[];
  const page=makePage(async(url,options={})=>{
    calls.push({url,body:JSON.parse(options.body)});
    return r2Reply({raw_response:{choices:[]},total_latency_ms:1});
  });
  vm.runInContext('manualVersion="v2";credentialCsrf="fictional-csrf";fillExperiment(null)',page.context);
  assert.equal(Object.hasOwn(JSON.parse(page.element('experiment-body').value),'model'),false);
  page.element('experiment-name').value='new draft';page.element('experiment-service').value='label';
  page.element('experiment-url').value='http://127.0.0.1:11434/v1';page.element('experiment-model').value='authoritative-model';
  const original=' { "messages": [{"role":"user", "content":"OK"}] } ';
  page.element('experiment-body').value=original;
  await vm.runInContext('sendManual()',page.context);
  assert.equal(calls[0].url,'/api/manual-v2');
  assert.equal(calls[0].body.experiment.model,'authoritative-model');
  assert.equal(Object.hasOwn(calls[0].body.experiment.raw_request_body,'model'),false);
  assert.equal(page.element('experiment-body').value,original);
});

test('Manual V2 labels explain Credential name versus Key value and Save versus Save As',()=>{
  assert.match(html,/Credential Ref \/ 凭据名称/);
  assert.match(html,/DASHSCOPE_MANUAL_KEY/);
  assert.match(html,/New Key \/ API Key Value/);
  assert.match(html,/这里只填写真实 Key 值，不填写 NAME=value/);
  assert.match(html,/Experiment 只保存 credential_ref，不保存 Key/);
  assert.match(html,/Save：保存\/更新当前 Experiment/);
  assert.match(html,/Save As：以当前内容创建一个新的 Experiment，原 Experiment 保留/);
  assert.match(html,/outputs\/manual-experiments\//);
});

test('Manual V2 switches without losing V1 or V2 drafts and hides the saved connection selector',async()=>{
  const page=threeModePage(async(url)=>url==='/api/manual-v2/experiments' ? r2Reply({experiments:[]}) : null);
  await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");})()',page.context);
  page.element('manual-body').value='V1 draft preserved';
  const target=vm.runInContext('manualTargetId',page.context);
  await vm.runInContext('setManualVersion("v2")',page.context);
  page.element('experiment-name').value='V2 draft preserved';
  page.element('experiment-body').value='V2 raw draft preserved';
  assert.equal(page.element('profile').hidden,true);
  assert.equal(page.element('manual-v1-fields').hidden,true);
  await vm.runInContext('setManualVersion("v1")',page.context);
  assert.equal(page.element('manual-body').value,'V1 draft preserved');
  assert.equal(vm.runInContext('manualTargetId',page.context),target);
  assert.equal(page.element('profile').hidden,false);
  await vm.runInContext('setManualVersion("v2")',page.context);
  assert.equal(page.element('experiment-name').value,'V2 draft preserved');
  assert.equal(page.element('experiment-body').value,'V2 raw draft preserved');
});

test('Manual V2 empty clean-room can send without any Profile and leaving mode preserves its draft',async()=>{
  const page=threeModePage(async(url)=>url==='/api/manual-v2/experiments' ? r2Reply({experiments:[]}) : null,[]);
  await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");await setManualVersion("v2");})()',page.context);
  assert.equal(page.element('manual-send').disabled,false);
  page.element('experiment-name').value='keep';
  vm.runInContext('setAccessMode("managed_custom");setAccessMode("manual_expert")',page.context);
  assert.equal(page.element('manual-send').disabled,false);
  assert.equal(page.element('experiment-name').value,'keep');
});

test('Manual V2 Save update Save As and Delete use only independent experiment endpoints',async()=>{
  let saved=[];
  const calls=[];
  const page=makePage(async(url,options={})=>{
    calls.push({url,method:options.method||'GET',body:options.body?JSON.parse(options.body):null});
    if(url==='/api/manual-v2/experiments' && !options.method)return r2Reply({experiments:saved});
    if(options.method==='DELETE'){saved=[];return r2Reply({status:'success'});}
    const data={...JSON.parse(options.body),id:'experiment-'+(options.method==='PUT'?'a':'b').repeat(32)};
    saved=[data];return r2Reply({experiment:data});
  });
  vm.runInContext(`credentialCsrf='fictional-csrf';fillExperiment(${JSON.stringify(manualV2Draft())})`,page.context);
  await vm.runInContext('saveExperiment()',page.context);
  assert.equal(calls[0].method,'PUT');
  await vm.runInContext('saveExperiment(true)',page.context);
  assert.equal(calls.find(x=>x.method==='POST').url,'/api/manual-v2/experiments');
  await vm.runInContext('deleteExperiment()',page.context);
  assert.equal(vm.runInContext('experimentId',page.context),null);
  assert.equal(calls.some(x=>x.url.includes('profiles')||x.url.includes('credentials')),false);
});

test('Manual V2 Send preserves raw JSON and custom target without capability or defaults',async()=>{
  const calls=[];
  const page=makePage(async(url,options={})=>{
    calls.push({url,body:options.body?JSON.parse(options.body):null});
    return r2Reply({raw_response:{choices:[{message:{tool_calls:[{id:'display_only'}]}}]},usage:{total_tokens:3},total_latency_ms:2});
  });
  const values=manualV2Draft();
  vm.runInContext(`manualVersion='v2';credentialCsrf='fictional-csrf';fillExperiment(${JSON.stringify(values)})`,page.context);
  await vm.runInContext('sendManual()',page.context);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/manual-v2');
  assert.deepEqual(calls[0].body.experiment.raw_request_body,values.raw_request_body);
  assert.equal(calls[0].body.profile_id,undefined);
  assert.equal(calls[0].body.experiment.service_name,'unregistered label');
  assert.match(page.element('manual-output').textContent,/display_only/);
});

test('Manual V2 Streaming uses common raw events and Stop uses shared cancellation',async()=>{
  const calls=[];
  const page=makePage(async(url,options={})=>{
    calls.push(url);
    if(url.startsWith('/api/requests/'))return r2Reply({state:'CANCELLED',backend_io_closed:true});
    return sseResponse([['raw_delta',{raw_response:{choices:[{delta:{content:'offline'}}]},usage:{total_tokens:3}}],['completed',{total_latency_ms:4}]]);
  });
  const values=manualV2Draft({raw_request_body:{model:'free-model',messages:[{role:'user',content:'OK'}],stream:true}});
  vm.runInContext(`manualVersion='v2';credentialCsrf='fictional-csrf';fillExperiment(${JSON.stringify(values)})`,page.context);
  await vm.runInContext('sendManual()',page.context);
  assert.match(page.element('manual-output').textContent,/offline/);
  assert.match(page.element('manual-status').textContent,/完成/);
  await vm.runInContext('beginExecution()',page.context);
  assert.equal(page.element('manual-stop').disabled,false);
  await vm.runInContext('stopGeneration()',page.context);
  assert.match(page.element('manual-status').textContent,/USER_CANCELLED/);
  assert.equal(page.element('manual-stop').disabled,true);
  assert.ok(calls.some(x=>x.endsWith('/cancel')));
});

test('Manual V2 credential CRUD clears input and never puts Key into experiment fields',async()=>{
  const calls=[];
  const state={credential_ref:'MANUAL_TEST_KEY',availability:'MISSING',editable:true,exists:false,revision:'opaque'};
  const page=makePage(async(url,options={})=>{
    calls.push({url,body:JSON.parse(options.body)});
    assert.equal(page.element('manual-key-value').value,'');
    return r2Reply({...state,availability:'PRESENT',exists:true,revision:'rotated'});
  });
  vm.runInContext(`credentialCsrf='fictional-csrf';fillExperiment(${JSON.stringify(manualV2Draft({credential_ref:'MANUAL_TEST_KEY'}))});manualKeyState=${JSON.stringify(state)}`,page.context);
  page.element('manual-key-value').value='fictional-manual-key';
  await vm.runInContext('changeManualCredential("create")',page.context);
  assert.equal(calls[0].url,'/api/manual-v2/credentials');
  assert.equal(calls[0].body.secret,'fictional-manual-key');
  assert.equal(JSON.stringify(vm.runInContext('collectExperiment()',page.context)).includes('fictional-manual-key'),false);
  assert.doesNotMatch(page.element('manual-key-status').textContent,/fictional-manual-key/);
  await vm.runInContext('changeManualCredential("remove")',page.context);
  assert.equal(calls[1].body.secret,undefined);
  assert.equal(page.element('experiment-ref').value,'MANUAL_TEST_KEY');
});

test('Manual V2 errors are safe and credential responses for an older ref are discarded',async()=>{
  let finish;
  const page=makePage(async()=>new Promise(resolve=>{finish=resolve;}));
  page.element('experiment-ref').value='FIRST_KEY';
  const pending=vm.runInContext('refreshManualCredential()',page.context);
  page.element('experiment-ref').value='SECOND_KEY';
  vm.runInContext('resetManualKeyState()',page.context);
  finish(r2Reply({credential_ref:'FIRST_KEY',availability:'PRESENT',editable:true,revision:'old'}));
  await pending;
  assert.equal(vm.runInContext('manualKeyState',page.context),null);
  const failed=makePage(async()=>{throw new Error('sensitive fake exception');});
  vm.runInContext(`credentialCsrf='fake';manualKeyState={credential_ref:'TEST_KEY',editable:true,revision:'old'}`,failed.context);
  failed.element('experiment-ref').value='TEST_KEY';failed.element('manual-key-value').value='fictional-manual-key';
  await vm.runInContext('changeManualCredential("create")',failed.context);
  assert.equal(failed.element('manual-key-value').value,'');
  assert.match(failed.element('manual-key-status').textContent,/NETWORK_ERROR/);
  assert.doesNotMatch(failed.element('manual-key-status').textContent,/sensitive/);
});

test('Manual V2 malformed JSON fails locally and New never clears V1 draft',async()=>{
  let count=0;
  const page=makePage(async()=>{count++;throw new Error('offline');});
  vm.runInContext('manualVersion="v2";bindManualV2Controls()',page.context);
  page.element('manual-body').value='keep V1';page.element('experiment-body').value='invalid';
  await vm.runInContext('sendManual()',page.context);
  assert.equal(count,0);
  assert.match(page.element('manual-status').textContent,/INVALID_REQUEST/);
  await page.element('experiment-new').dispatch('click');
  assert.equal(page.element('manual-body').value,'keep V1');
  assert.equal(page.element('experiment-name').value,'');
  assert.equal(page.element('experiment-model').value,'');
  assert.equal(page.element('experiment-delete').disabled,true);
});

test('Default preference UNKNOWN, UNSUPPORTED and CONFLICT disable new ON/OFF selections with explanations', () => {
  const page=makePage(async()=>{throw new Error('offline');});
  for(const item of [{status:'unknown'}, {status:'unsupported'}, {status:'unknown',resolution:'EVIDENCE_CONFLICT'}]) {
    vm.runInContext(`formMode='new'; updateDefaultPreferenceControls({capabilities:{thinking_on:${JSON.stringify(item)},thinking_off:${JSON.stringify(item)}}})`,page.context);
    const choices=page.element('custom-default-thinking').children;
    assert.equal(choices.find(x=>x.value==='auto').disabled,false);
    assert.equal(choices.find(x=>x.value==='on').disabled,true);
    assert.equal(choices.find(x=>x.value==='off').disabled,true);
    assert.match(choices.find(x=>x.value==='on').textContent,item.resolution ? /证据冲突，需要人工处理/ : item.status==='unsupported' ? /不支持/ : /尚未验证.*Thinking ON Probe/);
  }
  assert.match(html,/<details id="runtime-default-fields"[^>]*>/);
  assert.doesNotMatch(html,/<details id="runtime-default-fields"[^>]*\bopen\b/);
});

test('Default preference retains saved ON when UNKNOWN and distinguishes its safe AUTO runtime value', () => {
  const page=makePage(async()=>{throw new Error('offline');});
  vm.runInContext(`formMode='edit';updateDefaultPreferenceControls({stored_default_thinking_mode:'on',capabilities:{}},'on')`,page.context);
  assert.equal(page.element('custom-default-thinking').value,'on');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,true);
  assert.match(page.element('runtime-default-summary').textContent,/已保存偏好：ON.*当前有效能力.*实际安全运行值：AUTO/);
  assert.equal(vm.runInContext('collectFields().default_thinking_mode',page.context),'on');
  page.element('custom-default-thinking').value='auto';
  vm.runInContext('updateDefaultPreferenceSummary()',page.context);
  assert.match(page.element('runtime-default-summary').textContent,/已保存偏好：ON.*当前表单偏好：AUTO/);
});

test('Default preference unlocks only the supported exact Thinking option', () => {
  const page=makePage(async()=>{throw new Error('offline');});
  vm.runInContext(`formMode='edit';updateDefaultPreferenceControls({capabilities:{thinking_on:{status:'supported'},thinking_off:{status:'unknown'}}})`,page.context);
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,false);
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='off').disabled,true);
  vm.runInContext(`formMode='new';invalidateTest()`,page.context);
  assert.equal(page.element('custom-default-thinking').value,'auto');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,true);
});

test('Default preference unlocks immediately after explicit Thinking Probe and R4 refresh', async () => {
  const base={profile_id:'custom-default-probe',source:'user_custom',runtime_type:'local',profile_status:'custom',
    thinking_probe_available:true,capabilities:{thinking_on:{status:'unknown'},thinking_off:{status:'unknown'}}};
  const updated={...base,capabilities:{...base.capabilities,thinking_on:{status:'supported',source:'USER_VERIFIED'}}};
  const page=makePage(async(url)=>{
    if(url.endsWith('/thinking-probe'))return {ok:true,json:async()=>({status:'success',capability:updated.capabilities})};
    if(url==='/api/config')return {ok:true,json:async()=>({profiles:[updated]})};
    return {ok:true,json:async()=>({fields:{default_thinking_mode:'auto'},editable:true})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(base)}];formMode='edit';updateDefaultPreferenceControls(profiles[0])`,page.context);
  page.element('profile').value=base.profile_id;
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,true);
  await vm.runInContext('probeThinking("on")',page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,false);
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='off').disabled,true);
});

test('R4 conflicting evidence is UNKNOWN with sources and time, safe choices remain available', () => {
  const page = makePage(async () => { throw new Error('offline'); });
  const conflict = {status:'unknown', source:'USER_VERIFIED', resolution:'EVIDENCE_CONFLICT',
    sources:['OFFICIAL_DOCS','USER_VERIFIED'], evidence:[
      {source:'OFFICIAL_DOCS',status:'supported',observed_at:'2026-10-01'},
      {source:'USER_VERIFIED',status:'unsupported',observed_at:'2026-10-02'}]};
  const profile = {capabilities:{streaming:'unknown', streaming_evidence:conflict,
    thinking_on:conflict, thinking_off:{status:'unknown'}}};
  vm.runInContext(`renderCapabilities(${JSON.stringify(profile)}); updateRuntimeOptionControls(${JSON.stringify(profile)}, {reasoning:'on', response:'streaming'})`, page.context);
  const text = vm.runInContext(`capabilityText(${JSON.stringify(conflict)})`, page.context);
  assert.match(text, /证据冲突.*OFFICIAL_DOCS.*USER_VERIFIED.*2026-10-01.*2026-10-02/);
  assert.equal(page.element('reasoning-mode').value, 'auto');
  assert.equal(page.element('response-mode').value, 'normal');
});

test('R5 unknown exact model Thinking Probe unlocks ON only and uses the current Profile', async () => {
  const base = {profile_id:'custom-unknown-exact', service_id:'dashscope', model:'unlisted-model',
    profile_status:'custom',runtime_type:'local',source:'user_custom',thinking_probe_available:true,
    capabilities:{streaming:'unknown',thinking_on:{status:'unknown'},thinking_off:{status:'unknown'}}};
  const resolved = {...base,capabilities:{...base.capabilities,
    thinking_on:{status:'supported',source:'USER_VERIFIED',resolution:'EVIDENCE_AGREEMENT'}}};
  const calls = [];
  const page = makePage(async (url, options={}) => {
    if (url.endsWith('/thinking-probe')) {
      calls.push({url,body:JSON.parse(options.body)});
      return {ok:true,json:async()=>({status:'success',capability:resolved.capabilities})};
    }
    if (url === '/api/config') return {ok:true,json:async()=>({profiles:[resolved]})};
    return {ok:true,json:async()=>({fields:{},editable:true})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(base)}]`,page.context);
  page.element('profile').value=base.profile_id;
  await vm.runInContext('probeThinking("on")',page.context);
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,`/api/profiles/${base.profile_id}/thinking-probe`);
  assert.equal(calls[0].body.confirm_network,true);
  assert.equal(page.element('reasoning-mode').children.find(x=>x.value==='on').disabled,false);
  assert.equal(page.element('reasoning-mode').children.find(x=>x.value==='off').disabled,true);
  assert.equal(page.element('probe-thinking-on').hidden,true);
});

test('R5 successful request with conflicting evidence never announces resolved SUPPORTED', async () => {
  const profile={profile_id:'custom-conflict',profile_status:'custom',runtime_type:'local',source:'user_custom',
    thinking_probe_available:true,capabilities:{streaming:'unknown',source:'USER_VERIFIED',streaming_evidence:{
      status:'unknown',source:'USER_VERIFIED',resolution:'EVIDENCE_CONFLICT',sources:['OFFICIAL_DOCS','USER_VERIFIED']}}};
  const page=makePage(async(url)=> {
    if(url.endsWith('/probe')) return {ok:true,json:async()=>({status:'success',capability:profile.capabilities})};
    if(url==='/api/config') return {ok:true,json:async()=>({profiles:[profile]})};
    return {ok:true,json:async()=>({fields:{},editable:true})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(profile)}]`,page.context);
  page.element('profile').value=profile.profile_id;
  await vm.runInContext('probeSelectedCapability(true)',page.context);
  assert.match(page.element('capability-probe-status').textContent,/证据冲突.*UNKNOWN/);
  assert.doesNotMatch(page.element('capability-probe-status').textContent,/SUPPORTED/);
  assert.equal(page.element('response-mode').children.find(x=>x.value==='streaming').disabled,true);
});

const r2Profile = {profile_id:'r2-profile',display_name:'R2 fixture',service_id:'dashscope',
  runtime_type:'cloud',profile_status:'custom',source:'user_custom',auth_spec:'REQUIRED_BEARER',
  secret_env:'TEST_FAKE_KEY',credential_ref:'TEST_FAKE_KEY',capabilities:{streaming:'supported'}};
const r2State = {provider:'dashscope',credential_name:'TEST_FAKE_KEY',availability:'PRESENT',
  source:'PROJECT_ENV',editable:true,exists:true,revision:'opaque-revision',error_code:null};
const r2Reply = (data,ok=true,status=ok?200:409) => ({ok,status,json:async()=>data});
test('R2 private storage is explicitly shown without implying source-root dotenv edits',async()=>{
  const page=makePage(async()=>r2Reply({...r2State,storage:'USER_PRIVATE'}));
  r2Setup(page,{...r2State,storage:'USER_PRIVATE'});
  assert.match(page.element('credential-status').textContent,/PROJECT_ENV.*用户私有存储/);
  await vm.runInContext(`showSecret('TEST_FAKE_KEY','secret-status',()=>true,${JSON.stringify(r2Profile)})`,page.context);
  assert.match(page.element('secret-status').textContent,/PROJECT_ENV.*用户私有存储/);
  assert.match(html,/不编辑或自动迁移源码根目录/);
});
function r2Setup(page,state=r2State) {
  vm.runInContext(`profiles=[${JSON.stringify(r2Profile)}];formMode='view';credentialCsrf='fictional-csrf'`,page.context);
  page.element('profile').value=r2Profile.profile_id;
  vm.runInContext(`renderCredentialState(${JSON.stringify(state)})`,page.context);
}

test('R2 credential submit clears input before request, never changes runtime capability, and clears auth caches',async()=>{
  let page;
  let body;
  page=makePage(async(url,options)=>{
    if(url==='/api/credentials') {
      assert.equal(page.element('credential-value').value,'');
      body=JSON.parse(options.body);
      assert.equal(options.method,'PUT');
      assert.equal(options.headers['X-CSRF-Token'],'fictional-csrf');
      return r2Reply({...r2State,revision:'new-opaque'});
    }
    assert.equal(url,'/api/secret-status');
    return r2Reply({availability:'PRESENT',source:'PROJECT_ENV',editable:true});
  });
  r2Setup(page);
  page.element('credential-value').value='fictional-browser-key';
  page.element('response-mode').value='streaming';
  page.element('reasoning-mode').value='off';
  page.element('model-options').hidden=false;
  vm.runInContext("testId='old-test';testedFingerprint='old-fingerprint'",page.context);
  await vm.runInContext("changeCredential('replace')",page.context);
  assert.equal(body.secret,'fictional-browser-key');
  assert.equal(body.profile_id,r2Profile.profile_id);
  assert.equal(page.element('credential-value').value,'');
  assert.equal(page.element('model-options').hidden,true);
  assert.equal(vm.runInContext('testId',page.context),null);
  assert.equal(page.element('response-mode').value,'streaming');
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(vm.runInContext('profiles[0].capabilities.streaming',page.context),'supported');
  assert.match(page.element('credential-status').textContent,/已保存.*立即生效.*失效/);
  assert.doesNotMatch(page.element('credential-status').textContent,/fictional-browser-key/);
});

test('R2 first missing credential uses create and deletion sends no secret',async()=>{
  const calls=[];
  const page=makePage(async(url,options)=>{
    if(url==='/api/credentials') {
      calls.push({method:options.method,body:JSON.parse(options.body)});
      return r2Reply(options.method==='DELETE' ? {...r2State,availability:'MISSING',exists:false}
        : r2State);
    }
    return r2Reply({availability:'PRESENT',source:'PROJECT_ENV',editable:true});
  });
  r2Setup(page,{...r2State,exists:false,availability:'MISSING'});
  assert.equal(page.element('credential-create').hidden,false);
  page.element('credential-value').value='fictional-created-key';
  await vm.runInContext("changeCredential('create')",page.context);
  assert.equal(page.element('credential-replace').hidden,false);
  await vm.runInContext("changeCredential('remove')",page.context);
  assert.deepEqual(calls.map(x=>x.method),['POST','DELETE']);
  assert.equal(Object.hasOwn(calls[1].body,'secret'),false);
  assert.match(page.element('credential-status').textContent,/已删除/);
});

test('R2 readonly PROCESS_ENV and NONE never expose credential edit controls',()=>{
  const page=makePage(async()=>{throw new Error('offline only');});
  r2Setup(page,{...r2State,source:'PROCESS_ENV',editable:false,revision:null});
  assert.equal(page.element('credential-edit-fields').hidden,true);
  assert.match(page.element('credential-status').textContent,/外部只读/);
  vm.runInContext("renderCredentialState({availability:'NONE_REQUIRED',source:'NONE_REQUIRED',editable:false})",page.context);
  assert.equal(page.element('credential-edit-fields').hidden,true);
  assert.match(page.element('credential-status').textContent,/不需要凭据/);
});

test('R2 safe conflict, fetch error and bad JSON all clear input without echoing raw exception',async()=>{
  for(const kind of ['conflict','fetch','json']) {
    const page=makePage(async()=>{
      if(kind==='fetch') throw new Error('fictional-browser-secret raw exception');
      if(kind==='json') return {ok:true,json:async()=>{throw new SyntaxError('fictional-browser-secret');}};
      return r2Reply({error_code:'ENV_REVISION_CONFLICT'},false);
    });
    r2Setup(page);
    page.element('credential-value').value='fictional-browser-secret';
    await vm.runInContext("changeCredential('replace')",page.context);
    assert.equal(page.element('credential-value').value,'');
    assert.match(page.element('credential-status').textContent,/修改失败/);
    assert.doesNotMatch(page.element('credential-status').textContent,/fictional-browser-secret|raw exception/);
    assert.equal(page.element('credential-replace').disabled,false);
    if(kind==='conflict') assert.match(page.element('credential-status').textContent,/ENV_REVISION_CONFLICT.*刷新/);
  }
});

test('R2 CSRF failure clears new key before fetching session token',async()=>{
  let page;
  page=makePage(async(url)=>{
    assert.equal(url,'/api/credential-session');
    assert.equal(page.element('credential-value').value,'');
    return r2Reply({error_code:'CSRF_INVALID'},false,403);
  });
  r2Setup(page);
  vm.runInContext('credentialCsrf=null',page.context);
  page.element('credential-value').value='fictional-browser-secret';
  await vm.runInContext("changeCredential('replace')",page.context);
  assert.match(page.element('credential-status').textContent,/CSRF_INVALID/);
  assert.equal(page.element('credential-value').value,'');
});

test('R2 credential status response for previous Profile is discarded',async()=>{
  let resolve;
  const page=makePage(async()=>new Promise(done=>{resolve=done;}));
  r2Setup(page);
  const pending=vm.runInContext('refreshCredentialStatus()',page.context);
  vm.runInContext("profiles[0]={...profiles[0],profile_id:'next',auth_spec:'NONE'};formMode='view'",page.context);
  page.element('profile').value='next';
  vm.runInContext('resetCredentialManager()',page.context);
  resolve(r2Reply(r2State));
  await pending;
  assert.match(page.element('credential-status').textContent,/不需要凭据/);
  assert.equal(page.element('credential-edit-fields').hidden,true);
});

test('R2 draft profile can set credential before saving or querying models',async()=>{
  const fields={display_name:'R2 new',service_id:'dashscope',model_family:'qwen',adapter_id:'openai_chat',
    base_url:'https://example.invalid/v1',model:'',secret_env:'TEST_FAKE_KEY',provider_kind:'cloud',auth_spec:'REQUIRED_BEARER'};
  let submitted;
  const page=makePage(async(url,options)=>{
    assert.equal(url,'/api/credentials/status');
    submitted=JSON.parse(options.body);
    return r2Reply({...r2State,exists:false,availability:'MISSING'});
  });
  vm.runInContext('formMode="new"',page.context);
  page.element('provider-preset').value='dashscope';
  for(const [field,value] of Object.entries(fields)) {
    vm.runInContext(`$(customFields[${JSON.stringify(field)}]).value=${JSON.stringify(value)}`,page.context);
  }
  await vm.runInContext('refreshCredentialStatus()',page.context);
  assert.equal(submitted.draft.secret_env,'TEST_FAKE_KEY');
  assert.equal(Object.hasOwn(submitted,'profile_id'),false);
  assert.equal(page.element('credential-create').hidden,false);
});

test('R2 late model-list or connection-test response cannot restore caches after credential rotation',async()=>{
  for(const action of ['queryModels()','testConnection()']) {
    let resolve;
    const page=makePage(async()=>new Promise(done=>{resolve=done;}));
    const fields={display_name:'R2 new',service_id:'dashscope',model_family:'qwen',adapter_id:'openai_chat',
      base_url:'https://example.invalid/v1',model:'fake-model',secret_env:'TEST_FAKE_KEY',provider_kind:'cloud',auth_spec:'REQUIRED_BEARER'};
    vm.runInContext('formMode="new"',page.context);
    page.element('provider-preset').value='dashscope';
    page.element('test-method').value='models';
    for(const [field,value] of Object.entries(fields)) vm.runInContext(`$(customFields[${JSON.stringify(field)}]).value=${JSON.stringify(value)}`,page.context);
    const pending=vm.runInContext(action,page.context);
    vm.runInContext('invalidateCredentialCaches()',page.context);
    resolve(r2Reply({models:['obsolete-model'],test_id:'obsolete-test',model:'fake-model'}));
    await pending;
    assert.equal(vm.runInContext('testId',page.context),null);
    assert.equal(page.element('model-options').hidden,true);
    assert.match(page.element('test-status').textContent,/失效/);
  }
});

function businessView(page) {
  return ['model-inference', 'recommendations', 'uncertainty', 'structured']
    .map(id => ({text: page.element(id).textContent,
      children: page.element(id).children.map(child => child.textContent)}));
}

test('Normal and completed Streaming share final rendering without raw JSON residue', async () => {
  const raw = JSON.stringify({inference:'当前低氧',recommendations:['增氧'],uncertainty:['缺少症状']});
  const result = {runtime:{},inference:'当前低氧',recommendations:['增氧'],uncertainty:['缺少症状'],
    generated_text:raw,structured_parse_ok:true,status:'completed'};
  const normal = makePage(async () => { throw new Error('offline only'); });
  vm.runInContext(`render(${JSON.stringify(result)}, 30)`, normal.context);
  const streaming = makePage(async () => sseResponse([
    ['content_delta',{delta:raw.slice(0,15)}], ['content_delta',{delta:raw.slice(15)}],
    ['completed',{result,total_latency_ms:30,ttft_ms:5}],
  ], 1));
  await vm.runInContext('analyzeStreaming({})', streaming.context);
  assert.deepEqual(businessView(streaming),businessView(normal));
  assert.equal(streaming.element('model-inference').textContent,'当前低氧');
  assert.equal(streaming.element('streaming-preview').hidden,true);
  assert.equal(streaming.element('streaming-output').textContent,'');
  assert.equal(streaming.element('model-output').textContent,raw);
  assert.equal(streaming.element('raw-model-debug').open,false);
  assert.doesNotMatch(streaming.element('model-inference').textContent,/"inference"|[{}]/);
});

test('parse failure retains raw output only in debug for either transport',async()=>{
  const raw='{"inference": broken';
  const result={runtime:{},inference:raw,generated_text:raw,structured_parse_ok:false,
    status:'completed',recommendations:[],uncertainty:['解析失败']};
  const page=makePage(async()=>sseResponse([['content_delta',{delta:raw}],['completed',{result}]]));
  await vm.runInContext('analyzeStreaming({})',page.context);
  assert.match(page.element('model-inference').textContent,/未能解析/);
  assert.doesNotMatch(page.element('model-inference').textContent,/broken/);
  assert.doesNotMatch(page.element('structured').children.map(x=>x.textContent).join(' '),/broken/);
  assert.equal(page.element('model-output').textContent,raw);
  const view=businessView(page);
  vm.runInContext(`render(${JSON.stringify(result)}, 20)`,page.context);
  assert.deepEqual(businessView(page),view);
});

test('live preview is separate from inference and clears previous parsed results',()=>{
  const page=makePage(async()=>{throw new Error('offline only');});
  page.element('model-inference').textContent='旧推断';
  page.element('recommendations').append({textContent:'旧建议'});
  vm.runInContext('prepareStreamView()',page.context);
  assert.match(page.element('model-inference').textContent,/正在生成/);
  assert.equal(page.element('streaming-preview').hidden,false);
  assert.equal(page.element('streaming-preview').open,true);
  assert.equal(page.element('recommendations').children.length,0);
  const businessPanel=html.split('class="panel output-panel"')[1].split('</section>')[0];
  assert.doesNotMatch(businessPanel,/streaming-output/);
});

test('capabilities use concise colored status and default folded evidence',()=>{
  const page=makePage(async()=>{throw new Error('offline only');});
  const profile={service_id:'dashscope',adapter_id:'openai_chat',base_url:'https://example.invalid/v1',model:'exact-model',
    capabilities:{streaming:'supported',source:'USER_VERIFIED',
      thinking_on:{status:'supported',source:'OFFICIAL_DOCS'},thinking_off:{status:'unsupported',source:'USER_VERIFIED'},
      reasoning_effort:{status:'unknown'},thinking_default:false}};
  vm.runInContext(`renderCapabilities(${JSON.stringify(profile)})`,page.context);
  const status=page.element('capability-list').children.filter(x=>x.className);
  assert.equal(status.length,8);
  assert.equal(status[0].className,'capability-status capability-supported');
  assert.equal(status[2].className,'capability-status capability-unsupported');
  assert.equal(status[4].className,'capability-status capability-unknown');
  assert.deepEqual(status.slice(0,3).map(x=>x.textContent),['支持','支持','不支持']);
  assert.doesNotMatch(page.element('capability-list').children.map(x=>x.textContent).join(' '),/OFFICIAL_DOCS|USER_VERIFIED/);
  assert.match(page.element('capability-evidence').children.map(x=>x.textContent).join(' '),/OFFICIAL_DOCS.*USER_VERIFIED.*exact-model/);
  const evidenceTag=html.match(/<details id="capability-evidence-details"[^>]*>/)[0];
  assert.doesNotMatch(evidenceTag,/\bopen\b/);
  assert.match(html,/查看能力证据详情/);
  for(const state of ['supported','unknown','unsupported']) assert.match(css,new RegExp(`\\.capability-${state} \\{ color:`));
});

test('Thinking and combination Probe buttons fit a single sidebar column',()=>{
  assert.match(css,/\.probe-actions \{[^}]*grid-template-columns: minmax\(0, 1fr\)/);
  assert.match(css,/\.capability-panel button\.compact-action \{[^}]*width: 100%;[^}]*max-width: 100%;[^}]*min-width: 0;[^}]*white-space: normal;[^}]*overflow-wrap: anywhere/);
});

// Explicit replay only: no default dependency on previous online validation files.
test('Preset fixed thinking variant is readonly while response remains independently selectable',()=>{
  const page=makePage(async()=>r2Reply({fields:{},editable:false}));
  const profile={profile_id:'preset-test-off',display_name:'Preset',service_id:'dashscope',
    model:'qwen-plus',base_url:'https://example.invalid/v1',adapter_id:'openai_chat',
    access_mode:'preset',preset_id:'qwen-plus',preset_variant:'off',preset_contract_version:'1',
    default_reasoning_mode:'off',default_response_mode:'normal',runtime_type:'cloud',profile_status:'experimental',source:'preset',
    capabilities:{streaming:'supported',source:'USER_VERIFIED',thinking_default:false,
      thinking_on:{status:'supported'},thinking_off:{status:'supported'},thinking_off_streaming_combination:{status:'supported'}}};
  vm.runInContext(`profiles=[${JSON.stringify(profile)}];presets=[];renderProfiles('${profile.profile_id}');updateProfile()`,page.context);
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(page.element('reasoning-mode').disabled,true);
  assert.equal(page.element('response-mode').children.find(x=>x.value==='streaming').disabled,false);
  assert.equal(page.element('probe-streaming').hidden,true);
  assert.equal(page.element('advanced-capability-actions').hidden,true);
  assert.match(page.element('profile-meta').textContent,/合同 v1/);
});

test('R6 Stop sends independent authenticated cancel before browser abort and reports I/O separately',async()=>{
  const calls=[];
  let page;
  page=makePage(async(url,options)=>{
    calls.push(url);
    if(url==='/api/requests') return r2Reply({request_id:'r6',control_token:'fictional-control'});
    assert.equal(options.headers['X-CSRF-Token'],'offline-csrf');
    assert.equal(JSON.parse(options.body).control_token,'fictional-control');
    assert.equal(vm.runInContext('activeExecution.controller.signal.aborted',page.context),false);
    return r2Reply({state:'CANCELLED',backend_io_closed:true,remote_compute_stopped:'unknown'});
  },{ownExecutionRoutes:true});
  setProfile(page);
  await vm.runInContext('beginExecution()',page.context);
  assert.equal(page.element('profile').disabled,true);
  await vm.runInContext('stopGeneration()',page.context);
  assert.deepEqual(calls,['/api/requests','/api/requests/r6/cancel']);
  assert.match(page.element('status').textContent,/USER_CANCELLED.*I\/O 已关闭.*UNKNOWN/);
  assert.equal(page.element('profile').disabled,false);
  assert.equal(page.element('stop-generation').disabled,true);
});

test('R6 stop failure never claims backend cancellation',async()=>{
  const page=makePage(async(url)=>{
    if(url==='/api/requests') return r2Reply({request_id:'r6',control_token:'fictional-control'});
    throw new Error('fictional private exception');
  },{ownExecutionRoutes:true});
  setProfile(page);
  await vm.runInContext('beginExecution()',page.context);
  await vm.runInContext('stopGeneration()',page.context);
  assert.match(page.element('status').textContent,/取消未确认.*NETWORK_ERROR.*后端状态未知/);
  assert.doesNotMatch(page.element('status').textContent,/fictional private exception/);
});

test('R6 late browser abort cannot overwrite cancellation acknowledgement or clear a newer request',async()=>{
  let rejectOld;
  const page=makePage(async(url)=>{
    if(url.includes('/cancel')) return r2Reply({state:'CANCELLED',backend_io_closed:true});
    if(url==='/api/analyze') return new Promise((_,reject)=>{rejectOld=reject;});
    throw new Error('unexpected offline route');
  });
  setProfile(page);
  page.element('response-mode').value='normal';
  const old=vm.runInContext('analyze()',page.context);
  await new Promise(setImmediate);
  await vm.runInContext('stopGeneration()',page.context);
  const acknowledged=page.element('status').textContent;
  await vm.runInContext('beginExecution()',page.context);
  const next=vm.runInContext('activeExecution',page.context);
  rejectOld(new Error('AbortError'));
  await old;
  assert.equal(page.element('status').textContent,acknowledged);
  assert.equal(vm.runInContext('activeExecution',page.context),next);
  assert.equal(page.element('stop-generation').disabled,false);
});

test('Manual UI sends raw JSON without managed parameters and renders raw tool_calls without execution',async()=>{
  const calls=[];
  const body={model:'qwen-plus',messages:[{role:'user',content:'OK'}],thinking:{type:'disabled'},max_tokens:8};
  const page=makePage(async(url,options)=>{
    calls.push(url);
    const sent=JSON.parse(options.body);
    assert.deepEqual(sent.body,body);
    assert.equal(Object.hasOwn(sent,'reasoning_mode'),false);
    assert.equal(Object.hasOwn(sent,'scenario'),false);
    return r2Reply({raw_response:{tool_calls:[{name:'never_execute'}]},usage:{total_tokens:5},total_latency_ms:7});
  });
  setProfile(page,true);
  page.element('manual-body').value=JSON.stringify(body);
  await vm.runInContext('sendManual()',page.context);
  assert.deepEqual(calls,['/api/manual']);
  assert.match(page.element('manual-output').textContent,/never_execute.*|total_tokens/);
  assert.match(page.element('manual-status').textContent,/Manual 完成/);
  assert.equal(page.element('analyze').disabled,false);
});

test('Manual malformed JSON is rejected locally without network',async()=>{
  const page=makePage(async()=>{throw new Error('network forbidden');});
  setProfile(page,true);
  page.element('manual-body').value='{bad';
  await vm.runInContext('sendManual()',page.context);
  assert.match(page.element('manual-status').textContent,/INVALID_REQUEST/);
});

if(process.env.FISHERY_PARITY_RECORD) {
  test('recorded Qwen results converge through the real UI renderer without another API call',async()=>{
    const record=JSON.parse(fs.readFileSync(process.env.FISHERY_PARITY_RECORD,'utf8'));
    assert.equal(record.cases.length,4);
    for(const item of record.cases) {
      const result=item.result;
      assert.equal(result.status,'completed');
      assert.equal(result.structured_parse_ok,true);
      const normal=makePage(async()=>{throw new Error('offline replay');});
      vm.runInContext(`render(${JSON.stringify(result)}, 10)`,normal.context);
      const streaming=makePage(async()=>sseResponse([
        ...item.deltas.map(delta=>['content_delta',{delta}]),['completed',{result}],
      ]));
      await vm.runInContext('analyzeStreaming({})',streaming.context);
      assert.deepEqual(businessView(normal),businessView(streaming));
      assert.equal(streaming.element('model-inference').textContent,result.inference);
      assert.equal(streaming.element('streaming-preview').hidden,true);
      assert.equal(streaming.element('model-output').textContent,result.generated_text);
      assert.equal(streaming.element('reasoning-output').textContent,result.reasoning_content||'unavailable');
    }
  });
}

test('Streaming plus Thinking needs its own exact capability and preserves safe modes', () => {
  const page = makePage(async () => { throw new Error('offline'); });
  const profile = {capabilities: {streaming: 'supported', thinking_default: true,
    thinking_on: {status: 'supported'}, thinking_off: {status: 'supported'},
    thinking_streaming_combination: {status: 'unknown'},thinking_off_streaming_combination:{status:'supported'}}};
  vm.runInContext(`updateRuntimeOptionControls(${JSON.stringify(profile)}, {reasoning:'on', response:'streaming'})`, page.context);
  assert.equal(page.element('response-mode').value, 'normal');
  assert.equal(page.element('response-mode').children.find(x => x.value === 'streaming').disabled, true);
  vm.runInContext(`updateRuntimeOptionControls(${JSON.stringify(profile)}, {reasoning:'off', response:'streaming'})`, page.context);
  assert.equal(page.element('response-mode').value, 'streaming');
  vm.runInContext(`updateRuntimeOptionControls(${JSON.stringify(profile)}, {reasoning:'auto', response:'streaming'})`, page.context);
  assert.equal(page.element('response-mode').value, 'normal');
});

test('Cloud Thinking Probe retains official evidence and exposes independent revalidation', async () => {
  const base = {profile_id:'custom-qwen-thinking', profile_status:'custom', service_id:'dashscope', runtime_type:'cloud',
    source:'user_custom', thinking_probe_available:true, capabilities:{streaming:'supported',source:'OFFICIAL_DOCS',
    thinking_on:{status:'supported',source:'OFFICIAL_DOCS'}, thinking_off:{status:'supported',source:'OFFICIAL_DOCS'}}};
  const verified = {...base, capabilities:{...base.capabilities,
    thinking_on:{status:'supported',source:'USER_VERIFIED',sources:['OFFICIAL_DOCS','USER_VERIFIED']}}};
  const calls = [];
  const page = makePage(async (url, options) => {
    if (url.endsWith('/thinking-probe')) {
      calls.push(JSON.parse(options.body));
      return {ok:true,json:async()=>({status:'success',capability:verified.capabilities,latency_ms:3})};
    }
    if (url === '/api/config') return {ok:true,json:async()=>({profiles:[verified]})};
    return {ok:true,json:async()=>({fields:{},editable:false})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(base)}]; presets=[]`,page.context);
  page.element('profile').value=base.profile_id;
  vm.runInContext('updateProfile()',page.context);
  await vm.runInContext('probeThinking("on")',page.context);
  assert.deepEqual(calls,[{mode:'on',confirm_network:true,reverify:false}]);
  assert.equal(page.element('probe-thinking-on').hidden,true);
  assert.equal(page.element('reprobe-thinking-on').hidden,false);
  assert.equal(page.element('probe-thinking-off').hidden,false);
  const text = page.element('capability-evidence').children.map(x=>x.textContent).join(' ');
  assert.match(text,/OFFICIAL_DOCS \+ USER_VERIFIED/);
});

test('combination Probe refresh unlocks Streaming without changing Thinking OFF evidence', async () => {
  const base={profile_id:'custom-combination',profile_status:'custom',runtime_type:'local',source:'user_custom',thinking_probe_available:true,
    capabilities:{streaming:'supported',source:'USER_VERIFIED',thinking_on:{status:'supported',source:'USER_VERIFIED'},
      thinking_off:{status:'unknown'},thinking_streaming_combination:{status:'unknown'}}};
  const verified={...base,capabilities:{...base.capabilities,
    thinking_streaming_combination:{status:'supported',source:'USER_VERIFIED'}}};
  const page=makePage(async(url,options)=>{
    if(url.endsWith('/probe')){
      assert.equal(JSON.parse(options.body).capability,'thinking_streaming_combination');
      return {ok:true,json:async()=>({status:'success',capability:verified.capabilities})};
    }
    if(url==='/api/config')return {ok:true,json:async()=>({profiles:[verified]})};
    return {ok:true,json:async()=>({fields:{},editable:true})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(base)}]; presets=[]`,page.context);
  page.element('profile').value=base.profile_id;
  await vm.runInContext('runExplicitProbe("thinking_streaming_combination")',page.context);
  vm.runInContext('updateRuntimeOptionControls(selectedProfile(),{reasoning:"on",response:"streaming"})',page.context);
  assert.equal(page.element('response-mode').value,'streaming');
  assert.equal(page.element('probe-combination').hidden,true);
  assert.equal(page.element('reprobe-combination').hidden,false);
  assert.equal(page.element('reasoning-mode').children.find(x=>x.value==='off').disabled,true);
});

test('Thinking Probe malformed response has a visible safe error',async()=>{
  const page=makePage(async()=>({ok:true,json:async()=>{throw new Error('private');}}));
  vm.runInContext('profiles=[{profile_id:"unknown-cloud",runtime_type:"cloud",thinking_probe_available:true}]',page.context);
  page.element('profile').value='unknown-cloud';
  await vm.runInContext('probeThinking("off")',page.context);
  assert.match(page.element('thinking-probe-status').textContent,/INVALID_RESPONSE/);
  assert.doesNotMatch(page.element('thinking-probe-status').textContent,/private/);
  assert.equal(page.element('probe-thinking-off').disabled,false);
});

test('reasoning deltas remain in folded debug area and never in final inference',async()=>{
  const result={runtime:{},inference:'final inference',generated_text:'final content',reasoning_content:'debug trace',
    structured_parse_ok:true,usage:{},observed_facts:{},rule_results:[],evidence:[],recommendations:[],uncertainty:[]};
  const page=makePage(async()=>sseResponse([
    ['reasoning_delta',{delta:'debug trace'}],['content_delta',{delta:'final content'}],
    ['completed',{result}],
  ]));
  await vm.runInContext('analyzeStreaming({})',page.context);
  assert.equal(page.element('model-inference').textContent,'final inference');
  assert.equal(page.element('model-output').textContent,'final content');
  assert.equal(page.element('reasoning-output').textContent,'debug trace');
  assert.equal(page.element('reasoning-debug').open,false);
});

function toolManagerFixture(analysis=[], assistant=['get_current_water_quality'], source='BUILTIN_DEFAULT') {
  return {catalog:[{name:'get_current_water_quality',display_name:'get_current_water_quality',
    short_description:'读取当前水质',detailed_description:'canonical Snapshot 与确定性 Findings',
    access_type:'READ ONLY',registered:true,executable:true,dev_only:false,planned:false,parameter_summary:'无；{}'},
    {name:'score_current_water_quality',display_name:'水质评分',short_description:'实验评分',
      detailed_description:'EXPERIMENTAL / NOT PROFESSIONAL STANDARD',access_type:'READ ONLY',
      registered:true,executable:true,dev_only:false,planned:false,experimental:true,parameter_summary:'无；{}'}],policy:{schema_version:1,source,
      modes:{analysis:{selected_tools:analysis},assistant:{selected_tools:assistant}},
      defaults:{analysis:{selected_tools:[]},assistant:{selected_tools:['get_current_water_quality']}},
      runtime_consumed:{analysis:true,assistant:true}}};
}

function toolManagerPage(fetch=async()=>r2Reply(toolManagerFixture())) {
  const page=makePage(fetch);
  vm.runInContext('credentialCsrf="offline-csrf"; bindToolManagerControls()',page.context);
  return page;
}

test('Tool Manager title and Tool entry are application level not Profile controls',()=>{
  assert.match(html,/<h2>Analysis Model<\/h2><button id="open-tool-manager"/);
  assert.doesNotMatch(html,/基础模型配置/);
  assert.ok(html.indexOf('id="open-tool-manager"')<html.indexOf('id="profile"'));
  assert.match(html,/id="tool-manager"[^>]*hidden/);
});

test('Tool Manager opens Analysis tab with collapsed entries and closes without writes',async()=>{
  const calls=[];const page=toolManagerPage(async(url,options)=>{calls.push({url,method:options.method});return r2Reply(toolManagerFixture());});
  await page.element('open-tool-manager').dispatch('click');
  assert.equal(page.element('tool-manager').open,true);
  assert.match(page.element('tool-manager-title').textContent,/Analysis/);
  assert.equal(page.element('tool-catalog-list').children.length,2);
  for(const row of page.element('tool-catalog-list').children)assert.equal(row.children[1].hidden,true);
  await page.element('tool-policy-close').dispatch('click');
  assert.equal(page.element('tool-manager').hidden,true);
  assert.deepEqual(calls,[{url:'/api/tool-policies',method:'GET'}]);
});

test('Tool Manager expands details and collapses again without saving or fetching',async()=>{
  let calls=0;const page=toolManagerPage(async()=>{calls++;return r2Reply(toolManagerFixture());});
  await page.element('open-tool-manager').dispatch('click');
  const item=page.element('tool-catalog-list').children[0],button=item.children[0].children[3],detail=item.children[1];
  await button.dispatch('click');assert.equal(detail.hidden,false);assert.equal(button.textContent,'收起');
  assert.match(detail.children.map(x=>x.textContent).join(' '),/用途.*参数.*适用模式.*Built-in/);
  await button.dispatch('click');assert.equal(detail.hidden,true);assert.equal(button.textContent,'展开');
  assert.equal(calls,1);
});

test('Tool Manager both tabs retain independent drafts and mark Normal Analysis authorization',async()=>{
  const page=toolManagerPage();await page.element('open-tool-manager').dispatch('click');
  assert.match(page.element('tool-policy-note').textContent,/Normal Analysis.*模型|Normal Analysis.*Runtime/);
  assert.match(page.element('tool-policy-count').textContent,/0 \/ 2/);
  let checkbox=page.element('tool-catalog-list').children[0].children[0].children[0];
  checkbox.checked=true;await checkbox.dispatch('change');
  assert.match(page.element('tool-policy-count').textContent,/1 \/ 2/);
  assert.match(page.element('tool-policy-status').textContent,/未保存/);
  await page.element('tool-policy-assistant').dispatch('click');
  checkbox=page.element('tool-catalog-list').children[0].children[0].children[0];assert.equal(checkbox.checked,true);
  checkbox.checked=false;await checkbox.dispatch('change');
  assert.match(page.element('tool-policy-count').textContent,/0 \/ 2/);
  await page.element('tool-policy-analysis').dispatch('click');
  assert.equal(page.element('tool-catalog-list').children[0].children[0].children[0].checked,true);
});

test('Tool Manager Save persists both drafts with CSRF and reopening reads override',async()=>{
  let state=toolManagerFixture();const calls=[];
  const page=toolManagerPage(async(url,options)=>{
    calls.push({url,...options});
    if(options.method==='PUT') {const draft=JSON.parse(options.body);state={...state,policy:{...state.policy,...draft,source:'USER_OVERRIDE'}};}
    return r2Reply(state);
  });
  await page.element('open-tool-manager').dispatch('click');await page.element('tool-policy-assistant').dispatch('click');
  const checkbox=page.element('tool-catalog-list').children[0].children[0].children[0];checkbox.checked=false;await checkbox.dispatch('change');
  await page.element('tool-policy-save').dispatch('click');
  const write=calls.find(x=>x.method==='PUT');assert.equal(write.headers['X-CSRF-Token'],'offline-csrf');
  assert.deepEqual(JSON.parse(write.body),{schema_version:1,modes:{analysis:{selected_tools:[]},assistant:{selected_tools:[]}}});
  assert.match(page.element('tool-policy-status').textContent,/已保存/);
  await page.element('tool-policy-close').dispatch('click');await page.element('open-tool-manager').dispatch('click');
  await page.element('tool-policy-assistant').dispatch('click');
  assert.equal(page.element('tool-catalog-list').children[0].children[0].children[0].checked,false);
  assert.match(page.element('tool-policy-count').textContent,/USER_OVERRIDE/);
});

test('Tool Manager Restore defaults deletes only override and resets both modes',async()=>{
  let state=toolManagerFixture(['get_current_water_quality'],[],'USER_OVERRIDE');const calls=[];
  const page=toolManagerPage(async(url,options)=>{calls.push({url,...options});if(options.method==='DELETE')state=toolManagerFixture();return r2Reply(state);});
  await page.element('open-tool-manager').dispatch('click');await page.element('tool-policy-reset').dispatch('click');
  const reset=calls.find(x=>x.method==='DELETE');assert.deepEqual(JSON.parse(reset.body),{});
  assert.match(page.element('tool-policy-status').textContent,/已恢复内置默认/);
  assert.equal(page.element('tool-catalog-list').children[0].children[0].children[0].checked,false);
  await page.element('tool-policy-assistant').dispatch('click');assert.equal(page.element('tool-catalog-list').children[0].children[0].children[0].checked,true);
});

test('Tool Manager Cancel close retains draft until confirmed discard and reopening resets it',async()=>{
  const page=toolManagerPage();await page.element('open-tool-manager').dispatch('click');
  const checkbox=page.element('tool-catalog-list').children[0].children[0].children[0];checkbox.checked=true;await checkbox.dispatch('change');
  page.context.window.confirm=()=>false;await page.element('tool-policy-close').dispatch('click');assert.equal(page.element('tool-manager').open,true);
  page.context.window.confirm=()=>true;await page.element('tool-policy-close').dispatch('click');
  await page.element('open-tool-manager').dispatch('click');assert.equal(page.element('tool-catalog-list').children[0].children[0].children[0].checked,false);
});

test('Tool Manager save failure is safe, keeps draft and unlocks controls',async()=>{
  const page=toolManagerPage(async(_url,options)=>options.method==='PUT'?{ok:false,status:503,json:async()=>({error_code:'TOOL_POLICY_STORAGE_ERROR'})}:r2Reply(toolManagerFixture()));
  await page.element('open-tool-manager').dispatch('click');
  const checkbox=page.element('tool-catalog-list').children[0].children[0].children[0];checkbox.checked=true;await checkbox.dispatch('change');
  await page.element('tool-policy-save').dispatch('click');
  assert.match(page.element('tool-policy-status').textContent,/TOOL_POLICY_STORAGE_ERROR.*草稿保留/);
  assert.equal(vm.runInContext('toolPolicyDirty',page.context),true);assert.equal(page.element('tool-policy-save').disabled,false);
});

test('Tool Manager read JSON or network failure cannot display editable stale policy',async()=>{
  for(const fetch of [async()=>{throw new Error('private unexpected error');},async()=>({ok:true,json:async()=>({})})]) {
    const page=toolManagerPage(fetch);await page.element('open-tool-manager').dispatch('click');
    assert.match(page.element('tool-policy-status').textContent,/读取失败/);
    assert.doesNotMatch(page.element('tool-policy-status').textContent,/private/);
    assert.equal(page.element('tool-catalog-list').children.length,0);assert.equal(page.element('tool-policy-save').disabled,true);
    await page.element('tool-policy-close').dispatch('click');assert.equal(page.element('tool-manager').hidden,true);
  }
});

test('Tool Manager pending save locks duplicate operations and mode switching',async()=>{
  let resolve;const page=toolManagerPage(async(_url,options)=>options.method==='PUT'?new Promise(r=>{resolve=r;}):r2Reply(toolManagerFixture()));
  await page.element('open-tool-manager').dispatch('click');const pending=page.element('tool-policy-save').dispatch('click');
  await new Promise(setImmediate);assert.equal(page.element('tool-policy-save').disabled,true);
  await page.element('tool-policy-assistant').dispatch('click');assert.equal(vm.runInContext('toolPolicyMode',page.context),'analysis');
  await page.element('tool-policy-close').dispatch('click');assert.equal(page.element('tool-manager').open,true);
  resolve(r2Reply(toolManagerFixture([],[],'USER_OVERRIDE')));await pending;
  assert.equal(page.element('tool-policy-save').disabled,false);
});

test('Tool Manager Assistant workspace entry opens the shared Assistant policy tab',async()=>{
  const page=assistantPage(async()=>r2Reply(toolManagerFixture()));
  await enterAssistant(page);
  await page.element('assistant-tool').dispatch('click');
  assert.equal(vm.runInContext('toolPolicyMode',page.context),'assistant');
  assert.match(page.element('tool-manager-title').textContent,/Assistant/);
  assert.equal(page.element('tool-catalog-list').children.length,2);
});

function assistantBootstrap(epoch='assistant-epoch') {
  return {epoch,default_preset_id:'qwen-preset',fixed_mode:{thinking:'off',response_mode:'normal'},
    presets:[{preset_id:'qwen-preset',display_name:'Qwen 3.8 Flash',runtime_type:'cloud'},
      {preset_id:'deepseek-preset',display_name:'DeepSeek Flash',runtime_type:'cloud'},
      {preset_id:'ollama-preset',display_name:'Ollama Qwen3.5 4B',runtime_type:'local'}]};
}

function assistantResult(changes={}) {
  return {successful_turn:true,status:'completed',final_text:'概念回答',completed_at:'2026-10-06T01:00:00Z',
    final_finish_reason:'stop',history_turns_received:0,history_turns_sent:0,history_trimmed:0,
    tool_activity:{used_tool:false},request_1:{outcome:'final_answer'},request_2:{outcome:'not_started'},
    usage:{request_count:1,usage:{input_tokens:10,output_tokens:8,total_tokens:18,source:'provider'}},
    total_latency_ms:3200,...changes};
}

function assistantPage(handler=async()=>r2Reply({result:assistantResult()}), bootstrap=assistantBootstrap()) {
  const calls=[];
  const page=makePage(async(url,options={})=>{
    calls.push({url,options});
    if(url==='/api/assistant/bootstrap')return r2Reply(bootstrap);
    return handler(url,options);
  });
  page.calls=calls;
  vm.runInContext('credentialCsrf="offline-csrf"; bindToolManagerControls(); bindAssistantControls()',page.context);
  return page;
}

async function enterAssistant(page) { await page.element('application-mode-toggle').dispatch('click'); }
async function sendAssistantQuestion(page, question='什么是溶氧？') {
  page.element('assistant-input').value=question;
  page.element('assistant-confirm-network').checked=true;
  return page.element('assistant-send').dispatch('click');
}
function assistantStateJson(page, expression='assistantState') {
  // Inspect UI records, never serialize transient control tokens or Node timer handles.
  return JSON.parse(vm.runInContext(`JSON.stringify(${expression},(key,value)=>key==='pendingRequest'?null:value)`,page.context));
}
function allElementText(node) { return node.textContent+' '+node.children.map(allElementText).join(' '); }

test('Assistant single fixed-width toggle replaces both old status buttons',()=>{
  assert.match(html,/id="application-mode-toggle"/);
  assert.doesNotMatch(html,/analysis-mode-entry|assistant-mode-entry|application-mode-status|Coming Soon/);
  assert.match(css,/#application-mode-toggle\s*\{[^}]*width: 240px/);
  const workspace=html.slice(html.indexOf('id="assistant-workspace"'),html.indexOf('id="tool-manager"'));
  assert.match(workspace,/Thinking OFF · Normal/);
  assert.doesNotMatch(workspace,/tool-trace|Reasoning|capability|Base URL/);
});

test('Assistant workspace switch preserves Analysis DOM runtime scenario result drafts and scroll',async()=>{
  const page=assistantPage(async()=>assert.fail('switch must not generate or Apply'));
  vm.runInContext('accessMode="managed_custom"; profiles=[{profile_id:"origin"}]; formMode="edit"; editDraft={model:"draft-model"}',page.context);
  page.element('profile').value='origin';page.element('scenario').value='low_oxygen';page.element('question').value='Analysis草稿';
  page.element('model-inference').textContent='原结果';page.element('analysis-controls').scrollTop=88;
  page.context.window.scrollY=140;page.context.window.scrollTo=(_x,y)=>{page.context.window.scrollY=y;};
  await enterAssistant(page);
  assert.equal(page.element('analysis-workspace').hidden,true);
  assert.equal(page.element('assistant-workspace').hidden,false);
  page.element('assistant-input').value='助手草稿';await page.element('assistant-input').dispatch('input');
  page.element('assistant-messages').scrollTop=50;page.context.window.scrollY=20;
  await page.element('application-mode-toggle').dispatch('click');
  assert.equal(page.element('analysis-workspace').hidden,false);
  assert.equal(page.element('profile').value,'origin');assert.equal(page.element('scenario').value,'low_oxygen');
  assert.equal(page.element('question').value,'Analysis草稿');assert.equal(page.element('model-inference').textContent,'原结果');
  assert.equal(page.context.window.scrollY,140);assert.equal(page.element('analysis-controls').scrollTop,88);
  assert.equal(vm.runInContext('accessMode',page.context),'managed_custom');
  assert.equal(vm.runInContext('editDraft.model',page.context),'draft-model');
  await page.element('application-mode-toggle').dispatch('click');
  assert.equal(page.element('assistant-input').value,'助手草稿');assert.equal(page.element('assistant-messages').scrollTop,50);
  assert.deepEqual(page.calls.map(c=>c.url),['/api/assistant/bootstrap']);
});

test('Assistant selector uses only bootstrap Presets OFF Normal and preserves Analysis model',async()=>{
  const page=assistantPage();page.element('profile').value='analysis-profile';await enterAssistant(page);
  assert.deepEqual(page.element('assistant-preset').children.map(x=>x.textContent),['请选择模型','Qwen 3.8 Flash','DeepSeek Flash','Ollama Qwen3.5 4B']);
  assert.equal(page.element('assistant-preset').value,'qwen-preset');
  page.element('assistant-preset').value='ollama-preset';await page.element('assistant-preset').dispatch('change');
  assert.equal(page.element('profile').value,'analysis-profile');
  assert.equal(page.element('assistant-network-label').textContent,'LOCAL MODEL REQUEST');
  assert.doesNotMatch(page.element('assistant-network-note').textContent,/Mock|离线/);
});

test('Assistant Send requires question and explicit per-send network confirmation',async()=>{
  const page=assistantPage();await enterAssistant(page);
  await page.element('assistant-send').dispatch('click');assert.match(page.element('assistant-notice').textContent,/请输入/);
  page.element('assistant-input').value='问题';await page.element('assistant-send').dispatch('click');
  assert.match(page.element('assistant-notice').textContent,/NETWORK_CONFIRMATION_REQUIRED/);
  page.element('assistant-input').value='甲'.repeat(683);page.element('assistant-confirm-network').checked=true;
  await page.element('assistant-send').dispatch('click');assert.match(page.element('assistant-notice').textContent,/QUESTION_TOO_LARGE/);
  assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,0);
});

test('Assistant success commits only complete pairs and sends no Analysis facts raw Tool or connection',async()=>{
  const page=assistantPage();await enterAssistant(page);await sendAssistantQuestion(page);
  const state=assistantStateJson(page);
  assert.deepEqual(state.completedTurns,[{user:'什么是溶氧？',assistant:'概念回答',completed_at:'2026-10-06T01:00:00Z'}]);
  assert.equal(state.displayEntries.length,2);assert.equal(state.displayEntries[1].queried_this_turn,false);
  assert.match(allElementText(page.element('assistant-messages')),/未调用 Tool/);
  assert.equal(page.element('assistant-confirm-network').checked,false);
  assert.match(page.element('assistant-run-summary').textContent,/Completed.*Qwen.*0 Tool.*1 Requests.*3.20s/);
  const body=JSON.parse(page.calls.find(c=>c.url==='/api/assistant/chat').options.body);
  assert.deepEqual(Object.keys(body).sort(),['control_token','epoch','history','preset_id','question','request_id','confirm_network'].sort());
  assert.deepEqual(body.history,[]);assert.equal(body.epoch,'assistant-epoch');
  await sendAssistantQuestion(page,'再解释一下');
  const sent=JSON.parse(page.calls.filter(c=>c.url==='/api/assistant/chat')[1].options.body);
  assert.deepEqual(sent.history,state.completedTurns);
});

test('Assistant pending run blocks duplicate Send workspace model clear and history commit',async()=>{
  let resolve;const page=assistantPage(async()=>new Promise(done=>{resolve=done;}));await enterAssistant(page);
  const pending=sendAssistantQuestion(page);while(!resolve)await new Promise(done=>setImmediate(done));
  assert.equal(page.element('application-mode-toggle').disabled,true);assert.equal(page.element('assistant-preset').disabled,true);
  assert.equal(page.element('assistant-clear').disabled,true);assert.equal(page.element('assistant-send').disabled,true);
  assert.equal(assistantStateJson(page).completedTurns.length,0);
  assert.match(allElementText(page.element('assistant-messages')),/等待回答/);
  await page.element('application-mode-toggle').dispatch('click');await page.element('assistant-send').dispatch('click');
  assert.equal(vm.runInContext('applicationMode',page.context),'assistant');
  assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,1);
  resolve(r2Reply({result:assistantResult()}));await pending;
  assert.equal(page.element('application-mode-toggle').disabled,false);
});

test('Assistant failed cancelled truncated empty unknown-finish turns never enter history or reveal partial output',async()=>{
  for(const changes of [{successful_turn:false,status:'failed',error_code:'READ_TIMEOUT'},
    {successful_turn:false,status:'cancelled',error_code:'USER_CANCELLED'},
    {successful_turn:false,status:'failed',error_code:'ASSISTANT_RESPONSE_TRUNCATED'},
    {final_text:''},{final_finish_reason:'length'},{final_finish_reason:'unrecognized'}]) {
    const page=assistantPage(async()=>r2Reply({result:assistantResult({final_text:'secret partial body',...changes})}));
    await enterAssistant(page);await sendAssistantQuestion(page);
    const state=assistantStateJson(page);assert.equal(state.completedTurns.length,0);
    assert.equal(state.displayEntries.filter(e=>e.kind==='assistant').length,0);
    assert.doesNotMatch(allElementText(page.element('assistant-messages')),/secret partial/);
    assert.equal(page.element('assistant-input').value,'什么是溶氧？');
    assert.equal(page.element('assistant-confirm-network').checked,false);
    assert.match(page.element('assistant-run-summary').textContent,/Failed|Cancelled/);
  }
});

test('Assistant lightweight tool activity shows query status time and experimental score without Raw Trace',async()=>{
  for(const [name,status,quality,freshness] of [['get_current_water_quality','OK','valid','fresh'],
    ['get_current_water_quality','OK','invalid','stale'],['get_current_water_quality','PARTIAL','partial','fresh'],
    ['get_current_water_quality','NO_DATA',undefined,undefined],
    ['get_current_water_quality','NO_MATCH',undefined,undefined],['score_current_water_quality','OK','valid','fresh']]) {
    const activity={used_tool:true,tool_name:name,tool_status:status,quality,freshness,duration_ms:2,
      evaluated_at:'2026-10-06T01:00:00Z'};
    const page=assistantPage(async()=>r2Reply({result:assistantResult({tool_activity:activity,
      request_1:{outcome:'tool_calls'},request_2:{outcome:'final_answer'},usage:{request_count:2,usage:{}},
      tool_result:{secret:'raw result must not persist'},reasoning_content:'private reasoning',prompt:'private prompt'})}));
    await enterAssistant(page);await sendAssistantQuestion(page,'现在水质怎么样？');
    const article=page.element('assistant-messages').children[1],detail=article.children.find(c=>c.children[0]?.textContent==='使用了 1 个 Tool');
    assert.ok(detail);assert.notEqual(detail.open,true);
    const text=allElementText(detail);assert.match(text,new RegExp(name));assert.match(text,new RegExp(status));
    assert.match(text,/evaluated_at/);if(freshness)assert.match(text,new RegExp(freshness));
    if(name==='score_current_water_quality')assert.match(text,/EXPERIMENTAL \/ NOT PROFESSIONAL STANDARD/);
    assert.doesNotMatch(text,/Request #|Raw|Authorization|Prompt|Usage/);
    assert.doesNotMatch(JSON.stringify(assistantStateJson(page)),/raw result must not persist|private reasoning|private prompt/);
    assert.match(allElementText(page.element('assistant-run-details')),/Request #1 outcome.*tool_calls.*Request #2 outcome.*final_answer/);
  }
});

test('Assistant plain text instruction is present while Markdown and HTML still render as safe literal text',async()=>{
  const backend=fs.readFileSync(path.join(__dirname,'../src/fishery_ai/assistant.py'),'utf8');
  assert.match(backend,/最终回答使用简洁纯文本/);
  assert.match(backend,/不要输出Markdown表格、Markdown粗体或代码围栏/);
  const payload='**粗体**\n| DO | 值 |\n| -- | -- |\n```json\n{}\n```\n<script>bad()</script>';
  const page=assistantPage(async()=>r2Reply({result:assistantResult({final_text:payload})}));
  await enterAssistant(page);await sendAssistantQuestion(page);
  const text=page.element('assistant-messages').children[1].children[0];
  assert.equal(text.textContent,payload);assert.equal(text.children.length,0);
  assert.doesNotMatch(source,/marked\.|markdownit|DOMPurify/);
});

test('Assistant history budget trims complete pairs while keeping more display records',async()=>{
  const page=assistantPage();await enterAssistant(page);
  vm.runInContext(`assistantState.completedTurns=Array.from({length:9},(_,i)=>({user:'旧'+i+'甲'.repeat(650),assistant:'旧回答',completed_at:'2026-10-06T01:00:00Z'}));
    assistantState.displayEntries=[{kind:'user',text:'仍可显示旧记录'}]`,page.context);
  await sendAssistantQuestion(page);
  const history=JSON.parse(page.calls.find(c=>c.url==='/api/assistant/chat').options.body).history;
  assert.ok(history.length<6);assert.ok(Buffer.byteLength(JSON.stringify(history))<=6144);
  assert.ok(history.every(t=>Object.keys(t).sort().join(',')==='assistant,completed_at,user'));
  assert.match(page.element('assistant-history-notice').textContent,/较早对话未发送.*不代表模型收到全部/);
  assert.match(allElementText(page.element('assistant-messages')),/仍可显示旧记录/);
});

test('Assistant epoch expiration clears old history activity retains input bootstraps once without resend',async()=>{
  let requests=0;
  const page=assistantPage(async()=>{requests++;return r2Reply({error_code:'ASSISTANT_SESSION_EXPIRED'},false);});
  await enterAssistant(page);
  vm.runInContext(`assistantState.completedTurns=[{user:'旧',assistant:'DO2.2',completed_at:'2026-10-06T01:00:00Z'}];
    assistantState.toolActivity={used_tool:true};assistantState.displayEntries=[{kind:'user',text:'旧'}]`,page.context);
  await sendAssistantQuestion(page,'当前问题保留');
  assert.equal(assistantStateJson(page).completedTurns.length,0);assert.equal(assistantStateJson(page).toolActivity,null);
  assert.equal(page.element('assistant-input').value,'当前问题保留');assert.equal(requests,1);
  assert.equal(page.calls.filter(c=>c.url==='/api/assistant/bootstrap').length,2);
  assert.match(page.element('assistant-notice').textContent,/后端已重启.*重新发送/);
});

test('Assistant model change and clear confirm affect only Assistant and preserve draft',async()=>{
  const page=assistantPage();await enterAssistant(page);await sendAssistantQuestion(page);
  page.element('assistant-input').value='未发送草稿';await page.element('assistant-input').dispatch('input');
  page.element('model-inference').textContent='原Analysis';page.element('profile').value='analysis-origin';
  page.context.window.confirm=()=>false;
  page.element('assistant-preset').value='deepseek-preset';await page.element('assistant-preset').dispatch('change');
  assert.equal(page.element('assistant-preset').value,'qwen-preset');assert.equal(assistantStateJson(page).completedTurns.length,1);
  await page.element('assistant-clear').dispatch('click');assert.equal(assistantStateJson(page).completedTurns.length,1);
  page.context.window.confirm=()=>true;page.element('assistant-preset').value='deepseek-preset';await page.element('assistant-preset').dispatch('change');
  assert.equal(assistantStateJson(page).completedTurns.length,0);assert.equal(page.element('assistant-input').value,'未发送草稿');
  assert.equal(page.element('model-inference').textContent,'原Analysis');assert.equal(page.element('profile').value,'analysis-origin');
  assert.equal(page.calls.filter(c=>c.options.method==='PUT'||c.options.method==='DELETE').length,0);
});

test('Assistant output HTML is textContent and raw exception stays a safe code',async()=>{
  const payload='<img src=x onerror=alert(1)><script>steal()</script>';
  const page=assistantPage(async()=>r2Reply({result:assistantResult({final_text:payload})}));await enterAssistant(page);await sendAssistantQuestion(page);
  const text=page.element('assistant-messages').children[1].children[0];assert.equal(text.textContent,payload);assert.equal(text.children.length,0);
  const failed=assistantPage(async()=>{throw new Error('traceback PRIVATE_SECRET filesystem path');});await enterAssistant(failed);await sendAssistantQuestion(failed);
  assert.match(failed.element('assistant-notice').textContent,/NETWORK_ERROR/);assert.doesNotMatch(allElementText(failed.element('assistant-messages')),/PRIVATE_SECRET|traceback/);
});

test('Assistant Stop cancels backend first rejects late answers and leaves Analysis status unchanged',async()=>{
  let resolve;const calls=[];
  const page=assistantPage(async(url)=>{
    calls.push(url);if(url.endsWith('/cancel'))return r2Reply({state:'CANCELLED',backend_io_closed:true});
    return new Promise(done=>{resolve=done;});
  });await enterAssistant(page);page.element('status').textContent='原Analysis状态';
  const pending=sendAssistantQuestion(page);while(!resolve)await new Promise(done=>setImmediate(done));
  await page.element('assistant-stop').dispatch('click');
  assert.ok(calls.some(url=>url.endsWith('/cancel')));assert.match(page.element('assistant-run-summary').textContent,/Cancelled/);
  assert.equal(page.element('status').textContent,'原Analysis状态');assert.equal(page.element('assistant-input').value,'什么是溶氧？');
  resolve(r2Reply({result:assistantResult({final_text:'late response must not win'})}));await pending;
  assert.equal(assistantStateJson(page).completedTurns.length,0);assert.doesNotMatch(allElementText(page.element('assistant-messages')),/late response/);
  assert.equal(page.element('application-mode-toggle').disabled,false);
});

test('Assistant live phase observation reads actual shared request status without model streaming',async()=>{
  let resolve;const phases=['REQUEST_1','RUNNING_TOOL','REQUEST_2'];let index=0;
  const page=assistantPage(async(url)=>{
    if(url.endsWith('/status'))return r2Reply({state:'RUNNING',phase:phases[Math.min(index++,2)]});
    return new Promise(done=>{resolve=done;});
  });await enterAssistant(page);
  vm.runInContext('let observedPhases=[];const originalSetRun=setAssistantRun;setAssistantRun=(phase,...args)=>{observedPhases.push(phase);return originalSetRun(phase,...args)}',page.context);
  const pending=sendAssistantQuestion(page);while(!resolve)await new Promise(done=>setImmediate(done));
  await new Promise(done=>setTimeout(done,1150));
  assert.deepEqual(assistantStateJson(page,'observedPhases'),['Preparing','Request #1','Running Tool','Request #2']);
  resolve(r2Reply({result:assistantResult()}));await pending;
  assert.match(page.element('assistant-run-summary').textContent,/Completed/);
});

test('Assistant Ctrl Enter sends and normal Enter retains multiline input',async()=>{
  const page=assistantPage();await enterAssistant(page);page.element('assistant-input').value='第一行\n第二行';page.element('assistant-confirm-network').checked=true;
  let prevented=false;
  await page.element('assistant-input').dispatch('keydown',{key:'Enter',ctrlKey:false,preventDefault:()=>{prevented=true;}});
  assert.equal(prevented,false);assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,0);
  await page.element('assistant-input').dispatch('keydown',{key:'Enter',ctrlKey:true,preventDefault:()=>{prevented=true;}});
  assert.equal(prevented,true);assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,1);
});

test('Assistant current-fact follow-up passes only old text pairs and renders newly queried mock facts',async()=>{
  let oxygen=2.2;
  const page=assistantPage(async(url,options)=>{
    assert.equal(url,'/api/assistant/chat');const body=JSON.parse(options.body);
    const current=/现在|当前/.test(body.question);
    const activity=current?{used_tool:true,tool_name:'get_current_water_quality',tool_status:'OK',freshness:'fresh'}:{used_tool:false};
    const text=current?`本轮Tool查询DO=${oxygen}`:'刚才2.2是历史低氧读数';
    return r2Reply({result:assistantResult({final_text:text,tool_activity:activity,raw_tool_result:{oxygen}})});
  });await enterAssistant(page);await sendAssistantQuestion(page,'现在水质怎么样？');
  await page.element('application-mode-toggle').dispatch('click');oxygen=6.4;
  await page.element('application-mode-toggle').dispatch('click');await sendAssistantQuestion(page,'现在仍然是2.2吗？');
  const body=JSON.parse(page.calls.filter(c=>c.url==='/api/assistant/chat')[1].options.body);
  assert.match(body.history[0].assistant,/2.2/);assert.ok(body.history.every(t=>Object.keys(t).length===3));
  assert.match(assistantStateJson(page).completedTurns[1].assistant,/6.4/);
  await sendAssistantQuestion(page,'刚才2.2意味着什么？');
  assert.equal(assistantStateJson(page).displayEntries.at(-1).activity.used_tool,false);
});

test('Assistant no default Preset keeps empty selection and loading failures do not send models',async()=>{
  const page=assistantPage(undefined,{...assistantBootstrap(),default_preset_id:null});await enterAssistant(page);
  assert.equal(page.element('assistant-preset').value,'');assert.equal(page.element('assistant-send').disabled,true);
  page.element('assistant-input').value='问题';page.element('assistant-confirm-network').checked=true;
  await page.element('assistant-send').dispatch('click');assert.match(page.element('assistant-notice').textContent,/请选择模型/);
  assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,0);
  vm.runInContext('assistantState.epoch=null',page.context);
  await page.element('assistant-send').dispatch('click');
  assert.equal(page.calls.filter(c=>c.url==='/api/assistant/chat').length,0);
});

test('Assistant prepare lock also blocks switching while an Analysis handle is being prepared',async()=>{
  let release;const page=makePage(async()=>new Promise(done=>{release=done;}),{ownExecutionRoutes:true});
  vm.runInContext('credentialCsrf="offline-csrf";bindAssistantControls()',page.context);
  const pending=vm.runInContext('beginExecution()',page.context);
  while(!release)await new Promise(done=>setImmediate(done));
  await page.element('application-mode-toggle').dispatch('click');
  assert.equal(vm.runInContext('applicationMode',page.context),'analysis');
  assert.equal(page.element('application-mode-toggle').disabled,true);
  release(r2Reply({request_id:'offline',control_token:'offline-control'}));await pending;
  vm.runInContext('finishExecution()',page.context);
  assert.equal(page.element('application-mode-toggle').disabled,false);
});

test('Assistant Stop works at either model phase and unsafe cancellation failures stay unconfirmed',async()=>{
  for(const phase of ['Request #1','Request #2']) {
    let release;const page=assistantPage(async(url)=>url.endsWith('/cancel')
      ?r2Reply({state:'CANCELLED',backend_io_closed:true}):new Promise(done=>{release=done;}));
    await enterAssistant(page);const pending=sendAssistantQuestion(page);
    while(!release)await new Promise(done=>setImmediate(done));
    vm.runInContext(`setAssistantRun('${phase}')`,page.context);
    await page.element('assistant-stop').dispatch('click');
    release(r2Reply({result:assistantResult()}));await pending;
    assert.equal(assistantStateJson(page).completedTurns.length,0);assert.match(page.element('assistant-run-summary').textContent,/Cancelled/);
  }
  let release;const page=assistantPage(async(url)=>{
    if(url.endsWith('/cancel'))throw new Error('private SDK traceback');
    return new Promise(done=>{release=done;});
  });await enterAssistant(page);const pending=sendAssistantQuestion(page);
  while(!release)await new Promise(done=>setImmediate(done));
  await page.element('assistant-stop').dispatch('click');
  assert.match(page.element('assistant-notice').textContent,/取消未确认.*后端状态未知/);
  assert.doesNotMatch(page.element('assistant-notice').textContent,/SDK traceback/);
  release(r2Reply({result:assistantResult()}));await pending;
  assert.equal(assistantStateJson(page).completedTurns.length,0);
});

test('Assistant invalid response JSON gives a safe failure and full details use unavailable for absent Usage',async()=>{
  const page=assistantPage(async()=>({ok:true,json:async()=>{throw new Error('SECRET raw response');}}));
  await enterAssistant(page);await sendAssistantQuestion(page);
  assert.match(page.element('assistant-notice').textContent,/NETWORK_ERROR/);
  assert.doesNotMatch(allElementText(page.element('assistant-messages')),/SECRET/);
  const missing=assistantPage(async()=>r2Reply({result:assistantResult({usage:{request_count:1}})}));
  await enterAssistant(missing);await sendAssistantQuestion(missing);
  assert.match(allElementText(missing.element('assistant-run-details')),/input_tokens\s+unavailable.*output_tokens\s+unavailable/);
  assert.equal(missing.element('assistant-run').open,false);
});

function makePage(fetch, {ownExecutionRoutes = false} = {}) {
  const controls = new Map();
  class Element {
    constructor() {
      this.value = '';
      this.textContent = '';
      this.hidden = false;
      this.disabled = false;
      this.checked = false;
      this.children = [];
      this.listeners = new Map();
      this.classList = {toggle() {}, add() {}, remove() {}};
    }
    append(...items) { this.children.push(...items); }
    prepend(...items) { this.children.unshift(...items); }
    replaceChildren(...items) { this.children = items; }
    addEventListener(type, handler) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(handler);
    }
    async dispatch(type, extra = {}) {
      const event = {type, target: this, ...extra};
      return Promise.all((this.listeners.get(type) || []).map((handler) => handler(event)));
    }
    removeAttribute() {}
    setAttribute() {}
    focus() {}
    showModal() { this.open = true; }
    close() { this.open = false; }
    checkValidity() { return true; }
  }
  const element = (id) => {
    if (!knownIds.has(id)) return null;
    if (!controls.has(id)) controls.set(id, new Element());
    return controls.get(id);
  };
  const document = {getElementById: element, createElement: () => new Element()};
  const guardedFetch = async (url, options) => {
    if (!ownExecutionRoutes && url === '/api/requests') return r2Reply({request_id:'offline-request',control_token:'offline-control'});
    return fetch(url, options);
  };
  const context = vm.createContext({document, fetch:guardedFetch, TextDecoder, TextEncoder, Uint8Array, AbortController, setTimeout, clearTimeout,
    window: {confirm: () => true}});
  vm.runInContext(source, context);
  return {element, context};
}

function sseResponse(events, chunkSize = 17) {
  const wire = events.map(([kind, data]) => `event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`).join('');
  const bytes = new TextEncoder().encode(wire);
  let offset = 0;
  return {ok: true, status: 200, body: {getReader: () => ({
    async read() {
      if (offset >= bytes.length) return {done: true};
      const value = bytes.slice(offset, offset + chunkSize);
      offset += chunkSize;
      return {done: false, value};
    },
  })}};
}

test('Built-in Ollama auth NONE hides Secret controls and never queries credentials', async () => {
  const profile = {profile_id:'ollama-qwen35-4b-local',display_name:'Ollama',service_id:'ollama',
    model:'qwen3.5:4b',base_url:'http://127.0.0.1:11434/v1',adapter_id:'generic_openai_chat',
    runtime_type:'local',profile_status:'experimental',source:'built_in',auth_spec:'NONE',capabilities:{}};
  const calls=[];
  const page=makePage(async (url) => {
    calls.push(url);
    assert.notEqual(url,'/api/secret-status');
    return {ok:true,json:async()=>({editable:false,fields:{display_name:'Ollama',service_id:'ollama',
      adapter_id:'generic_openai_chat',base_url:profile.base_url,model:profile.model,
      provider_kind:'local',secret_env:'',auth_spec:'NONE'}})};
  });
  vm.runInContext(`profiles=[${JSON.stringify(profile)}];presets=[]`,page.context);
  page.element('profile').value=profile.profile_id;
  vm.runInContext('updateProfile()',page.context);
  assert.equal(page.element('secret-env-fields').hidden,true);
  await new Promise(setImmediate);
  for(const id of ['secret-env-fields','secret-status','selected-secret-status']) {
    assert.equal(page.element(id).hidden,true);
  }
  assert.equal(page.element('custom-auth').value,'NONE');
  assert.equal(page.element('custom-auth').disabled,true);
  assert.equal(page.element('custom-secret-env').required,false);
  assert.deepEqual(calls,[`/api/profiles/${profile.profile_id}`]);
  assert.doesNotMatch(page.element('secret-status').textContent,/Local 可选|local-no-key/);
});

test('Credential status shows source and readonly scope without values or fingerprints',async()=>{
  const replies=[{availability:'PRESENT',source:'PROCESS_ENV',editable:false},
    {availability:'PRESENT',source:'PROJECT_ENV',editable:true},
    {availability:'MISSING',source:'PROCESS_ENV',editable:false}];
  const requests=[];
  const page=makePage(async(_url,options)=>{
    requests.push(JSON.parse(options.body));
    return {ok:true,json:async()=>replies.shift()};
  });
  const connection={profile_id:'exact-cloud',auth_spec:'REQUIRED_BEARER'};
  await vm.runInContext(`showSecret('TEST_FAKE_KEY','secret-status',()=>true,${JSON.stringify(connection)})`,page.context);
  assert.match(page.element('secret-status').textContent,/TEST_FAKE_KEY: PRESENT.*PROCESS_ENV.*外部只读/);
  await vm.runInContext(`showSecret('TEST_FAKE_KEY','secret-status',()=>true,${JSON.stringify(connection)})`,page.context);
  assert.match(page.element('secret-status').textContent,/PRESENT.*PROJECT_ENV.*本地凭据管理.*编辑/);
  await vm.runInContext(`showSecret('TEST_FAKE_KEY','secret-status',()=>true,${JSON.stringify(connection)})`,page.context);
  assert.match(page.element('secret-status').textContent,/MISSING.*PROCESS_ENV.*外部只读/);
  assert.deepEqual(requests,Array(3).fill({profile_id:'exact-cloud'}));
  assert.match(html,/id="credential-value" type="password" autocomplete="new-password"/);
});

test('Auth requirements are independent of deployment and changes invalidate connection test',async()=>{
  const page=makePage(async()=>{throw Error('offline only');});
  vm.runInContext('newProfile()',page.context);
  page.element('custom-deployment').value='local';
  vm.runInContext('updateSecretRequirement()',page.context);
  assert.equal(page.element('custom-secret-env').required,true);
  page.element('custom-auth').value='OPTIONAL_BEARER';
  vm.runInContext('updateSecretRequirement()',page.context);
  assert.equal(page.element('custom-secret-env').required,false);
  page.element('custom-deployment').value='cloud';
  vm.runInContext('updateSecretRequirement()',page.context);
  assert.equal(page.element('custom-secret-env').required,false);
  const base={service_id:'custom',model_family:'unknown',adapter_id:'generic_openai_chat',
    base_url:'https://example.invalid/v1',model:'m',secret_env:'',provider_kind:'cloud'};
  const optional=vm.runInContext(`connectionFingerprint(${JSON.stringify({...base,auth_spec:'OPTIONAL_BEARER'})})`,page.context);
  const required=vm.runInContext(`connectionFingerprint(${JSON.stringify({...base,auth_spec:'REQUIRED_BEARER'})})`,page.context);
  assert.notEqual(optional,required);
});

test('late Credential status cannot overwrite the current Profile status',async()=>{
  let finish;
  const page=makePage(async()=>({ok:true,json:()=>new Promise(resolve=>{finish=resolve;})}));
  vm.runInContext('let currentCredentialProfile="old"',page.context);
  const pending=vm.runInContext(`showSecret('OLD_FAKE_KEY','selected-secret-status',
    ()=>currentCredentialProfile==='old',{profile_id:'old',auth_spec:'REQUIRED_BEARER'})`,page.context);
  await new Promise(setImmediate);
  vm.runInContext('currentCredentialProfile="new"',page.context);
  await vm.runInContext(`showSecret('','selected-secret-status',()=>true,
    {profile_id:'new',auth_spec:'NONE'})`,page.context);
  finish({availability:'PRESENT',source:'PROJECT_ENV',editable:true});
  await pending;
  assert.equal(page.element('selected-secret-status').hidden,true);
  assert.equal(page.element('selected-secret-status').textContent,'');
});

test('Credential status file error stays a safe code rather than a false MISSING',async()=>{
  const page=makePage(async()=>({ok:false,json:async()=>({error_code:'CREDENTIAL_FILE_ERROR'})}));
  await vm.runInContext(`showSecret('TEST_FAKE_KEY','secret-status',()=>true,
    {profile_id:'exact-cloud',auth_spec:'REQUIRED_BEARER'})`,page.context);
  assert.match(page.element('secret-status').textContent,/CREDENTIAL_FILE_ERROR/);
  assert.doesNotMatch(page.element('secret-status').textContent,/MISSING/);
});

function setProfile(page, real = false) {
  const profile = real
    ? {profile_id: 'qwen-plus-experimental', runtime_type: 'cloud'}
    : {profile_id: 'mock-demo', runtime_type: 'mock'};
  vm.runInContext(`profiles = [${JSON.stringify(profile)}];credentialCsrf='offline-csrf'`, page.context);
  page.element('profile').value = profile.profile_id;
  page.element('response-mode').value = 'streaming';
  page.element('scenario').value = 'low_oxygen';
  page.element('question').value = '当前水质情况怎么样？';
  if (real) page.element('confirm-network').checked = true;
}

test('Mock SSE completes through the browser handler with split UTF-8 chunks', async () => {
  const facts = {water_quality: {temperature_c: 28, ph: 7.5, dissolved_oxygen_mg_l: 2.2}};
  const result = {runtime: {profile_id: 'mock-demo', provider_id: 'custom', model: 'offline-mock'},
    observed_facts: facts, rule_results: [{code: 'OXYGEN_CRITICAL_LOW', severity: 'critical', message: '低氧'}],
    evidence: [], inference: '低氧', recommendations: ['增氧'], uncertainty: [],
    generated_text: '你好', structured_parse_ok: true, usage: {source: 'unavailable'}, status: 'completed'};
  const response = sseResponse([
    ['analysis_started', {}], ['facts_ready', {observed_facts: facts, runtime: result.runtime}],
    ['rules_ready', {rule_results: result.rule_results}], ['evidence_ready', {evidence: []}],
    ['content_delta', {delta: '你'}], ['content_delta', {delta: '好'}],
    ['usage', {usage: result.usage}],
    ['completed', {result, ttft_ms: 12, total_latency_ms: 30}],
  ], 1);
  const page = makePage(async () => response);
  setProfile(page);
  await vm.runInContext('analyze()', page.context);
  assert.equal(page.element('status').textContent, '流式分析完成。');
  assert.equal(page.element('streaming-output').textContent, '');
  assert.equal(page.element('streaming-preview').hidden, true);
  assert.equal(page.element('model-output').textContent, '你好');
  assert.equal(page.element('model-inference').textContent, '低氧');
  assert.equal(page.element('analyze').disabled, false);
});

test('safe failed SSE event is shown rather than NETWORK_ERROR', async () => {
  const response = sseResponse([
    ['analysis_started', {}], ['failed', {error_code: 'OPTION_UNKNOWN'}],
  ]);
  const page = makePage(async () => response);
  setProfile(page, true);
  await vm.runInContext('analyze()', page.context);
  assert.equal(page.element('status').textContent, '流式分析失败：OPTION_UNKNOWN');
  assert.equal(page.element('confirm-network').checked, false);
});

test('OPTION_UNSUPPORTED and HTTP preflight errors keep their safe codes', async () => {
  const denied = makePage(async () => sseResponse([
    ['failed', {error_code: 'OPTION_UNSUPPORTED'}],
  ]));
  setProfile(denied, true);
  await vm.runInContext('analyze()', denied.context);
  assert.equal(denied.element('status').textContent, '流式分析失败：OPTION_UNSUPPORTED');

  const preflight = makePage(async () => ({ok: false, status: 503,
    json: async () => ({error_code: 'SECRET_MISSING'})}));
  setProfile(preflight, true);
  await vm.runInContext('analyze()', preflight.context);
  assert.equal(preflight.element('status').textContent, '请求未执行：SECRET_MISSING');
});

test('read interruption is classified as STREAM_INTERRUPTED', async () => {
  const page = makePage(async () => ({ok: true, status: 200, body: {getReader: () => ({
    async read() { throw Error('offline simulated read failure'); },
  })}}));
  setProfile(page);
  await vm.runInContext('analyze()', page.context);
  assert.equal(page.element('status').textContent, '流式连接中断：STREAM_INTERRUPTED');
});

test('page rendering failure is not mislabeled as a network failure', async () => {
  let fetchCalled = false;
  const page = makePage(async () => { fetchCalled = true; throw Error('fetch forbidden'); });
  setProfile(page);
  page.element('runtime').replaceChildren = () => { throw Error('simulated DOM failure'); };
  await vm.runInContext('analyze()', page.context);
  assert.equal(page.element('status').textContent, '流式页面显示失败：STREAM_DISPLAY_ERROR');
  assert.equal(fetchCalled, false);
});

test('Runtime selection immediately fills the actual read-only Profile, then edit and new modes', async () => {
  const profiles = [
    {profile_id: 'qwen-plus-experimental', display_name: 'Qwen 预置', provider: 'qwen',
      model: 'qwen-plus', profile_status: 'experimental', runtime_type: 'cloud', source: 'built_in',
      service_id: 'dashscope', model_family: 'qwen',
      capabilities: {streaming: 'supported', streaming_scope_matches: true, source: 'USER_VERIFIED'}},
    {profile_id: 'deepseek-v4-flash-experimental', display_name: 'DeepSeek 预置', provider: 'deepseek_api',
      model: 'deepseek-flash', profile_status: 'experimental', runtime_type: 'cloud', source: 'built_in',
      service_id: 'deepseek_api', model_family: 'deepseek',
      capabilities: {streaming: 'supported', streaming_scope_matches: true, source: 'OFFICIAL_DOCS'}},
    {profile_id: 'custom-one', display_name: '学校服务', provider: 'school',
      model: 'school-model', profile_status: 'custom', runtime_type: 'local', source: 'user_custom'},
    {profile_id: 'mock-demo', display_name: 'Mock', provider: 'mock',
      model: 'offline-mock', profile_status: 'custom', runtime_type: 'mock', source: 'built_in'},
  ];
  const details = {
    'qwen-plus-experimental': {editable: false, fields: {display_name: 'Qwen 预置',
      provider_id: 'qwen', service_id: 'dashscope', model_family: 'qwen', adapter_id: 'openai_chat',
      base_url: 'https://example.invalid/v1', model: 'qwen-plus',
      secret_env: 'DASHSCOPE_API_KEY', provider_kind: 'cloud'}},
    'deepseek-v4-flash-experimental': {editable: false, fields: {display_name: 'DeepSeek 预置',
      provider_id: 'deepseek', service_id: 'deepseek_api', model_family: 'deepseek',
      adapter_id: 'openai_chat', base_url: 'https://example.invalid/v1', model: 'deepseek-flash',
      secret_env: 'DEEPSEEK_API_KEY', provider_kind: 'cloud'}},
    'custom-one': {editable: true, fields: {display_name: '学校服务',
      provider_id: 'school', service_id: 'school', model_family: 'unknown', adapter_id: 'openai_chat',
      base_url: 'http://localhost:11434/v1', model: 'school-model',
      secret_env: '', provider_kind: 'local'}},
    'mock-demo': {editable: false, fields: {display_name: 'Mock', provider_id: 'custom',
      adapter_id: 'generic_openai_chat', base_url: 'http://mock.invalid/v1',
      model: 'offline-mock', secret_env: '', provider_kind: 'mock'}},
  };
  const page = makePage(async (url) => ({ok: true, json: async () =>
    url === '/api/secret-status' ? {status: 'MISSING'} : details[url.split('/').at(-1)]}));
  vm.runInContext(`profiles = ${JSON.stringify(profiles)}; presets = [{id:'dashscope',service_id:'dashscope'}, {id:'custom',service_id:'custom'}]`, page.context);
  page.element('profile').value = 'qwen-plus-experimental';
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('custom-name').value, 'Qwen 预置');
  assert.equal(page.element('custom-model').value, 'qwen-plus');
  assert.equal(page.element('custom-url').value, 'https://example.invalid/v1');
  assert.match(page.element('streaming-capability').textContent, /本机已验证.*SUPPORTED.*service \/ adapter \/ Base URL \/ Model/);
  assert.equal(page.element('custom-name').disabled, true);
  assert.equal(page.element('edit-profile').hidden, true);
  assert.equal(page.element('delete-profile').hidden, true);
  assert.equal(page.element('save-profile').hidden, true);

  page.element('profile').value = 'deepseek-v4-flash-experimental';
  vm.runInContext('updateProfile()', page.context);
  assert.match(page.element('streaming-capability').textContent, /官方文档支持.*SUPPORTED/);

  page.element('profile').value = 'custom-one';
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('custom-name').value, '学校服务');
  assert.equal(page.element('custom-model').value, 'school-model');
  assert.match(page.element('streaming-capability').textContent, /UNKNOWN.*未绑定当前精确连接/);
  assert.equal(page.element('probe-streaming').hidden, false);
  assert.equal(page.element('edit-profile').hidden, false);
  assert.equal(page.element('delete-profile').hidden, false);
  await vm.runInContext('editSelected()', page.context);
  assert.equal(page.element('custom-name').readOnly, true);
  assert.equal(page.element('custom-name').disabled, false);
  assert.equal(page.element('custom-model').disabled, false);
  assert.equal(page.element('save-profile').hidden, false);

  vm.runInContext('newProfile()', page.context);
  for (const id of ['provider-preset', 'custom-name', 'custom-url', 'custom-model']) {
    assert.equal(page.element(id).value, '');
  }
  assert.equal(page.element('custom-name').readOnly, false);
  assert.equal(page.element('custom-name').disabled, false);
});

test('duplicate name shows PROFILE_NAME_EXISTS without any conflict actions', async () => {
  const page = makePage(async () => ({status: 409, ok: false,
    json: async () => ({error_code: 'PROFILE_NAME_EXISTS'})}));
  vm.runInContext('newProfile()', page.context);
  const values = {'provider-preset': 'custom', 'custom-name': '测试配置',
    'custom-provider': 'custom', 'custom-adapter': 'generic_openai_chat',
    'custom-url': 'http://localhost:11434/v1', 'custom-model': 'demo',
    'custom-secret-env': '', 'custom-deployment': 'local', 'custom-auth': 'OPTIONAL_BEARER'};
  for (const [id, value] of Object.entries(values)) page.element(id).value = value;
  await vm.runInContext('saveCustomProfile()', page.context);
  assert.match(page.element('custom-status').textContent, /PROFILE_NAME_EXISTS/);
  assert.equal(page.element('conflict-panel'), null);
});

test('late Profile response cannot overwrite a newer selection or clean New form', async () => {
  let finishQwen;
  const qwenReply = new Promise((resolve) => { finishQwen = resolve; });
  const details = {editable: false, fields: {display_name: 'Qwen 预置',
    provider_id: 'qwen', service_id: 'dashscope', model_family: 'qwen',
    adapter_id: 'openai_chat', base_url: 'https://example.invalid/v1',
    model: 'qwen-plus', secret_env: '', provider_kind: 'cloud'}};
  const page = makePage(async (url) => {
    if (url.endsWith('/qwen-plus-experimental')) return qwenReply;
    return {ok: true, json: async () => ({editable: true, fields: {
      display_name: '学校服务', provider_id: 'school', adapter_id: 'openai_chat',
      base_url: 'http://localhost:11434/v1', model: 'school-model',
      secret_env: '', provider_kind: 'local'}})};
  });
  vm.runInContext(`profiles = ${JSON.stringify([
    {profile_id: 'qwen-plus-experimental', display_name: 'Qwen', provider: 'qwen',
      model: 'qwen-plus', profile_status: 'experimental', runtime_type: 'cloud', source: 'built_in',
      service_id: 'dashscope', model_family: 'qwen',
      capabilities: {streaming: 'supported', streaming_scope_matches: true, source: 'USER_VERIFIED'}},
    {profile_id: 'custom-one', display_name: '学校服务', provider: 'school',
      model: 'school-model', profile_status: 'custom', runtime_type: 'local', source: 'user_custom',
      service_id: 'school', model_family: 'unknown'},
  ])}; presets = [{id:'dashscope',service_id:'dashscope'}, {id:'custom',service_id:'custom'}]`, page.context);
  page.element('profile').value = 'qwen-plus-experimental';
  vm.runInContext('updateProfile()', page.context);
  assert.equal(page.element('custom-name').value, '');
  assert.equal(page.element('custom-model').value, '');
  page.element('profile').value = 'custom-one';
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  finishQwen({ok: true, json: async () => details});
  await new Promise(setImmediate);
  assert.equal(page.element('custom-name').value, '学校服务');
  vm.runInContext('newProfile()', page.context);
  assert.equal(page.element('custom-name').value, '');
});

test('reasoning mode is sent only for a Profile exposing the exact supported controls', async () => {
  let sent = null;
  const page = makePage(async (_url, options) => {
    sent = JSON.parse(options.body);
    return {ok: false, json: async () => ({error_code: 'SECRET_MISSING'})};
  });
  const exact = {profile_id: 'ollama-qwen35', runtime_type: 'local',
    reasoning_modes: ['auto', 'on', 'off']};
  vm.runInContext(`profiles = [${JSON.stringify(exact)}];credentialCsrf='offline-csrf'`, page.context);
  page.element('profile').value = exact.profile_id;
  page.element('scenario').value = 'low_oxygen';
  page.element('question').value = 'test';
  page.element('reasoning-mode').value = 'off';
  page.element('confirm-network').checked = true;
  await vm.runInContext('analyze()', page.context);
  assert.equal(sent.reasoning_mode, 'off');

  const generic = {...exact, profile_id: 'generic-custom', reasoning_modes: ['auto']};
  vm.runInContext(`profiles = [${JSON.stringify(generic)}]`, page.context);
  page.element('profile').value = generic.profile_id;
  page.element('reasoning-mode').value = 'auto';
  page.element('confirm-network').checked = true;
  await vm.runInContext('analyze()', page.context);
  assert.equal(Object.hasOwn(sent, 'reasoning_mode'), false);
});

test('left settings have three layers, desktop independent scroll, and local default Normal OFF', async () => {
  assert.match(html, /<h2>Analysis Model<\/h2>/);
  assert.match(html, /id="capability-panel"/);
  assert.match(html, /本次运行选择/);
  const capStart = html.indexOf('id="capability-panel"');
  const capEnd = html.indexOf('<h3 class="control-section-heading">03', capStart);
  const capabilitySection = html.slice(capStart, capEnd);
  assert.match(capabilitySection, /id="reasoning-mode"/);
  assert.match(capabilitySection, /id="response-mode"/);
  assert.match(capabilitySection, /id="probe-thinking-on"/);
  assert.match(capabilitySection, /id="probe-thinking-off"/);
  assert.match(css, /\.controls\s*\{[^}]*max-height:\s*calc\(100vh - 32px\)[^}]*overflow-y:\s*auto/);
  assert.match(css, /select option:disabled\s*\{\s*color:/);
  assert.match(css, /@media \(max-width: 1000px\).*\.controls \{ position: static; max-height: none; overflow: visible;/);
  const local = {profile_id: 'ollama-qwen35-4b-local', display_name: 'Ollama local',
    service_id: 'ollama', model_family: 'qwen', model: 'qwen3.5:4b', profile_status: 'experimental',
    runtime_type: 'local', source: 'built_in', reasoning_modes: ['auto', 'on', 'off'],
    default_reasoning_mode: 'off', capabilities: {streaming: 'unknown', source: 'UNKNOWN',
      thinking_on: {status: 'supported', source: 'MODEL_METADATA'},
      thinking_off: {status: 'supported', source: 'MODEL_METADATA'}, thinking_default: true}};
  const page = makePage(async () => ({ok: true, json: async () => ({editable: false,
    fields: {display_name: local.display_name, service_id: 'ollama', model_family: 'qwen',
      adapter_id: 'generic_openai_chat', base_url: 'http://127.0.0.1:11434/v1',
      model: local.model, secret_env: '', provider_kind: 'local'}})}));
  vm.runInContext(`profiles = [${JSON.stringify(local)}]; presets = []`, page.context);
  page.element('profile').value = local.profile_id;
  page.element('response-mode').value = 'streaming';
  vm.runInContext('updateProfile()', page.context);
  assert.equal(page.element('response-mode').value, 'normal');
  assert.equal(page.element('reasoning-mode').value, 'off');
  assert.equal(page.element('refresh-metadata').hidden, false);
  assert.equal(page.element('edit-profile').hidden, true);
});

test('editing draft invalidation does not alter selected runtime controls or capability display', () => {
  const page = makePage(async () => ({ok: true, json: async () => ({})}));
  page.element('reasoning-mode').value = 'off';
  page.element('response-mode').value = 'streaming';
  page.element('streaming-capability').textContent = 'SUPPORTED';
  page.element('probe-streaming').hidden = false;
  vm.runInContext('formMode = "edit"; invalidateTest()', page.context);
  assert.equal(page.element('streaming-capability').textContent, 'SUPPORTED');
  assert.equal(page.element('probe-streaming').hidden, false);
  assert.equal(page.element('reasoning-mode').value, 'off');
  assert.equal(page.element('response-mode').value, 'streaming');
});

test('Profile switching restores saved runtime defaults and verified probes move to advanced actions', async () => {
  const first = {profile_id: 'custom-local-a', display_name: 'Local A', provider: 'custom',
    service_id: 'custom', model: 'a', profile_status: 'custom', runtime_type: 'local',
    source: 'user_custom', reasoning_modes: ['auto', 'on', 'off'],
    default_reasoning_mode: 'off', default_response_mode: 'streaming', capabilities: {
      streaming: 'supported', source: 'USER_VERIFIED',
      thinking_on: {status: 'supported', source: 'USER_VERIFIED'},
      thinking_off: {status: 'supported', source: 'USER_VERIFIED'},
      thinking_off_streaming_combination: {status:'supported',source:'USER_VERIFIED'},
    }},
    second = {profile_id: 'custom-local-b', display_name: 'Local B', provider: 'custom',
      service_id: 'custom', model: 'b', profile_status: 'custom', runtime_type: 'local',
      source: 'user_custom', reasoning_modes: ['auto'], default_reasoning_mode: 'auto',
      default_response_mode: 'normal', capabilities: {streaming: 'unknown', source: 'UNKNOWN'}};
  const details = (profile) => ({editable: true, fields: {display_name: profile.display_name,
    service_id: profile.service_id, model_family: 'unknown', adapter_id: 'generic_openai_chat',
    base_url: 'http://localhost:11434/v1', model: profile.model, secret_env: '',
    provider_kind: 'local', default_thinking_mode: profile.default_reasoning_mode,
    default_response_mode: profile.default_response_mode}});
  const page = makePage(async (url) => ({ok: true, json: async () =>
    url === '/api/secret-status' ? {status: 'MISSING'}
      : details([first, second].find((profile) => url.endsWith(profile.profile_id)))}));
  vm.runInContext(`profiles = ${JSON.stringify([first, second])}; presets = []`, page.context);
  page.element('profile').value = first.profile_id;
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('reasoning-mode').value, 'off');
  assert.equal(page.element('response-mode').value, 'streaming');
  assert.equal(page.element('probe-thinking-on').hidden, true);
  assert.equal(page.element('probe-thinking-off').hidden, true);
  assert.equal(page.element('reprobe-thinking-on').hidden, false);
  assert.equal(page.element('reprobe-thinking-off').hidden, false);
  assert.equal(page.element('probe-streaming').hidden, true);
  assert.equal(page.element('reprobe-streaming').hidden, false);

  page.element('profile').value = second.profile_id;
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('reasoning-mode').value, 'auto');
  assert.equal(page.element('response-mode').value, 'normal');
  assert.equal(page.element('probe-streaming').hidden, false);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, true);
  assert.equal(page.element('reasoning-mode').children.find((item) => item.value === 'on').disabled, true);
  page.element('profile').value = first.profile_id;
  vm.runInContext('updateProfile()', page.context);
  assert.equal(page.element('reasoning-mode').value, 'off');
  assert.equal(page.element('response-mode').value, 'streaming');
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, false);
  assert.equal(page.element('reasoning-mode').children.find((item) => item.value === 'off').disabled, false);
});

test('runtime option choices follow exact capabilities and unavailable defaults fall back safely', () => {
  const unknown = {profile_id: 'custom-unknown', display_name: 'Unknown', provider: 'custom',
    service_id: 'custom', model: 'm1', adapter_id: 'openai_chat', base_url: 'http://localhost/v1',
    profile_status: 'custom', runtime_type: 'local', source: 'user_custom',
    stored_default_thinking_mode: 'on', stored_default_response_mode: 'streaming',
    default_reasoning_mode: 'auto', default_response_mode: 'normal', capabilities: {
      streaming: 'unknown', source: 'UNKNOWN',
      thinking_on: {status: 'unknown', source: 'UNKNOWN'},
      thinking_off: {status: 'unsupported', source: 'OFFICIAL_DOCS'},
      reasoning_effort: {status: 'unknown', source: 'UNKNOWN'}, effort_values: ['low', 'high'],
    }};
  const page = makePage(async (url) => ({ok: true, json: async () => url.endsWith('/custom-unknown')
    ? {editable: true, fields: {display_name: 'Unknown', service_id: 'custom', model_family: 'unknown',
      adapter_id: 'openai_chat', base_url: 'http://localhost/v1', model: 'm1', secret_env: '',
      provider_kind: 'local'}} : {status: 'MISSING'}}));
  vm.runInContext(`profiles = [${JSON.stringify(unknown)}]`, page.context);
  page.element('profile').value = unknown.profile_id;
  vm.runInContext('updateProfile()', page.context);
  const choice = (id, value) => page.element(id).children.find((item) => item.value === value);
  assert.equal(page.element('reasoning-mode').value, 'auto');
  assert.equal(page.element('response-mode').value, 'normal');
  assert.equal(page.element('reasoning-effort').value, '');
  assert.equal(choice('reasoning-mode', 'auto').disabled, false);
  assert.equal(choice('reasoning-mode', 'on').disabled, true);
  assert.match(choice('reasoning-mode', 'on').textContent, /未验证/);
  assert.equal(choice('reasoning-mode', 'off').disabled, true);
  assert.match(choice('reasoning-mode', 'off').textContent, /不支持/);
  assert.equal(choice('response-mode', 'streaming').disabled, true);
  assert.match(choice('response-mode', 'streaming').textContent, /未验证/);
  assert.equal(choice('reasoning-effort', '').disabled, false);
  assert.equal(choice('reasoning-effort', '__unknown__').disabled, true);
  assert.match(page.element('runtime-default-notice').textContent, /未验证.*AUTO.*未验证.*Normal/);

  const supported = {...unknown, capabilities: {...unknown.capabilities,
    streaming: 'supported', source: 'USER_VERIFIED',
    thinking_on: {status: 'supported', source: 'MODEL_METADATA'},
    thinking_off: {status: 'supported', source: 'MODEL_METADATA'},
    reasoning_effort: {status: 'supported', source: 'MODEL_METADATA'},
    thinking_off_streaming_combination:{status:'supported',source:'USER_VERIFIED'}, thinking_streaming_combination: {status: 'supported', source: 'USER_VERIFIED'}, effort_values: ['low', 'high']}};
  vm.runInContext(`updateRuntimeOptionControls(${JSON.stringify(supported)}, {reasoning:'on', response:'streaming', effort:'high'})`, page.context);
  assert.equal(choice('reasoning-mode', 'on').disabled, false);
  assert.equal(choice('reasoning-mode', 'off').disabled, false);
  assert.equal(choice('response-mode', 'streaming').disabled, false);
  assert.equal(choice('reasoning-effort', 'low').disabled, false);
  assert.equal(page.element('reasoning-effort').value, 'high');

  vm.runInContext(`profiles = [${JSON.stringify(supported)}]`, page.context);
  page.element('profile').value = supported.profile_id;
  page.element('reasoning-mode').value = 'auto';
  vm.runInContext('syncRuntimeOptionsFromCurrentSelections()', page.context);
  assert.equal(choice('reasoning-effort', 'low').disabled, true);
  assert.match(choice('reasoning-effort', 'low').textContent, /选择 Thinking ON 后可选/);
  page.element('reasoning-mode').value = 'on';
  vm.runInContext('syncRuntimeOptionsFromCurrentSelections()', page.context);
  assert.equal(choice('reasoning-effort', 'low').disabled, false);
});

test('successful Streaming Probe unlocks the exact Profile choice without reloading the page', async () => {
  const unknown = {profile_id: 'custom-stream', display_name: 'Custom Stream', provider: 'custom',
    service_id: 'custom', model: 'm1', adapter_id: 'openai_chat', base_url: 'https://example.invalid/v1',
    profile_status: 'custom', runtime_type: 'cloud', source: 'user_custom',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN', streaming_scope_matches: true}};
  const verified = {...unknown, capabilities: {streaming: 'supported', source: 'USER_VERIFIED',
    streaming_scope_matches: true}};
  const page = makePage(async (url) => {
    if (url === `/api/profiles/${unknown.profile_id}/probe`) return {ok: true, json: async () => ({
      status: 'success', capability: verified.capabilities, latency_ms: 5})};
    if (url === '/api/config') return {ok: true, json: async () => ({profiles: [verified]})};
    if (url === `/api/profiles/${unknown.profile_id}`) return {ok: true, json: async () => ({editable: true,
      fields: {display_name: unknown.display_name, service_id: 'custom', model_family: 'unknown',
        adapter_id: 'openai_chat', base_url: unknown.base_url, model: 'm1', secret_env: '',
        provider_kind: 'cloud'}})};
    return {ok: true, json: async () => ({status: 'MISSING'})};
  });
  vm.runInContext(`profiles = [${JSON.stringify(unknown)}]`, page.context);
  page.element('profile').value = unknown.profile_id;
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, true);
  await vm.runInContext('probeSelectedCapability()', page.context);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, false);
  assert.match(page.element('streaming-capability').textContent, /本机已验证/);
});

test('successful Thinking Probe independently unlocks the exact ON choice', async () => {
  const base = {profile_id: 'ollama-qwen35-4b-local', display_name: 'Ollama Qwen', provider: 'ollama',
    service_id: 'ollama', model_family: 'qwen', model: 'qwen3.5:4b', adapter_id: 'generic_openai_chat',
    base_url: 'http://127.0.0.1:11434/v1', profile_status: 'experimental', runtime_type: 'local',
    source: 'built_in', thinking_probe_available: true, default_reasoning_mode: 'auto', default_response_mode: 'normal',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN',
      thinking_on: {status: 'unknown', source: 'UNKNOWN'},
      thinking_off: {status: 'unknown', source: 'UNKNOWN'}, reasoning_effort: {status: 'unknown', source: 'UNKNOWN'}}};
  const verified = {...base, capabilities: {...base.capabilities,
    thinking_on: {status: 'supported', source: 'USER_VERIFIED'}}};
  const page = makePage(async (url) => {
    if (url === `/api/profiles/${base.profile_id}/thinking-probe`) return {ok: true, json: async () => ({status: 'success', capability: verified.capabilities})};
    if (url === '/api/config') return {ok: true, json: async () => ({profiles: [verified]})};
    if (url === `/api/profiles/${base.profile_id}`) return {ok: true, json: async () => ({editable: false,
      fields: {display_name: base.display_name, service_id: 'ollama', model_family: 'qwen',
        adapter_id: 'generic_openai_chat', base_url: base.base_url, model: base.model, secret_env: '',
        provider_kind: 'local'}})};
    return {ok: true, json: async () => ({status: 'MISSING'})};
  });
  vm.runInContext(`profiles = [${JSON.stringify(base)}]`, page.context);
  page.element('profile').value = base.profile_id;
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  const onChoice = () => page.element('reasoning-mode').children.find((item) => item.value === 'on');
  const offChoice = () => page.element('reasoning-mode').children.find((item) => item.value === 'off');
  assert.equal(onChoice().disabled, true);
  await vm.runInContext('probeThinking("on")', page.context);
  assert.equal(onChoice().disabled, false);
  assert.equal(offChoice().disabled, true);
});

test('new Custom Profile first Streaming Probe uses the current id and unlocks without page reload', async () => {
  const mock = {profile_id: 'mock-demo', display_name: 'Mock', provider: 'mock', service_id: 'custom',
    model: 'offline-mock', profile_status: 'custom', runtime_type: 'mock', source: 'built_in',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN'}};
  const existing = {profile_id: 'custom-existing', display_name: 'Existing Custom', provider: 'custom',
    service_id: 'school', model: 'school-a', adapter_id: 'openai_chat', base_url: 'http://localhost/a/v1',
    profile_status: 'custom', runtime_type: 'local', source: 'user_custom',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN', streaming_scope_matches: true}};
  const created = {profile_id: 'custom-created', display_name: 'New Custom', provider: 'custom',
    service_id: 'school', model: 'school-b', adapter_id: 'openai_chat', base_url: 'http://localhost/b/v1',
    profile_status: 'custom', runtime_type: 'local', source: 'user_custom',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN', streaming_scope_matches: true}};
  let profileList = [mock, existing];
  const probeCalls = [];
  let page;
  const fieldsFor = (profile) => ({display_name: profile.display_name,
    service_id: profile.service_id, model_family: 'unknown', adapter_id: profile.adapter_id || 'generic_openai_chat',
    base_url: profile.base_url || 'http://mock.invalid/v1', model: profile.model, secret_env: '',
    provider_kind: profile.runtime_type});
  const reply = (body, status = 200) => ({ok: status >= 200 && status < 300, status,
    json: async () => body});
  page = makePage(async (url, options = {}) => {
    if (url === '/api/config') return reply({profiles: profileList,
      presets: [{id: 'custom', label: 'Custom OpenAI-compatible', service_id: 'custom',
        model_family: 'unknown', adapter_id: 'openai_chat', provider_kind: 'local'}], scenarios: ['normal']});
    if (url === '/api/profiles' && options.method === 'POST') {
      profileList = [...profileList, created];
      return reply({profile: {profile_id: created.profile_id}});
    }
    if (/^\/api\/profiles\/[^/]+\/probe$/.test(url)) {
      const profileId = url.split('/')[3];
      assert.equal(page.element('capability-probe-status').textContent, '正在验证 Streaming...');
      assert.equal(page.element('probe-streaming').disabled, true);
      const body = JSON.parse(options.body);
      probeCalls.push({profileId, body});
      const capability = {streaming: 'supported', source: 'USER_VERIFIED',
        streaming_scope_matches: true};
      profileList = profileList.map((profile) => profile.profile_id === profileId
        ? {...profile, capabilities: capability} : profile);
      return reply({status: 'success', capability, latency_ms: 7});
    }
    if (url.startsWith('/api/profiles/')) {
      const profile = profileList.find((item) => url.endsWith(item.profile_id));
      return reply({editable: profile?.source === 'user_custom', fields: fieldsFor(profile || mock)});
    }
    if (url === '/api/secret-status') return reply({status: 'MISSING'});
    throw new Error(`Unexpected offline test URL: ${url}`);
  });

  await vm.runInContext('init()', page.context);
  page.element('access-mode').value = 'managed_custom';
  await page.element('access-mode').dispatch('change');
  await page.element('new-profile').dispatch('click');
  const values = {'provider-preset': 'custom', 'custom-name': 'New Custom',
    'custom-provider': 'school', 'custom-family': 'unknown', 'custom-adapter': 'openai_chat',
    'custom-url': created.base_url, 'custom-model': created.model, 'custom-secret-env': '',
    'custom-deployment': 'local', 'custom-auth': 'OPTIONAL_BEARER', 'custom-default-thinking': 'auto',
    'custom-default-response': 'normal'};
  for (const [id, value] of Object.entries(values)) page.element(id).value = value;
  await page.element('save-profile').dispatch('click');
  await new Promise(setImmediate);
  assert.equal(page.element('profile').value, created.profile_id);
  assert.equal(page.element('probe-streaming').hidden, false);

  await page.element('probe-streaming').dispatch('click');
  assert.deepEqual(probeCalls[0], {profileId: created.profile_id,
    body: {capability: 'streaming', confirm_network: true, reverify: false}});
  assert.equal(page.element('probe-streaming').hidden, true);
  assert.equal(page.element('reprobe-streaming').hidden, false);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, false);
  assert.match(page.element('streaming-capability').textContent, /本机已验证.*SUPPORTED/);

  page.element('profile').value = existing.profile_id;
  await page.element('profile').dispatch('change');
  await new Promise(setImmediate);
  assert.equal(page.element('probe-streaming').hidden, false);
  await page.element('probe-streaming').dispatch('click');
  assert.equal(probeCalls[1].profileId, existing.profile_id);
});

test('explicit Streaming rejection is shown and refreshes the exact Profile as unsupported', async () => {
  const unknown = {profile_id: 'custom-stream-refused', display_name: 'Refused', provider: 'custom',
    service_id: 'custom', model: 'm1', adapter_id: 'openai_chat', base_url: 'http://localhost/v1',
    profile_status: 'custom', runtime_type: 'local', source: 'user_custom',
    capabilities: {streaming: 'unknown', source: 'UNKNOWN', streaming_scope_matches: true}};
  const rejected = {...unknown, capabilities: {streaming: 'unsupported', source: 'USER_VERIFIED',
    streaming_scope_matches: true}};
  const page = makePage(async (url) => {
    if (url.endsWith('/probe')) return {ok: true, status: 200, json: async () => ({status: 'unsupported',
      error_code: 'STREAM_UNSUPPORTED', capability: rejected.capabilities})};
    if (url === '/api/config') return {ok: true, json: async () => ({profiles: [rejected]})};
    return {ok: true, json: async () => ({editable: true, fields: {display_name: rejected.display_name,
      service_id: 'custom', model_family: 'unknown', adapter_id: 'openai_chat',
      base_url: rejected.base_url, model: 'm1', secret_env: '', provider_kind: 'local'}})};
  });
  vm.runInContext(`profiles = [${JSON.stringify(unknown)}]`, page.context);
  page.element('profile').value = unknown.profile_id;
  vm.runInContext('updateProfile()', page.context);
  await new Promise(setImmediate);
  await vm.runInContext('probeSelectedCapability(false)', page.context);
  assert.match(page.element('capability-probe-status').textContent, /STREAM_UNSUPPORTED.*UNSUPPORTED.*USER_VERIFIED/);
  assert.match(page.element('streaming-capability').textContent, /不支持.*UNSUPPORTED/);
  assert.equal(page.element('probe-streaming').hidden, true);
  assert.equal(page.element('reprobe-streaming').hidden, false);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, true);
});

test('Streaming Probe surfaces HTTP, malformed JSON, and network errors', async () => {
  const profile = {profile_id: 'custom-probe-errors', display_name: 'Probe Error', provider: 'custom',
    service_id: 'custom', model: 'm1', profile_status: 'custom', runtime_type: 'local',
    source: 'user_custom', capabilities: {streaming: 'unknown', source: 'UNKNOWN'}};
  const detail = {editable: true, fields: {display_name: profile.display_name, service_id: 'custom',
    model_family: 'unknown', adapter_id: 'generic_openai_chat', base_url: 'http://localhost/v1',
    model: 'm1', secret_env: '', provider_kind: 'local'}};
  async function check(probeReply, expected) {
    const page = makePage(async (url) => {
      if (url.endsWith('/probe')) {
        if (probeReply instanceof Error) throw probeReply;
        return probeReply;
      }
      return {ok: true, json: async () => detail};
    });
    vm.runInContext(`profiles = [${JSON.stringify(profile)}]`, page.context);
    page.element('profile').value = profile.profile_id;
    vm.runInContext('updateProfile()', page.context);
    await new Promise(setImmediate);
    await vm.runInContext('probeSelectedCapability(false)', page.context);
    assert.match(page.element('capability-probe-status').textContent, new RegExp(expected));
    assert.equal(page.element('probe-streaming').disabled, false);
  }
  await check({ok: false, status: 504, json: async () => ({error_code: 'READ_TIMEOUT'})}, 'READ_TIMEOUT');
  await check({ok: false, status: 502, json: async () => { throw new Error('bad JSON'); }}, 'INVALID_RESPONSE');
  await check(new TypeError('offline simulated fetch failure'), 'NETWORK_ERROR');
});


// Three-mode UI uses the unchanged exact backend Profiles / contracts.
function threeModeFixtures() {
  const base={display_name:'Preset Qwen Plus',service_id:'dashscope',model:'qwen-plus',
    adapter_id:'openai_chat',base_url:'https://example.invalid/v1',credential_ref:'TEST_FAKE_KEY',
    auth_spec:'REQUIRED_BEARER',profile_status:'experimental',runtime_type:'cloud',source:'preset',
    access_mode:'preset',preset_id:'qwen-plus',preset_contract_version:'1',default_response_mode:'normal',
    capabilities:{streaming:'supported',source:'USER_VERIFIED',thinking_default:false,
      thinking_on:{status:'supported'},thinking_off:{status:'supported'},
      thinking_off_streaming_combination:{status:'supported'},
      thinking_streaming_combination:{status:'supported'}}};
  const fixed=['off','on','auto'].map(variant=>({...base,profile_id:`preset-qwen-plus-${variant}`,
    preset_variant:variant,default_reasoning_mode:variant,display_name:`Preset Qwen Plus · ${variant}`}));
  return [...fixed,{...base,profile_id:'preset-deepseek-flash-auto',display_name:'Preset DeepSeek Flash · AUTO',
    service_id:'deepseek_api',preset_id:'deepseek-flash',model:'deepseek-flash',preset_variant:'auto',
    default_reasoning_mode:'auto',capabilities:{streaming:'unknown'}},
    {...base,profile_id:'qwen-plus-experimental',display_name:'Legacy Qwen',source:'built_in',access_mode:'managed'},
    {...base,profile_id:'deepseek-v4-flash-experimental',display_name:'Legacy DeepSeek',source:'built_in',access_mode:'managed'},
    {...base,profile_id:'mock-demo',display_name:'Mock',source:'built_in',access_mode:'managed',
      runtime_type:'mock',auth_spec:'NONE',default_reasoning_mode:'auto'},
    {...base,profile_id:'ollama-qwen35-4b-local',display_name:'Ollama Qwen3.5 4B',source:'built_in',access_mode:'managed',
      service_id:'ollama',runtime_type:'local',model:'qwen3.5:4b',auth_spec:'NONE',
      base_url:'http://127.0.0.1:11434/v1',default_reasoning_mode:'off'},
    {...base,profile_id:'user-local',display_name:'My Local',source:'user_custom',access_mode:'managed',
      service_id:'school',model:'local-model',runtime_type:'local',auth_spec:'NONE'}];
}
function threeModePage(extraFetch=null,items=threeModeFixtures()) {
  const calls=[];
  const page=makePage(async(url,options)=>{
    calls.push({url,body:options?.body ? JSON.parse(options.body):null});
    if(extraFetch) {const response=await extraFetch(url,options);if(response)return response;}
    if(url==='/api/config')return r2Reply({profiles:items,presets:[],scenarios:['low_oxygen','normal']});
    if(url.startsWith('/api/profiles/'))return r2Reply({fields:{},editable:url.endsWith('user-local')});
    if(url==='/api/secret-status')return r2Reply({availability:'MISSING',source:'MISSING'});
    if(url==='/api/analyze')return r2Reply({error_code:'OFFLINE_FIXTURE'});
    throw new Error(`Unexpected offline URL: ${url}`);
  });
  return {...page,calls,items};
}

function publicationPage(defaultId='fresh-release', extraFetch=null) {
  const fixed = ['off', 'on'].map(mode => ({profile_id:`preset-fresh-${mode}`,
    display_name:`Fresh Model · ${mode.toUpperCase()}`,source:'preset',access_mode:'preset',
    preset_id:'fresh-release',preset_variant:mode,preset_contract_version:'1.0.0',model:'exact-model',
    runtime_type:'cloud',default_reasoning_mode:mode,default_response_mode:'normal',
    preset_is_default:mode==='off',preset_response_modes:mode==='off'?['normal']:['normal','streaming']}));
  return threeModePage(async(url,options)=>{
    if(url==='/api/config')return r2Reply({profiles:fixed,presets:[],scenarios:['normal'],default_preset_id:defaultId});
    return extraFetch?extraFetch(url,options):null;
  },fixed);
}

function releasedModelsPage() {
  const catalog=JSON.parse(fs.readFileSync(path.join(__dirname,'../src/fishery_ai/resources/profiles/presets.json'),'utf8'));
  const fixed=catalog.templates.flatMap(t=>t.variants.map(v=>({
    profile_id:`preset-${t.id}-${v.id}`,display_name:`${t.display_name} · ${v.label}`,
    source:'preset',access_mode:'preset',preset_id:t.id,preset_variant:v.id,
    preset_contract_version:t.contract_version,model:t.connection.model,runtime_type:t.connection.provider_kind,
    default_reasoning_mode:v.thinking,default_response_mode:'normal',
    preset_is_default:t.defaults.thinking===v.thinking,preset_response_modes:v.response_modes})));
  return threeModePage(async(url)=>url==='/api/config'
    ?r2Reply({profiles:fixed,presets:[],scenarios:['normal'],default_preset_id:catalog.default_preset_id}):null,fixed);
}

test('published three exact models retain Qwen default and exclude the v4 pro candidate',async()=>{
  const page=releasedModelsPage();await vm.runInContext('init()',page.context);
  assert.deepEqual(page.element('profile').children.map(x=>x.textContent),
    ['请选择模型','Qwen 3.8 Flash','DeepSeek Flash','Ollama Qwen3.5 4B']);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'preset-dashscope-qwen38-flash-r1-off');
  assert.equal(vm.runInContext('profiles.some(p=>p.model==="deepseek-v4-pro")',page.context),false);
});

test('published OFF and ON Streaming combinations are visible without research fields',async()=>{
  const page=releasedModelsPage();await vm.runInContext('init()',page.context);
  for(const id of ['dashscope-qwen38-flash-r1','deepseek-flash-r1','ollama-qwen35-4b-r1']){
    page.element('profile').value=`preset-${id}-off`;await page.element('profile').dispatch('change');
    assert.equal(vm.runInContext('selectedProfile().preset_id',page.context),id);
    assert.equal(page.element('preset-response-mode').children.find(x=>x.value==='streaming').disabled,false);
    assert.deepEqual(page.element('preset-variant').children.map(x=>x.textContent),['Thinking OFF','Thinking ON']);
    page.element('preset-variant').value=`preset-${id}-on`;await page.element('preset-variant').dispatch('change');
    assert.equal(page.element('preset-response-mode').children.find(x=>x.value==='streaming').disabled,false);
    page.element('preset-response-mode').value='streaming';await page.element('preset-response-mode').dispatch('change');
    assert.equal(page.element('response-mode').value,'streaming');
    for(const field of ['capability-panel','credential-manager','profile-meta','profile-summary','selected-secret-status'])
      assert.equal(page.element(field).hidden,true,field);
  }
  assert.equal(page.calls.some(x=>x.url.startsWith('/api/profiles/')||x.url==='/api/secret-status'),false);
});

test('published Preset uses developer default and hides every research / connection control',async()=>{
  const page=publicationPage();await vm.runInContext('init()',page.context);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'preset-fresh-off');
  assert.equal(page.element('preset-response-mode').value,'normal');
  for(const id of ['capability-panel','credential-manager','profile-meta','profile-summary','custom-editor',
    'selected-secret-status'])assert.equal(page.element(id).hidden,true,id);
  assert.equal(page.calls.some(x=>x.url.startsWith('/api/profiles/')||x.url==='/api/secret-status'),false);
  assert.deepEqual(page.element('preset-variant').children.map(x=>x.textContent),['Thinking OFF','Thinking ON']);
});

test('published Preset without developer default requires explicit selection',async()=>{
  const page=publicationPage(null);await vm.runInContext('init()',page.context);
  assert.equal(page.element('profile').value,'');
  assert.equal(page.element('analyze').disabled,true);
  assert.equal(page.element('profile').children[0].textContent,'请选择模型');
  page.element('profile').value='preset-fresh-off';await page.element('profile').dispatch('change');
  assert.equal(page.element('analyze').disabled,false);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'preset-fresh-off');
});

test('published Preset combinations control Response Mode independently of Thinking',async()=>{
  const page=publicationPage();await vm.runInContext('init()',page.context);
  const streaming=()=>page.element('preset-response-mode').children.find(x=>x.value==='streaming');
  assert.equal(streaming().disabled,true);assert.match(streaming().textContent,/此 Preset 未提供该模式/);
  page.element('preset-variant').value='preset-fresh-on';await page.element('preset-variant').dispatch('change');
  assert.equal(streaming().disabled,false);assert.equal(page.element('preset-response-mode').value,'normal');
  page.element('preset-response-mode').value='streaming';await page.element('preset-response-mode').dispatch('change');
  assert.equal(page.element('response-mode').value,'streaming');
  page.element('preset-variant').value='preset-fresh-off';await page.element('preset-variant').dispatch('change');
  assert.equal(page.element('response-mode').value,'normal');assert.equal(streaming().disabled,true);
});

test('published Preset sends selected fixed variant through existing analysis endpoint',async()=>{
  const page=publicationPage();await vm.runInContext('(async()=>{await init();credentialCsrf="fictional-csrf";})()',page.context);
  page.element('confirm-network').checked=true;page.element('question').value='OK';page.element('scenario').value='normal';
  await vm.runInContext('analyze()',page.context);
  const sent=page.calls.find(x=>x.url==='/api/analyze');
  assert.equal(sent.body.profile_id,'preset-fresh-off');assert.equal(sent.body.reasoning_mode,'off');
  assert.equal(Object.hasOwn(sent.body,'base_url'),false);assert.equal(Object.hasOwn(sent.body,'credential_ref'),false);
});

test('Manual V1 reads Preset connection only in its developer view without enriching catalog',async()=>{
  const page=publicationPage('fresh-release',async(url)=>url.startsWith('/api/profiles/')
    ?r2Reply({fields:{service_id:'dashscope',base_url:'https://example.invalid/v1',model:'exact-model',
        secret_env:'TEST_FAKE_KEY',auth_spec:'REQUIRED_BEARER'}}):null);
  await vm.runInContext('init()',page.context);
  await vm.runInContext('setAccessMode("manual_expert")',page.context);
  await new Promise(setImmediate);
  assert.match(page.element('manual-connection').children.map(x=>x.textContent).join(' '),/TEST_FAKE_KEY/);
  assert.equal(vm.runInContext('profiles.some(p=>p.base_url || p.credential_ref || p.capabilities)',page.context),false);
  assert.equal(JSON.parse(page.element('manual-body').value).model,'exact-model');
});

test('three-mode initial UI shows Qwen once, DeepSeek once, and hides legacy Built-in choices',async()=>{
  const page=threeModePage();
  await vm.runInContext('init()',page.context);
  const choices=page.element('profile').children;
  assert.deepEqual(choices.map(x=>x.textContent),['Qwen Plus','DeepSeek Flash']);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'preset-qwen-plus-auto');
  for(const id of ['qwen-plus-experimental','deepseek-v4-flash-experimental','mock-demo','ollama-qwen35-4b-local'])
    assert.equal(choices.some(x=>x.value===id),false);
  assert.doesNotMatch(source,/label = "Built-in Profiles"/);
  assert.equal(vm.runInContext('profiles.length',page.context),9); // Internal compatibility definitions stay intact.
});

test('three-mode Qwen Variant sends the exact existing id and fixed thinking while response is independent',async()=>{
  const page=threeModePage();await vm.runInContext('(async()=>{await init();credentialCsrf="fictional-csrf";})()',page.context);
  assert.deepEqual(page.element('preset-variant').children.map(x=>x.value),[
    'preset-qwen-plus-off','preset-qwen-plus-on','preset-qwen-plus-auto']);
  for(const variant of ['off','on','auto']) {
    page.element('preset-variant').value=`preset-qwen-plus-${variant}`;
    await page.element('preset-variant').dispatch('change');
    page.element('confirm-network').checked=true;
    page.element('response-mode').value='normal';
    await page.element('analyze').dispatch('click');
    const body=page.calls.filter(x=>x.url==='/api/analyze').at(-1).body;
    assert.equal(body.profile_id,`preset-qwen-plus-${variant}`);
    assert.equal(body.reasoning_mode,variant==='auto'?undefined:variant);
    assert.equal(vm.runInContext('selectedProfile().preset_variant',page.context),variant);
    assert.equal(page.element('reasoning-mode').disabled,true);
    assert.equal(page.element('response-mode').children.find(x=>x.value==='streaming').disabled,false);
  }
});

test('three-mode DeepSeek exposes only AUTO readonly variant and Normal',async()=>{
  const page=threeModePage();await vm.runInContext('init()',page.context);
  page.element('profile').value='preset-deepseek-flash-auto';await page.element('profile').dispatch('change');
  assert.deepEqual(page.element('preset-variant').children.map(x=>x.value),['preset-deepseek-flash-auto']);
  assert.equal(page.element('preset-variant').disabled,true);
  assert.equal(page.element('response-mode').value,'normal');
  assert.equal(page.element('response-mode').children.find(x=>x.value==='streaming').disabled,true);
});

test('three-mode Preset has no CRUD entry and New cannot create a Preset',async()=>{
  const page=threeModePage();await vm.runInContext('init()',page.context);
  for(const id of ['custom-editor','new-profile','edit-profile','delete-profile','managed-thinking-field'])
    assert.equal(page.element(id).hidden,true,id);
  await page.element('new-profile').dispatch('click');
  assert.equal(vm.runInContext('formMode',page.context),'view');
  assert.equal(page.element('preset-variant-field').hidden,false);
});

test('three-mode Managed Custom owns CRUD and New remains a clean editable form',async()=>{
  const page=threeModePage();await vm.runInContext('init()',page.context);
  page.element('access-mode').value='managed_custom';await page.element('access-mode').dispatch('change');
  await new Promise(setImmediate);
  assert.deepEqual(page.element('profile').children.map(x=>x.value),['user-local']);
  for(const id of ['custom-editor','new-profile','edit-profile','delete-profile'])assert.equal(page.element(id).hidden,false,id);
  await page.element('edit-profile').dispatch('click');assert.equal(vm.runInContext('formMode',page.context),'edit');
  assert.equal(page.element('custom-name').readOnly,true);
  await page.element('new-profile').dispatch('click');assert.equal(vm.runInContext('formMode',page.context),'new');
  for(const id of ['custom-name','custom-model','custom-url','custom-provider','provider-preset'])assert.equal(page.element(id).value,'');
});

test('three-mode empty Custom list cannot accidentally analyze a legacy or Preset connection',async()=>{
  const page=threeModePage(null,threeModeFixtures().filter(x=>x.source!=='user_custom'));
  await vm.runInContext('(async()=>{await init();setAccessMode("managed_custom");})()',page.context);
  assert.equal(vm.runInContext('selectedProfile()',page.context),undefined);
  assert.equal(page.element('analyze').disabled,true);
  assert.equal(page.element('new-profile').hidden,false);
  await page.element('new-profile').dispatch('click');assert.equal(vm.runInContext('formMode',page.context),'new');
});

test('three-mode Mock and unpublished Ollama live only in explicit development selection',async()=>{
  const page=threeModePage();await vm.runInContext('init()',page.context);
  assert.deepEqual(page.element('development-target').children.map(x=>x.value),['mock-demo','ollama-qwen35-4b-local']);
  page.element('development-target').value='mock-demo';await page.element('use-development').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'development');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'mock-demo');
  assert.match(page.element('mode-note').textContent,/Development.*未发布/);
  assert.equal(page.element('custom-editor').hidden,true);
  assert.equal(page.element('real-warning').hidden,true);
  assert.equal(page.element('profile').children.some(x=>/Legacy/.test(x.textContent)),false);
});

test('three-mode Manual is an independent panel and hides every managed / business control',async()=>{
  const page=threeModePage();await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");})()',page.context);
  assert.equal(page.element('manual-expert').hidden,false);
  for(const id of ['custom-editor','credential-manager','capability-panel','analysis-inputs',
    'analyze','results','empty-state','preset-variant-field','development-workspace','tool-conversation-panel'])assert.equal(page.element(id).hidden,true,id);
  assert.equal(page.element('development-entry').hidden,false);
  assert.equal(page.element('use-development').hidden,false);
  const choices=page.element('profile').children;
  assert.equal(choices.filter(x=>x.textContent==='Qwen Plus').length,1);
  assert.equal(choices.some(x=>/Legacy|Mock|Manual Expert/.test(x.textContent)),false);
  assert.equal(page.calls.some(x=>/probe|metadata|credential/.test(x.url)),false);
  assert.match(html,/<section id="manual-expert"/);
});

test('three-mode Manual raw draft survives mode changes and changes only when target changes',async()=>{
  const page=threeModePage();await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");})()',page.context);
  const draft='{"model":"qwen-plus","messages":[],"stream":true,"custom_field":17}';
  page.element('manual-body').value=draft;
  await vm.runInContext('setAccessMode("preset");setAccessMode("manual_expert")',page.context);
  assert.equal(page.element('manual-body').value,draft);
  page.element('profile').value='user-local';await page.element('profile').dispatch('change');
  assert.equal(JSON.parse(page.element('manual-body').value).model,'local-model');
  assert.equal(page.element('results').hidden,true);
});

test('three-mode Manual Send preserves raw JSON and tool_calls are displayed without managed API calls',async()=>{
  const page=threeModePage(async(url)=>url==='/api/manual'?r2Reply({response:{choices:[{message:{tool_calls:[{id:'offline-tool'}]}}]},
    usage:{total_tokens:3},total_latency_ms:4}):null);
  await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");credentialCsrf="fictional-csrf";})()',page.context);
  const raw={model:'qwen-plus',messages:[{role:'user',content:'offline'}],stream:false,custom_field:17};
  page.element('manual-body').value=JSON.stringify(raw);await page.element('manual-send').dispatch('click');
  const submission=page.calls.find(x=>x.url==='/api/manual').body;
  assert.deepEqual(submission.body,raw);
  for(const key of ['reasoning_mode','reasoning_effort','scenario','question'])assert.equal(Object.hasOwn(submission,key),false);
  assert.match(page.element('manual-output').textContent,/offline-tool/);
  assert.equal(page.calls.some(x=>/analyze|probe|tools/.test(x.url)),false);
  assert.equal(page.element('results').hidden,true);
});

test('three-mode Manual Streaming renders raw deltas and final raw usage without managed injection',async()=>{
  const page=threeModePage(async(url)=>url==='/api/manual'?sseResponse([
    ['raw_delta',{choices:[{delta:{content:'offline'}}],usage:{total_tokens:2}}],
    ['completed',{total_latency_ms:5}]]):null);
  await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");credentialCsrf="fictional-csrf";})()',page.context);
  const raw={model:'qwen-plus',messages:[],stream:true};page.element('manual-body').value=JSON.stringify(raw);
  await page.element('manual-send').dispatch('click');
  assert.deepEqual(page.calls.find(x=>x.url==='/api/manual').body.body,raw);
  assert.match(page.element('manual-output').textContent,/offline.*[\s\S]*total_tokens/);
  assert.match(page.element('manual-status').textContent,/Manual 完成/);
  assert.equal(page.element('response-mode').value,'normal'); // Hidden managed preference has no effect.
});

test('three-mode Stop locks mode, model, variant and target then uses the existing cancellation route',async()=>{
  const page=threeModePage(async(url)=>url.endsWith('/cancel')?r2Reply({state:'CANCELLED',backend_io_closed:true}):null);
  await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");credentialCsrf="fictional-csrf";await beginExecution();})()',page.context);
  for(const id of ['profile','access-mode','preset-variant','use-development','development-target'])assert.equal(page.element(id).disabled,true,id);
  await vm.runInContext('setAccessMode("preset")',page.context);
  assert.equal(vm.runInContext('accessMode',page.context),'manual_expert');
  await page.element('stop-generation').dispatch('click');
  assert.match(page.element('manual-status').textContent,/USER_CANCELLED.*后端 I\/O 已关闭.*UNKNOWN/);
  assert.equal(page.element('access-mode').disabled,false);
  assert.equal(page.calls.some(x=>x.url.endsWith('/cancel')),true);
});


test('three-mode Preset Thinking switch retains a separately chosen supported response mode',async()=>{
  const page=threeModePage();await vm.runInContext('init()',page.context);
  page.element('response-mode').value='streaming';
  page.element('preset-variant').value='preset-qwen-plus-on';await page.element('preset-variant').dispatch('change');
  assert.equal(page.element('reasoning-mode').value,'on');
  assert.equal(page.element('response-mode').value,'streaming');
  page.element('preset-variant').value='preset-qwen-plus-off';await page.element('preset-variant').dispatch('change');
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(page.element('response-mode').value,'streaming');
});

test('three-mode Manual preserves saved Custom targets even when they share a Preset endpoint and model',async()=>{
  const items=threeModeFixtures();items.push({...items[0],profile_id:'custom-same-endpoint',
    display_name:'My timeout choice',source:'user_custom',access_mode:'managed'});
  const page=threeModePage(null,items);await vm.runInContext('(async()=>{await init();setAccessMode("manual_expert");})()',page.context);
  assert.equal(page.element('profile').children.some(x=>x.value==='custom-same-endpoint'),true);
  page.element('profile').value='user-local';await page.element('profile').dispatch('change');
  const draft='{"model":"local-model","messages":[]}';page.element('manual-body').value=draft;
  await vm.runInContext('setAccessMode("preset");setAccessMode("manual_expert")',page.context);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'user-local');
  assert.equal(page.element('manual-body').value,draft);
});

test('three-mode Managed Custom Normal and Streaming use the unchanged shared analysis endpoints',async()=>{
  const page=threeModePage(async(url)=>url==='/api/analyze/stream'?sseResponse([
    ['failed',{error_code:'OFFLINE_FIXTURE'}]]):null);
  await vm.runInContext('(async()=>{await init();setAccessMode("managed_custom");credentialCsrf="fictional-csrf";})()',page.context);
  for(const mode of ['normal','streaming']) {
    page.element('response-mode').value=mode;page.element('confirm-network').checked=true;
    await page.element('analyze').dispatch('click');
    const call=page.calls.filter(x=>x.url.startsWith('/api/analyze')).at(-1);
    assert.equal(call.url,mode==='normal'?'/api/analyze':'/api/analyze/stream');
    assert.equal(call.body.profile_id,'user-local');
    assert.equal(call.body.scenario,'low_oxygen');
    assert.equal(call.body.reasoning_mode,undefined);
  }
});


test('clean-room empty Preset, Managed and Manual views stay safe and allow a clean new draft',async()=>{
  const mock={profile_id:'mock-demo',display_name:'Mock',runtime_type:'mock',source:'built_in',
    auth_spec:'NONE',model:'offline-mock',capabilities:{streaming:'supported'}};
  const page=threeModePage(null,[mock]);await vm.runInContext('init()',page.context);
  assert.equal(page.element('analyze').disabled,true);
  assert.match(page.element('status').textContent,/暂无已发布 Preset/);
  await vm.runInContext('setAccessMode("managed_custom")',page.context);
  assert.match(page.element('status').textContent,/尚无自定义连接/);
  assert.equal(page.element('new-profile').disabled,false);
  await page.element('new-profile').dispatch('click');
  assert.equal(page.element('custom-editor').open,true);
  for(const id of ['custom-name','custom-url','custom-model','custom-secret-env'])
    assert.equal(page.element(id).value,'');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,true);
  await vm.runInContext('setAccessMode("manual_expert")',page.context);
  assert.equal(page.element('manual-send').disabled,true);
  assert.match(page.element('manual-status').textContent,/暂无可用连接/);
  assert.equal(page.calls.some(x=>/credential|analyze|probe|manual\//.test(x.url)),false);
});

test('clean-room empty model catalogs retain the offline Mock development path',async()=>{
  const mock={profile_id:'mock-demo',display_name:'Mock',runtime_type:'mock',source:'built_in',
    auth_spec:'NONE',model:'offline-mock',profile_status:'custom',capabilities:{streaming:'supported'}};
  const page=threeModePage(null,[mock]);await vm.runInContext('init()',page.context);
  await page.element('use-development').dispatch('click');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'mock-demo');
  assert.equal(page.element('analyze').disabled,false);
  assert.equal(page.calls.some(x=>/analyze|probe|manual\//.test(x.url)),false);
});


function preferenceEditPage(initialSupported=true, extraFetch=null) {
  const caps=initialSupported ? {streaming:'supported',source:'USER_VERIFIED',
    streaming_evidence:{status:'supported',source:'USER_VERIFIED'},
    thinking_on:{status:'supported',source:'USER_VERIFIED'},thinking_off:{status:'supported',source:'USER_VERIFIED'},
    thinking_off_streaming_combination:{status:'supported',source:'USER_VERIFIED'},
    thinking_streaming_combination:{status:'supported',source:'USER_VERIFIED'}} :
    {streaming:'unknown',thinking_on:{status:'unknown'},thinking_off:{status:'unknown'}};
  let persisted={profile_id:'custom-edit',display_name:'Edit fixture',source:'user_custom',profile_status:'custom',
    service_id:'dashscope',adapter_id:'openai_chat',base_url:'http://localhost:8111/v1',model:'exact-a',runtime_type:'local',
    auth_spec:'NONE',thinking_probe_available:true,stored_default_thinking_mode:initialSupported?'off':'auto',
    stored_default_response_mode:initialSupported?'streaming':'normal',capabilities:caps};
  let fields={display_name:persisted.display_name,service_id:persisted.service_id,model_family:'unknown',adapter_id:persisted.adapter_id,
    base_url:persisted.base_url,model:persisted.model,secret_env:'',provider_kind:'local',auth_spec:'NONE',
    default_thinking_mode:persisted.stored_default_thinking_mode,default_response_mode:persisted.stored_default_response_mode};
  const calls=[];
  const page=makePage(async(url,options={})=>{
    const body=options.body ? JSON.parse(options.body) : null;
    calls.push({url,method:options.method||'GET',body});
    if(extraFetch) { const response=await extraFetch(url,options); if(response) return response; }
    if(url==='/api/config')return r2Reply({profiles:[persisted],presets:[],scenarios:['normal']});
    if(url.endsWith('/thinking-probe')||url.endsWith('/probe')) {
      const key=body.mode ? `thinking_${body.mode}` : 'streaming';
      const updated={...persisted.capabilities,[key]:body.mode ? {status:'supported',source:'USER_VERIFIED'}:'supported'};
      if(!body.mode){updated.source='USER_VERIFIED';updated.streaming_evidence={status:'supported',source:'USER_VERIFIED'};}
      persisted={...persisted,capabilities:updated};
      return r2Reply({status:'success',capability:updated});
    }
    if(url==='/api/profiles/custom-edit'&&options.method==='PUT') {
      fields={...body};delete fields.test_id;
      persisted={...persisted,model:fields.model,base_url:fields.base_url,service_id:fields.service_id,adapter_id:fields.adapter_id,
        stored_default_thinking_mode:fields.default_thinking_mode,stored_default_response_mode:fields.default_response_mode,
        capabilities:{streaming:'unknown',thinking_on:{status:'unknown'},thinking_off:{status:'unknown'}}};
      return r2Reply({profile:persisted});
    }
    if(url==='/api/profiles/custom-edit')return r2Reply({profile:persisted,fields,editable:true});
    throw new Error(`Unexpected offline route ${url}`);
  });
  return {...page,calls,persisted:()=>persisted,fields:()=>fields};
}

async function startPreferenceEdit(page) {
  await vm.runInContext('init();',page.context);
  await vm.runInContext('setAccessMode("managed_custom");',page.context);
  await new Promise(setImmediate);
  await page.element('edit-profile').dispatch('click');
}

test('Default Response gate locks UNKNOWN UNSUPPORTED and CONFLICT while retaining a historical preference',()=>{
  const page=makePage(async()=>{throw new Error('offline');});
  for(const item of [{status:'unknown'},{status:'unsupported'},{status:'unknown',resolution:'EVIDENCE_CONFLICT'}]) {
    vm.runInContext(`formMode='edit';updateDefaultPreferenceControls({stored_default_response_mode:'streaming',capabilities:{streaming_evidence:${JSON.stringify(item)}}},'auto','streaming')`,page.context);
    const options=page.element('custom-default-response').children;
    assert.equal(options.find(x=>x.value==='normal').disabled,false);
    assert.equal(options.find(x=>x.value==='streaming').disabled,true);
    assert.match(options.find(x=>x.value==='streaming').textContent,item.resolution?/证据冲突/:item.status==='unsupported'?/不支持/:/先执行 Streaming Probe/);
    assert.equal(page.element('custom-default-response').value,'streaming');
    assert.match(page.element('runtime-default-summary').textContent,/响应已保存偏好：streaming.*安全响应：normal/);
  }
});

test('Thinking ON and OFF Probe refresh resolved panel and default gate together without discarding the edit',async()=>{
  const page=preferenceEditPage(false);await startPreferenceEdit(page);
  for(const mode of ['on','off']) {
    assert.equal(page.element('custom-default-thinking').children.find(x=>x.value===mode).disabled,true);
    await vm.runInContext(`probeThinking('${mode}')`,page.context);
    assert.equal(page.element('custom-default-thinking').children.find(x=>x.value===mode).disabled,false);
    assert.equal(page.element('reasoning-mode').children.find(x=>x.value===mode).disabled,false);
    assert.equal(vm.runInContext('formMode',page.context),'edit');
  }
});

test('Streaming Probe refresh unlocks Default Response immediately and preserves its draft preference',async()=>{
  const page=preferenceEditPage(false);await startPreferenceEdit(page);
  assert.equal(page.element('custom-default-response').children.find(x=>x.value==='streaming').disabled,true);
  await vm.runInContext('probeSelectedCapability()',page.context);
  assert.equal(page.element('custom-default-response').children.find(x=>x.value==='streaming').disabled,false);
  assert.equal(page.element('response-mode').children.find(x=>x.value==='streaming').disabled,false);
  assert.equal(page.element('custom-default-response').value,'normal');
  assert.equal(page.element('cancel-edit').hidden,false);
});

test('enter Edit and changing Draft Identity leave persisted profile capability and runtime unchanged',async()=>{
  const page=preferenceEditPage();await vm.runInContext('init()',page.context);
  await vm.runInContext('setAccessMode("managed_custom")',page.context);await new Promise(setImmediate);
  const before=vm.runInContext('JSON.stringify(selectedProfile())',page.context);
  const capabilityText=page.element('streaming-capability').textContent;
  await page.element('edit-profile').dispatch('click');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='off').disabled,false);
  page.element('custom-model').value='exact-b';await page.element('custom-model').dispatch('input');
  assert.equal(vm.runInContext('JSON.stringify(selectedProfile())',page.context),before);
  assert.equal(page.element('streaming-capability').textContent,capabilityText);
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(page.element('response-mode').value,'streaming');
  assert.equal(page.element('custom-default-thinking').value,'off');
  assert.equal(page.element('custom-default-response').value,'streaming');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='off').disabled,true);
  assert.match(page.element('draft-identity-notice').textContent,/保存后将重新解析能力/);
  assert.equal(page.calls.some(x=>x.method==='PUT'),false);
});

test('Cancel Edit restores all persisted fields without a request Resolve write or runtime change',async()=>{
  const page=preferenceEditPage();await startPreferenceEdit(page);
  page.element('custom-model').value='discard-model';page.element('custom-url').value='http://localhost:9999/v1';
  await page.element('custom-model').dispatch('input');
  const count=page.calls.length;
  await page.element('cancel-edit').dispatch('click');
  assert.equal(page.calls.length,count);
  const restored=JSON.parse(vm.runInContext('JSON.stringify(collectFields())',page.context));
  assert.deepEqual(restored,page.fields());
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(page.element('response-mode').value,'streaming');
  assert.equal(page.element('custom-model').disabled,true);
  assert.equal(page.element('cancel-edit').hidden,true);
  assert.equal(page.element('edit-profile').hidden,false);
});

test('saving changed Identity alone replaces runtime capability and safely falls back while keeping stored preferences',async()=>{
  const page=preferenceEditPage();await startPreferenceEdit(page);
  page.element('custom-model').value='exact-b';await page.element('custom-model').dispatch('input');
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'exact-a');
  await page.element('save-profile').dispatch('click');
  assert.equal(page.calls.filter(x=>x.method==='PUT').length,1);
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'exact-b');
  assert.equal(vm.runInContext('selectedProfile().capabilities.streaming',page.context),'unknown');
  assert.equal(page.element('reasoning-mode').value,'auto');
  assert.equal(page.element('response-mode').value,'normal');
  assert.equal(page.element('custom-default-thinking').value,'off');
  assert.equal(page.element('custom-default-response').value,'streaming');
  assert.equal(page.fields().default_thinking_mode,'off');
  assert.equal(page.fields().default_response_mode,'streaming');
});

test('normalized trailing slash and host case in Edit do not discard the current exact capability',async()=>{
  const page=preferenceEditPage();await startPreferenceEdit(page);
  page.element('custom-url').value='HTTP://LOCALHOST:8111/v1///';await page.element('custom-url').dispatch('input');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='off').disabled,false);
  assert.equal(page.element('custom-default-response').children.find(x=>x.value==='streaming').disabled,false);
  assert.doesNotMatch(page.element('draft-identity-notice').textContent,/模型身份已修改/);
});


test('Probe refresh preserves changed draft identity without granting it the selected model capability',async()=>{
  const page=preferenceEditPage(false);await startPreferenceEdit(page);
  page.element('custom-model').value='draft-unverified';await page.element('custom-model').dispatch('input');
  await vm.runInContext('probeThinking("on")',page.context);
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'exact-a');
  assert.equal(vm.runInContext('selectedProfile().capabilities.thinking_on.status',page.context),'supported');
  assert.equal(page.element('custom-model').value,'draft-unverified');
  assert.equal(page.element('custom-default-thinking').children.find(x=>x.value==='on').disabled,true);
  assert.equal(page.element('reasoning-mode').value,'auto');
  assert.equal(page.calls.some(x=>x.method==='PUT'),false);
});

test('Cancel Edit during a pending capability refresh cannot resurrect the discarded draft',async()=>{
  let hold=false,release;
  const page=preferenceEditPage(true,async(url)=>{
    if(hold&&url==='/api/config')return new Promise(done=>{release=done;});
  });
  await startPreferenceEdit(page);
  page.element('custom-model').value='discard-pending';await page.element('custom-model').dispatch('input');
  hold=true;
  const pending=vm.runInContext('refreshProfiles("custom-edit",{preserveDraft:true})',page.context);
  await new Promise(setImmediate);
  await page.element('cancel-edit').dispatch('click');
  release(r2Reply({profiles:[page.persisted()]}));
  await pending;
  assert.equal(vm.runInContext('formMode',page.context),'view');
  assert.equal(page.element('custom-model').value,'exact-a');
  assert.equal(page.element('cancel-edit').hidden,true);
  assert.equal(page.calls.some(x=>x.method==='PUT'),false);
});


test('Profile submit stays below connection testing and View Edit Create actions never conflict',async()=>{
  const actions=html.match(/<div class="manager-actions">([\s\S]*?)<\/div>/)[1];
  assert.doesNotMatch(actions,/id="save-profile"/);
  assert.ok(html.indexOf('id="test-status"')<html.indexOf('id="save-profile"'));
  assert.ok(html.indexOf('id="save-profile"')<html.indexOf('id="custom-status"'));
  const page=preferenceEditPage();await vm.runInContext('init()',page.context);
  await vm.runInContext('setAccessMode("managed_custom")',page.context);await new Promise(setImmediate);
  assert.equal(page.element('edit-profile').hidden,false);
  for(const id of ['cancel-edit','exit-new','save-profile'])assert.equal(page.element(id).hidden,true,id);
  await page.element('edit-profile').dispatch('click');
  assert.equal(page.element('edit-profile').hidden,true);
  assert.equal(page.element('cancel-edit').hidden,false);
  assert.equal(page.element('exit-new').hidden,true);
  assert.equal(page.element('save-profile').textContent,'保存修改');
  await page.element('new-profile').dispatch('click');
  assert.equal(page.element('edit-profile').hidden,true);
  assert.equal(page.element('cancel-edit').hidden,true);
  assert.equal(page.element('exit-new').hidden,false);
  assert.equal(page.element('save-profile').textContent,'创建 Profile');
});

test('Exit Create discards its fields and restores the previous View and selected runtime without writing',async()=>{
  const page=preferenceEditPage();await vm.runInContext('init()',page.context);
  await vm.runInContext('setAccessMode("managed_custom")',page.context);await new Promise(setImmediate);
  page.element('reasoning-mode').value='on';page.element('response-mode').value='normal';
  page.element('advanced-settings').open=true;
  const before=vm.runInContext('JSON.stringify(selectedProfile())',page.context);
  await page.element('new-profile').dispatch('click');
  page.element('custom-name').value='Never saved';page.element('custom-model').value='discard-create';
  await page.element('exit-new').dispatch('click');
  assert.equal(vm.runInContext('formMode',page.context),'view');
  assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(collectFields())',page.context)),page.fields());
  assert.equal(vm.runInContext('JSON.stringify(selectedProfile())',page.context),before);
  assert.equal(page.element('reasoning-mode').value,'on');assert.equal(page.element('response-mode').value,'normal');
  assert.equal(page.element('advanced-settings').open,true);
  assert.equal(page.element('exit-new').hidden,true);assert.equal(page.element('edit-profile').hidden,false);
  assert.equal(page.calls.some(x=>x.method!=='GET'),false);
});

test('Exit Create restores an earlier Edit draft and cancellation still restores the saved Profile',async()=>{
  const page=preferenceEditPage();await startPreferenceEdit(page);
  page.element('custom-model').value='earlier-edit';await page.element('custom-model').dispatch('input');
  await page.element('new-profile').dispatch('click');page.element('custom-model').value='discard-create';
  await page.element('exit-new').dispatch('click');
  assert.equal(vm.runInContext('formMode',page.context),'edit');
  assert.equal(page.element('custom-model').value,'earlier-edit');
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'exact-a');
  assert.equal(page.element('cancel-edit').hidden,false);assert.equal(page.element('exit-new').hidden,true);
  assert.equal(page.element('reasoning-mode').value,'off');assert.equal(page.element('response-mode').value,'streaming');
  await page.element('cancel-edit').dispatch('click');
  assert.equal(page.element('custom-model').value,'exact-a');
  assert.equal(page.calls.some(x=>x.method!=='GET'),false);
});

test('Exit Create from clean-room empty state remains safe and does not fetch a missing Profile',async()=>{
  const mock={profile_id:'mock-demo',display_name:'Mock',runtime_type:'mock',source:'built_in',
    auth_spec:'NONE',model:'offline-mock',capabilities:{streaming:'supported'}};
  const page=threeModePage(null,[mock]);await vm.runInContext('init()',page.context);
  await vm.runInContext('setAccessMode("managed_custom")',page.context);
  await page.element('new-profile').dispatch('click');page.element('custom-model').value='discard-empty';
  const count=page.calls.length;
  await page.element('exit-new').dispatch('click');
  assert.equal(page.calls.length,count);
  assert.equal(vm.runInContext('formMode',page.context),'view');
  assert.equal(page.element('custom-model').value,'');
  assert.equal(page.element('exit-new').hidden,true);assert.equal(page.element('edit-profile').hidden,true);
  assert.equal(page.element('save-profile').hidden,true);assert.equal(page.element('analyze').disabled,true);
});


test('OFF Streaming remains locked despite supported independent capabilities until exact combination evidence',()=>{
  const page=makePage(async()=>null);
  const caps={streaming:'supported',thinking_off:{status:'supported'},thinking_on:{status:'supported'},
    thinking_streaming_combination:{status:'supported'},thinking_off_streaming_combination:{status:'unknown'}};
  vm.runInContext(`updateRuntimeOptionControls({capabilities:${JSON.stringify(caps)}},{reasoning:'off',response:'streaming'})`,page.context);
  assert.equal(page.element('response-mode').children.find(o=>o.value==='streaming').disabled,true);
  assert.equal(page.element('response-mode').value,'normal');
  for(const status of ['supported','unsupported','unknown']) {
    caps.thinking_off_streaming_combination={status};
    vm.runInContext(`updateRuntimeOptionControls({capabilities:${JSON.stringify(caps)}},{reasoning:'off',response:'streaming'})`,page.context);
    assert.equal(page.element('response-mode').children.find(o=>o.value==='streaming').disabled,status!=='supported');
  }
});

test('OFF combination explicit Probe posts current Profile then refreshes both capability and runtime controls',async()=>{
  const before={profile_id:'custom-off-combo',source:'user_custom',runtime_type:'local',profile_status:'custom',
    thinking_probe_available:true,stored_default_thinking_mode:'off',stored_default_response_mode:'streaming',
    capabilities:{streaming:'supported',thinking_off:{status:'supported'},thinking_on:{status:'supported'},
      thinking_streaming_combination:{status:'unknown'},thinking_off_streaming_combination:{status:'unknown'}}};
  const after={...before,capabilities:{...before.capabilities,
    thinking_off_streaming_combination:{status:'supported',source:'USER_VERIFIED'}}};
  const page=makePage(async(url,options)=>{
    if(url.endsWith('/probe')) {
      assert.equal(url,'/api/profiles/custom-off-combo/probe');
      assert.equal(JSON.parse(options.body).capability,'thinking_off_streaming_combination');
      return r2Reply({status:'success',delta_count:1,finish_reason:'stop',capability:after.capabilities});
    }
    if(url==='/api/config')return r2Reply({profiles:[after],scenarios:['normal'],presets:[]});
    return r2Reply({fields:{},editable:true});
  });
  vm.runInContext(`profiles=[${JSON.stringify(before)}];presets=[];renderProfiles('custom-off-combo')`,page.context);
  assert.equal(page.element('probe-combination-off').hidden,false);
  await vm.runInContext('runExplicitProbe("thinking_off_streaming_combination")',page.context);
  assert.equal(page.element('probe-combination-off').hidden,true);
  assert.equal(page.element('reprobe-combination-off').hidden,false);
  assert.equal(page.element('response-mode').children.find(o=>o.value==='streaming').disabled,false);
  assert.match(page.element('thinking-probe-status').textContent,/验证成功/);
});

test('OFF combination network error is visible and leaves options locked without refreshing evidence',async()=>{
  const profile={profile_id:'custom-off-error',source:'user_custom',runtime_type:'cloud',thinking_probe_available:true,
    capabilities:{streaming:'supported',thinking_off:{status:'supported'},thinking_off_streaming_combination:{status:'unknown'}}};
  const page=makePage(async()=>r2Reply({status:'failure',error_code:'CONNECT_TIMEOUT'},false,502));
  vm.runInContext(`profiles=[${JSON.stringify(profile)}];presets=[]`,page.context);page.element('profile').value=profile.profile_id;
  await vm.runInContext('runExplicitProbe("thinking_off_streaming_combination")',page.context);
  assert.match(page.element('thinking-probe-status').textContent,/CONNECT_TIMEOUT/);
  assert.equal(vm.runInContext('selectedProfile().capabilities.thinking_off_streaming_combination.status',page.context),'unknown');
});

test('OFF combination default preference follows resolved conflict and latest successful evidence',()=>{
  const page=makePage(async()=>null);
  for (const [status,resolution] of [['unknown','NO_EVIDENCE'],['unknown','EVIDENCE_CONFLICT'],['unsupported','EVIDENCE_AGREEMENT'],['supported','EVIDENCE_AGREEMENT']]) {
    const profile={capabilities:{streaming:'supported',thinking_off:{status:'supported'},thinking_off_streaming_combination:{status,resolution}}};
    vm.runInContext(`updateDefaultPreferenceControls(${JSON.stringify(profile)},'off','normal')`,page.context);
    const option=page.element('custom-default-response').children.find(o=>o.value==='streaming');
    assert.equal(option.disabled,status!=='supported');
    if(resolution==='EVIDENCE_CONFLICT') assert.match(option.textContent,/冲突/);
  }
});

function toolConversationFixture(overrides={}) {
  return {status:'completed',error_code:null,snapshot_status:'AVAILABLE',generated_text:'当前溶氧 2.2 mg/L，请优先增氧。',
    request_1:{outcome:'tool_calls'},request_2:{outcome:'final_answer'},
    tool_call:{id:'offline-call',name:'get_current_water_quality',arguments:{}},
    tool_result:{status:'OK',water_quality:{temperature_c:28,ph:7.5,dissolved_oxygen_mg_l:2.2,
      quality:'valid',freshness:'fresh'},findings:[{code:'OXYGEN_CRITICAL_LOW',message:'低氧'}]},
    final_finish_reason:'stop',usage:{total_tokens:null},...overrides};
}

function toolPage(fetch, options) {
  const page=makePage(fetch, options);
  page.element('tool-target').value='mock';
  page.element('tool-question').value='现在水质怎么样？';
  vm.runInContext("accessMode='development';credentialCsrf='offline-csrf';bindToolConversationControls()",page.context);
  return page;
}

test('T4 Tool Conversation button runs the shared endpoint independently of main Streaming and Scenario',async()=>{
  const calls=[];
  const page=toolPage(async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    return r2Reply({result:toolConversationFixture(),total_latency_ms:12});
  });
  page.element('response-mode').value='streaming';
  page.element('scenario').value='normal';
  await page.element('tool-run').dispatch('click');
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/tool-conversation');
  assert.deepEqual(Object.keys(calls[0].body).sort(),['control_token','question','request_id','response_mode','target']);
  assert.equal(calls[0].body.response_mode,'normal');
  assert.equal(calls[0].body.target,'mock');
  assert.match(page.element('tool-answer').textContent,/2.2/);
  assert.match(page.element('tool-trace').textContent,/Request #1.*tool_calls/);
  assert.match(page.element('tool-trace').textContent,/get_current_water_quality/);
  assert.match(page.element('tool-trace').textContent,/arguments: \{\}/);
  assert.match(page.element('tool-trace').textContent,/Tool Result/);
  assert.match(page.element('tool-trace').textContent,/OXYGEN_CRITICAL_LOW/);
  assert.match(page.element('tool-trace').textContent,/Request #2: final_answer/);
  assert.equal(page.element('tool-run').disabled,false);
  assert.equal(page.element('tool-stop').disabled,true);
});

test('T4 Tool Conversation refreshes only snapshot availability and Apply preview updates it',async()=>{
  let snapshot=null;
  const page=toolPage(async(url)=>{assert.equal(url,'/api/water-quality/current');return r2Reply({snapshot});});
  await page.element('tool-refresh-snapshot').dispatch('click');
  assert.match(page.element('tool-snapshot-status').textContent,/NO_DATA/);
  snapshot={water_quality:{temperature_c:28},evaluated_at:'test'};
  await page.element('tool-refresh-snapshot').dispatch('click');
  assert.match(page.element('tool-snapshot-status').textContent,/AVAILABLE/);
  vm.runInContext('showScenarioSnapshot({snapshot:null,status:"NO_DATA"})',page.context);
  assert.match(page.element('tool-snapshot-status').textContent,/NO_DATA/);
});

test('T4 Tool Conversation NO_DATA is a normal tool result followed by a final explanation',async()=>{
  const page=toolPage(async()=>r2Reply({result:toolConversationFixture({snapshot_status:'NO_DATA',
    generated_text:'没有当前数据',tool_result:{status:'NO_DATA',water_quality:null,findings:[]}})}));
  await page.element('tool-run').dispatch('click');
  assert.match(page.element('tool-snapshot-status').textContent,/NO_DATA/);
  assert.match(page.element('tool-trace').textContent,/NO_DATA/);
  assert.match(page.element('tool-trace').textContent,/Request #2: final_answer/);
  assert.equal(page.element('tool-answer').textContent,'没有当前数据');
});

test('T4 Tool Conversation concept question ends without a tool and preserves user text',async()=>{
  let body;
  const page=toolPage(async(_,options)=>{body=JSON.parse(options.body);return r2Reply({result:toolConversationFixture({
    generated_text:'溶氧是水中溶解的氧气',tool_call:null,tool_result:null,
    request_1:{outcome:'final_answer'},request_2:{outcome:'not_started'}})});});
  page.element('tool-question').value='什么是溶氧？';
  await page.element('tool-run').dispatch('click');
  assert.equal(body.question,'什么是溶氧？');
  assert.match(page.element('tool-trace').textContent,/未执行 Tool/);
  assert.match(page.element('tool-trace').textContent,/Request #2: not_started/);
});

test('T4 Tool Conversation displays stale and invalid facts rather than turning them into NO_DATA',async()=>{
  for(const [quality,freshness,code] of [['valid','stale','SENSOR_STALE'],['invalid','fresh','SENSOR_INVALID']]) {
    const result=toolConversationFixture();
    result.tool_result.water_quality.quality=quality;
    result.tool_result.water_quality.freshness=freshness;
    result.tool_result.findings=[{code,message:code}];
    const page=toolPage(async()=>r2Reply({result}));
    await page.element('tool-run').dispatch('click');
    assert.match(page.element('tool-trace').textContent,new RegExp(code));
    assert.match(page.element('tool-trace').textContent,new RegExp(freshness));
    assert.match(page.element('tool-snapshot-status').textContent,/AVAILABLE/);
  }
});

test('T4 Tool Conversation renders safe execution errors including the explicit Streaming rejection',async()=>{
  for(const code of ['UNKNOWN_TOOL','INVALID_TOOL_ARGUMENTS','TOOL_EXECUTION_ERROR','TOOL_CALL_LIMIT','TOOL_ROUND_LIMIT','USER_CANCELLED','TOOL_STREAMING_NOT_IMPLEMENTED','OPTION_UNKNOWN']) {
    const page=toolPage(async()=>r2Reply({status:'failed',error_code:code},false));
    await page.element('tool-run').dispatch('click');
    assert.match(page.element('tool-status').textContent,new RegExp(code));
    assert.match(page.element('tool-trace').textContent,new RegExp(code));
    assert.equal(page.element('tool-run').disabled,false);
    assert.equal(vm.runInContext('activeExecution',page.context),null);
  }
  const page=toolPage(async()=>r2Reply({result:toolConversationFixture({status:'failed',error_code:'TOOL_ROUND_LIMIT',generated_text:''})},false,502));
  await page.element('tool-run').dispatch('click');
  assert.match(page.element('tool-status').textContent,/TOOL_ROUND_LIMIT/);
});

test('T4 Tool Conversation fetch and JSON errors are visible without private exception text',async()=>{
  for(const fetch of [async()=>{throw new Error('fake-secret-and-private-path');},async()=>({ok:false,json:async()=>{throw new SyntaxError('fake-private-response');}})]) {
    const page=toolPage(fetch);
    await page.element('tool-run').dispatch('click');
    assert.match(page.element('tool-status').textContent,/NETWORK_ERROR/);
    assert.doesNotMatch(page.element('tool-status').textContent,/fake-/);
    assert.equal(page.element('tool-run').disabled,false);
  }
});

test('T4 Tool Conversation selected runtime remains gated and requires its own explicit confirmation',async()=>{
  const calls=[];
  const page=toolPage(async(url)=>{calls.push(url);return r2Reply({error_code:'OPTION_UNKNOWN'},false);});
  setProfile(page);
  vm.runInContext("developmentReturnState=Object.freeze({originRuntimeId:'mock-demo'})",page.context);
  page.element('tool-target').value='selected';
  await page.element('tool-target').dispatch('change');
  assert.equal(page.element('tool-run').disabled,true);
  assert.match(page.element('tool-target-status').textContent,/OPTION_UNKNOWN/);
  assert.equal(page.element('tool-real-warning').hidden,false);
  await vm.runInContext('runToolConversation()',page.context);
  assert.match(page.element('tool-status').textContent,/REAL NETWORK REQUEST/);
  assert.deepEqual(calls,[]);
  page.element('tool-confirm-network').checked=true;
  page.element('tool-target').value='mock';
  await page.element('tool-target').dispatch('change');
  assert.equal(page.element('tool-confirm-network').checked,false);
  assert.equal(page.element('tool-run').disabled,false);
});

test('T4 Tool Conversation blocks duplicate submissions and Stop uses existing cancellation',async()=>{
  const calls=[];
  const page=toolPage(async(url,options)=>{
    calls.push(url);
    if(url==='/api/requests') return r2Reply({request_id:'t4',control_token:'offline-control'});
    if(url.endsWith('/cancel')) return r2Reply({state:'CANCELLED',backend_io_closed:true});
    assert.equal(url,'/api/tool-conversation');
    return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('AbortError'))));
  },{ownExecutionRoutes:true});
  const running=page.element('tool-run').dispatch('click');
  await new Promise(setImmediate);
  assert.equal(page.element('tool-run').disabled,true);
  assert.equal(page.element('tool-stop').disabled,false);
  await vm.runInContext('runToolConversation()',page.context);
  assert.equal(calls.filter(x=>x==='/api/tool-conversation').length,1);
  await page.element('tool-stop').dispatch('click');
  await running;
  assert.match(page.element('tool-status').textContent,/USER_CANCELLED/);
  assert.doesNotMatch(page.element('tool-trace').textContent,/正在等待/);
  assert.equal(page.element('tool-answer').textContent,'');
  assert.equal(page.element('tool-run').disabled,false);
  assert.equal(page.element('tool-stop').disabled,true);
  assert.equal(vm.runInContext('activeExecution',page.context),null);
  assert.deepEqual(calls,['/api/requests','/api/tool-conversation','/api/requests/t4/cancel']);
});

test('T4 Tool Conversation shares execution locking with existing analysis and renders final text safely',async()=>{
  const page=toolPage(async()=>{assert.fail('no real network');});
  await vm.runInContext('beginExecution()',page.context);
  assert.equal(page.element('tool-run').disabled,true);
  assert.equal(page.element('tool-stop').disabled,true);
  vm.runInContext('finishExecution()',page.context);
  assert.equal(page.element('tool-run').disabled,false);
  vm.runInContext(`renderToolConversation(${JSON.stringify(toolConversationFixture({generated_text:'<script>private()</script>'}))},3)`,page.context);
  assert.equal(page.element('tool-answer').textContent,'<script>private()</script>');
  assert.equal(html.includes('id="tool-conversation-panel"'),true);
});

function developmentUxPage(extraFetch=null) {
  const items=threeModeFixtures();
  const origin=items.find(item=>item.profile_id==='user-local');
  origin.display_name='DS_1';
  origin.capabilities={...origin.capabilities,tool_calling:{status:'supported'}};
  return threeModePage(async(url,options)=>{
    if(url==='/api/water-quality/current')return r2Reply({snapshot:null});
    if(extraFetch){const response=await extraFetch(url,options);if(response)return response;}
    return null;
  },items);
}

test('Tool Capability UI T5 Probe unlocks Managed exact Profile only after successful evidence',async()=>{
  let sent;
  const page=developmentUxPage(async(url,options)=>{
    if(url==='/api/profiles/user-local/tool-probe') {
      sent=JSON.parse(options.body);
      const profile={...page.items.find(p=>p.profile_id==='user-local'),capabilities:{tool_calling:{status:'supported',source:'explicit_probe'}}};
      return r2Reply({verdict:'SUPPORTED',evidence_written:true,request_1:'tool_calls',request_2:'final_answer',
        model_requests:2,tool_result_status:'NO_DATA',profile});
    }
    return null;
  });
  page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  assert.equal(page.element('tool-probe').hidden,false);
  assert.equal(page.element('tool-reprobe').hidden,true);
  vm.runInContext('window.confirm=()=>false',page.context);
  await page.element('tool-probe').dispatch('click');
  assert.equal(sent,undefined);
  assert.match(page.element('tool-probe-result').textContent,/已取消/);
  vm.runInContext("credentialCsrf='offline-csrf';window.confirm=()=>true",page.context);
  await page.element('tool-probe').dispatch('click');
  assert.equal(sent.confirm_network,true);
  assert.equal(Object.hasOwn(sent,'question'),false);
  assert.match(page.element('tool-probe-result').textContent,/SUPPORTED.*已写入/);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'user-local');
  assert.equal(vm.runInContext('selectedProfile().capabilities.tool_calling.source',page.context),'explicit_probe');
  assert.equal(page.element('tool-probe').hidden,true);
  assert.equal(page.element('tool-reprobe').hidden,false);
  assert.match(page.element('capability-list').children.map(x=>x.textContent).join(' '),/Tool Calling 支持/);
  await page.element('use-development').dispatch('click');
  page.element('tool-target').value='selected';await page.element('tool-target').dispatch('change');
  assert.equal(page.element('tool-run').disabled,false);
});

test('Tool Capability UI T5 failures remain visible without granting UNKNOWN runtime',async()=>{
  for(const failure of ['CONNECT_TIMEOUT','HTTP_401','HTTP_429','NO_TOOL_CALL']) {
    const page=developmentUxPage(async(url)=>url.endsWith('/tool-probe')?
      r2Reply({verdict:'UNKNOWN',evidence_written:false,error_code:failure,model_requests:1},false,502):null);
    page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
    await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
    vm.runInContext("credentialCsrf='offline-csrf'",page.context);
    await page.element('tool-probe').dispatch('click');
    assert.match(page.element('tool-probe-result').textContent,new RegExp(failure));
    assert.match(page.element('tool-probe-result').textContent,/未写入/);
    assert.equal(vm.runInContext('selectedProfile().capabilities.tool_calling.status',page.context),'unknown');
    assert.equal(page.element('tool-probe').disabled,false);
  }
});

test('Tool Capability UI Probe is hidden for Mock Preset Manual and Development',async()=>{
  const page=developmentUxPage();await vm.runInContext('init()',page.context);
  assert.equal(page.element('tool-probe').hidden,true);
  assert.equal(page.element('tool-reprobe').hidden,true);
  await page.element('use-development').dispatch('click');
  assert.equal(page.element('tool-probe').hidden,true);
  await page.element('return-normal').dispatch('click');
  await page.element('use-development').dispatch('click');
  page.element('tool-target').value='selected';await page.element('tool-target').dispatch('change');
  assert.equal(page.element('tool-probe').hidden,true);
  const dev=html.slice(html.indexOf('id="development-workspace"'),html.indexOf('id="manual-expert"'));
  assert.equal(dev.includes('id="tool-probe"'),false);
  const advanced=html.slice(html.indexOf('id="advanced-capability-actions"'),html.indexOf('runtime-options-heading'));
  assert.match(advanced,/id="tool-probe"/);
  assert.match(advanced,/id="tool-reprobe"/);
  await page.element('return-normal').dispatch('click');
  await vm.runInContext('setAccessMode("manual_expert","user-local")',page.context);
  assert.equal(page.element('tool-probe').hidden,true);
});

test('Tool Capability UI T5 malformed JSON or fetch failure never silently succeeds',async()=>{
  for(const bad of ['json','fetch']) {
    const page=developmentUxPage(async(url)=>{
      if(!url.endsWith('/tool-probe'))return null;
      if(bad==='fetch')throw new Error('private fake transport exception');
      return {ok:false,json:async()=>{throw new SyntaxError('fake invalid JSON');}};
    });
    page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
    await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
    vm.runInContext("credentialCsrf='offline-csrf'",page.context);
    await page.element('tool-probe').dispatch('click');
    assert.match(page.element('tool-probe-result').textContent,/NETWORK_ERROR/);
    assert.doesNotMatch(page.element('tool-probe-result').textContent,/private|fake/);
    assert.equal(vm.runInContext('selectedProfile().capabilities.tool_calling.status',page.context),'unknown');
    assert.equal(vm.runInContext('activeExecution',page.context),null);
  }
});

test('Tool Capability UI Development UNKNOWN explains management path and never auto Probes',async()=>{
  const page=developmentUxPage();
  page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('use-development').dispatch('click');
  page.element('tool-target').value='selected';await page.element('tool-target').dispatch('change');
  assert.match(page.element('tool-target-status').textContent,/请先在 Managed Custom → 模型能力中验证 Tool Calling/);
  const count=page.calls.length;
  await vm.runInContext('probeToolCalling()',page.context);
  assert.equal(page.calls.length,count);
  assert.equal(page.element('tool-probe').hidden,true);
  assert.equal(page.element('tool-run').disabled,true);
  await page.element('return-normal').dispatch('click');
  assert.equal(page.element('tool-probe').hidden,false);
});

test('Tool Capability UI verified Profile has reverify and switching identity recomputes buttons',async()=>{
  const page=developmentUxPage();
  page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'supported',source:'explicit_probe'};
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  assert.equal(page.element('tool-probe').hidden,true);
  assert.equal(page.element('tool-reprobe').hidden,false);
  const other=page.items.find(p=>p.profile_id==='user-local');
  other.capabilities.tool_calling={status:'unknown'};
  await vm.runInContext('updateProfile()',page.context);
  assert.equal(page.element('tool-probe').hidden,false);
  assert.equal(page.element('tool-reprobe').hidden,true);
});

test('Tool Capability UI duplicate Probe blocked and common Stop cancels without touching conversation Trace',async()=>{
  let release;let count=0;
  const page=developmentUxPage(async(url)=>{
    if(url.endsWith('/tool-probe')){count++;return await new Promise(resolve=>{release=resolve;});}
    return null;
  });
  page.items.find(p=>p.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  vm.runInContext("credentialCsrf='offline-csrf'",page.context);
  page.element('tool-trace').textContent='previous conversation trace';
  const running=page.element('tool-probe').dispatch('click');
  for(let i=0;i<10&&!release;i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(page.element('tool-probe').disabled,true);
  assert.equal(vm.runInContext('activeExecution.kind',page.context),'tool_probe');
  await vm.runInContext('probeToolCalling()',page.context);
  assert.equal(count,1);
  await page.element('stop-generation').dispatch('click');
  release(r2Reply({verdict:'UNKNOWN',evidence_written:false,error_code:'USER_CANCELLED'}));
  await running;
  assert.match(page.element('tool-probe-result').textContent,/USER_CANCELLED/);
  assert.equal(page.element('tool-trace').textContent,'previous conversation trace');
  assert.equal(vm.runInContext('activeExecution',page.context),null);
  assert.equal(page.element('tool-probe').disabled,false);
});

test('Tool Capability UI probes persisted Profile rather than edited Identity draft',async()=>{
  let target;
  const page=developmentUxPage(async(url)=>{
    if(url.endsWith('/tool-probe')){target=url;return r2Reply({verdict:'UNKNOWN',evidence_written:false,error_code:'NO_TOOL_CALL'});}
    return null;
  });
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('edit-profile').dispatch('click');
  page.element('custom-model').value='unsaved-different-model';
  page.element('custom-url').value='https://draft.invalid/v1';
  vm.runInContext("credentialCsrf='offline-csrf'",page.context);
  await page.element('tool-probe').dispatch('click');
  assert.equal(target,'/api/profiles/user-local/tool-probe');
  assert.equal(page.element('custom-model').value,'unsaved-different-model');
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'local-model');
});

test('Development UX normal Preset Managed and Manual expose only entry without experimental controls',async()=>{
  const page=developmentUxPage();
  await vm.runInContext('init()',page.context);
  for(const mode of ['preset','managed_custom','manual_expert']) {
    await vm.runInContext(`setAccessMode('${mode}')`,page.context);
    assert.equal(page.element('development-entry').hidden,false);
    assert.equal(page.element('development-intro').hidden,false);
    assert.equal(page.element('use-development').hidden,false);
    assert.equal(page.element('development-workspace').hidden,true);
    assert.equal(page.element('tool-conversation-panel').hidden,true);
    assert.equal(page.element('return-normal').hidden,true);
    assert.equal(page.element('tool-run').disabled,true);
  }
  const count=page.calls.length;
  await vm.runInContext('runToolConversation()',page.context);
  assert.match(page.element('tool-status').textContent,/请先进入开发验证/);
  assert.equal(page.calls.length,count);
});

test('Development UX enter opens experiments with Mock while retaining exact origin DS_1',async()=>{
  const page=developmentUxPage();
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('use-development').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'development');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'mock-demo');
  assert.equal(vm.runInContext('developmentReturnState.mode',page.context),'managed_custom');
  assert.equal(vm.runInContext('developmentReturnState.originRuntimeId',page.context),'user-local');
  assert.equal(page.element('use-development').hidden,true);
  for(const id of ['development-workspace','tool-conversation-panel','return-normal'])assert.equal(page.element(id).hidden,false);
  assert.equal(page.element('tool-conversation-panel').open,true);
  assert.equal(page.element('tool-target').value,'mock');
  assert.equal(page.element('tool-origin-target').textContent,'真实 Runtime · DS_1');
  assert.match(page.element('tool-target-status').textContent,/Mock Tool Calling.*完全离线/);
  page.element('tool-target').value='selected';
  await page.element('tool-target').dispatch('change');
  assert.match(page.element('tool-target-status').textContent,/真实 Runtime · DS_1.*能力门禁保护/);
  assert.equal(page.element('tool-run').disabled,false);
  assert.equal(page.element('tool-real-warning').hidden,false);
});

test('Development UX real Tool request uses origin id rather than top Mock and requires confirmation',async()=>{
  let body;
  const page=developmentUxPage(async(url,options)=>{
    if(url==='/api/tool-conversation'){body=JSON.parse(options.body);return r2Reply({result:toolConversationFixture()});}
    return null;
  });
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('use-development').dispatch('click');
  page.element('tool-target').value='selected';await page.element('tool-target').dispatch('change');
  await page.element('tool-run').dispatch('click');
  assert.equal(body,undefined);
  assert.match(page.element('tool-status').textContent,/REAL NETWORK REQUEST/);
  page.element('tool-confirm-network').checked=true;
  vm.runInContext("credentialCsrf='offline-csrf'",page.context);
  await page.element('tool-run').dispatch('click');
  assert.equal(body.profile_id,'user-local');
  assert.equal(body.target,'selected');
  assert.equal(body.confirm_network,true);
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'mock-demo');
  assert.equal(page.element('tool-confirm-network').checked,false);
});

test('Development UX changing experimental target cannot overwrite origin or grant unknown real capability',async()=>{
  const page=developmentUxPage();
  page.items.find(x=>x.profile_id==='user-local').capabilities.tool_calling={status:'unknown'};
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('use-development').dispatch('click');
  page.element('development-target').value='ollama-qwen35-4b-local';
  await page.element('development-target').dispatch('change');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'ollama-qwen35-4b-local');
  assert.equal(vm.runInContext('originToolProfile().profile_id',page.context),'user-local');
  page.element('tool-target').value='selected';await page.element('tool-target').dispatch('change');
  assert.equal(page.element('tool-run').disabled,true);
  assert.match(page.element('tool-target-status').textContent,/DS_1.*OPTION_UNKNOWN/);
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'user-local');
});

test('Development UX return restores Managed runtime options without any Profile Credential or Evidence writes',async()=>{
  const page=developmentUxPage();
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  page.element('reasoning-mode').value='off';page.element('response-mode').value='streaming';
  const profilesBefore=vm.runInContext('JSON.stringify(profiles)',page.context);
  const count=page.calls.length;
  await page.element('use-development').dispatch('click');
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'managed_custom');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'user-local');
  assert.equal(page.element('reasoning-mode').value,'off');
  assert.equal(page.element('response-mode').value,'streaming');
  assert.equal(vm.runInContext('JSON.stringify(profiles)',page.context),profilesBefore);
  assert.equal(page.element('tool-conversation-panel').hidden,true);
  assert.equal(page.element('use-development').hidden,false);
  assert.equal(page.calls.slice(count).some(x=>/probe|metadata|credentials|evidence|apply|requests|tool-conversation/.test(x.url)),false);
  assert.equal(vm.runInContext('developmentReturnState',page.context),null);
});

test('Development UX return restores exact Preset variant and independent Streaming choice',async()=>{
  const page=developmentUxPage();await vm.runInContext('init()',page.context);
  page.element('preset-variant').value='preset-qwen-plus-on';await page.element('preset-variant').dispatch('change');
  page.element('response-mode').value='streaming';
  await page.element('use-development').dispatch('click');
  assert.equal(vm.runInContext('originToolProfile().profile_id',page.context),'preset-qwen-plus-on');
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'preset');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'preset-qwen-plus-on');
  assert.equal(page.element('response-mode').value,'streaming');
});

test('Development UX Manual V1 returns its saved target and untouched raw draft',async()=>{
  const page=developmentUxPage();await vm.runInContext('(async()=>{await init();await setAccessMode("manual_expert","user-local");})()',page.context);
  const raw='{ "model": "local-model", "messages": [], "stream": true }';
  page.element('manual-body').value=raw;
  await page.element('use-development').dispatch('click');
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'manual_expert');
  assert.equal(vm.runInContext('selectedProfile().profile_id',page.context),'user-local');
  assert.equal(page.element('manual-body').value,raw);
  assert.equal(page.element('manual-expert').hidden,false);
});

test('Development UX Manual V2 retains independent experiment and has no implicit V1 real target',async()=>{
  const page=developmentUxPage();await vm.runInContext('(async()=>{await init();await setAccessMode("manual_expert","user-local");})()',page.context);
  vm.runInContext("manualVersion='v2';experimentId='offline-experiment';updateManualVersionView()",page.context);
  page.element('experiment-name').value='Experiment draft';
  page.element('manual-body').value='untouched V1';
  await page.element('use-development').dispatch('click');
  assert.equal(vm.runInContext('originToolProfile()',page.context),undefined);
  assert.equal(page.element('tool-origin-target').disabled,true);
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('manualVersion',page.context),'v2');
  assert.equal(vm.runInContext('experimentId',page.context),'offline-experiment');
  assert.equal(page.element('experiment-name').value,'Experiment draft');
  assert.equal(page.element('manual-body').value,'untouched V1');
  assert.equal(page.element('profile').hidden,true);
});

test('Development UX empty normal selection remains empty after return rather than picking another runtime',async()=>{
  const page=developmentUxPage();await vm.runInContext('(async()=>{await init();await setAccessMode("preset");})()',page.context);
  page.element('profile').value='';page.element('preset-variant').value='';await vm.runInContext('updateProfile()',page.context);
  await page.element('use-development').dispatch('click');
  assert.equal(page.element('tool-origin-target').disabled,true);
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('selectedProfile()',page.context),undefined);
  assert.equal(page.element('analyze').disabled,true);
});

test('Development UX restores an unsaved Managed edit draft without copying new Secret input',async()=>{
  const page=developmentUxPage();
  await vm.runInContext('(async()=>{await init();await setAccessMode("managed_custom");})()',page.context);
  await page.element('edit-profile').dispatch('click');
  page.element('custom-model').value='unsaved-model-draft';
  page.element('custom-url').value='https://draft.invalid/v1';
  page.element('credential-value').value='fictional-unsaved-secret';
  const before=vm.runInContext('JSON.stringify(profiles)',page.context);
  await page.element('use-development').dispatch('click');
  assert.doesNotMatch(vm.runInContext('JSON.stringify(developmentReturnState)',page.context),/fictional-unsaved-secret/);
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('formMode',page.context),'edit');
  assert.equal(page.element('custom-model').value,'unsaved-model-draft');
  assert.equal(page.element('custom-url').value,'https://draft.invalid/v1');
  assert.equal(vm.runInContext('selectedProfile().model',page.context),'local-model');
  assert.equal(vm.runInContext('JSON.stringify(profiles)',page.context),before);
  assert.equal(page.element('credential-value').value,'');
  assert.equal(page.element('cancel-edit').hidden,false);
});

test('Development UX snapshot display action only reads current state without Apply or simulator request',async()=>{
  const page=developmentUxPage();await vm.runInContext('init()',page.context);
  await page.element('use-development').dispatch('click');
  const count=page.calls.length;
  await page.element('tool-refresh-snapshot').dispatch('click');
  assert.deepEqual(page.calls.slice(count).map(x=>x.url),['/api/water-quality/current']);
  assert.match(html,/id="tool-refresh-snapshot"[^>]*>更新快照状态显示</);
  assert.equal(html.includes('刷新快照状态'),false);
});

test('Development UX return stays locked while T4 request runs and Mock Trace Final and Stop remain available',async()=>{
  const page=developmentUxPage();await vm.runInContext('init()',page.context);
  await page.element('use-development').dispatch('click');
  await vm.runInContext("credentialCsrf='offline-csrf';beginExecution()",page.context);
  assert.equal(page.element('return-normal').disabled,true);
  await vm.runInContext('returnNormalMode()',page.context);
  assert.equal(vm.runInContext('accessMode',page.context),'development');
  vm.runInContext('finishExecution()',page.context);
  assert.equal(page.element('return-normal').disabled,false);
  await page.element('return-normal').dispatch('click');
  assert.equal(vm.runInContext('accessMode',page.context),'preset');
});


test('Experimental score Tool is configurable in both Policy tabs without changing defaults',async()=>{
  let state=toolManagerFixture();
  const page=toolManagerPage(async(_url,options)=>{
    if(options.method==='PUT')state={...state,policy:{...state.policy,...JSON.parse(options.body)}};
    return r2Reply(state);
  });
  await page.element('open-tool-manager').dispatch('click');
  for(const tab of ['analysis','assistant']) {
    await page.element(`tool-policy-${tab}`).dispatch('click');
    const row=page.element('tool-catalog-list').children[1];
    const checkbox=row.children[0].children[0];
    assert.equal(checkbox.checked,false);assert.equal(checkbox.disabled,false);
    await row.children[0].children[3].dispatch('click');
    assert.match(row.children[1].children.map(n=>n.textContent).join(' '),/EXPERIMENTAL/);
    checkbox.checked=true;await checkbox.dispatch('change');
  }
  await page.element('tool-policy-save').dispatch('click');
  assert.deepEqual(state.policy.modes.analysis.selected_tools,['score_current_water_quality']);
  assert.deepEqual(state.policy.modes.assistant.selected_tools,['get_current_water_quality','score_current_water_quality']);
});

test('Analysis Tool Activity renders score and future tool result JSON generically and safely',()=>{
  const page=makePage(async()=>assert.fail('no network'));
  for(const name of ['score_current_water_quality','example_read_only_tool']) {
    const activity={allowed_tools:[name],called:true,requested:true,tool_name:name,arguments_summary:'{}',
      result_status:'PARTIAL',duration_ms:2,snapshot_comparison:'consistent',
      request_1:{outcome:'tool_calls'},request_2:{outcome:'final_answer'},
      tool_result:{status:'PARTIAL',score:72,standard:'EXPERIMENTAL / NOT PROFESSIONAL STANDARD',
        components:{dissolved_oxygen:{score:44}},note:'<img src=x onerror=alert(1)>'}};
    vm.runInContext(`render(${JSON.stringify(analysisActivityResult(activity))},10)`,page.context);
    assert.match(page.element('analysis-tool-summary').children.map(n=>n.textContent).join(' '),new RegExp(name));
    const record=JSON.parse(page.element('analysis-tool-record').textContent);
    assert.equal(record.tool_observation.score,72);
    assert.equal(record.tool_observation.components.dissolved_oxygen.score,44);
    assert.match(page.element('facts').children.map(n=>n.textContent).join(' '),/initial-fixture/);
    assert.equal(page.element('analysis-tool-activity').open,false);
  }
});
