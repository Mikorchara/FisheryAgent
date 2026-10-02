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
  assert.equal(status.length,7);
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
      thinking_on:{status:'supported'},thinking_off:{status:'supported'}}};
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
    thinking_streaming_combination: {status: 'unknown'}}};
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
    async dispatch(type) {
      const event = {type, target: this};
      return Promise.all((this.listeners.get(type) || []).map((handler) => handler(event)));
    }
    removeAttribute() {}
    setAttribute() {}
    focus() {}
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
  const context = vm.createContext({document, fetch:guardedFetch, TextDecoder, Uint8Array, AbortController, setTimeout,
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
  assert.match(html, /基础模型配置/);
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

test('editing the basic model identity clears draft capability display before save', () => {
  const page = makePage(async () => ({ok: true, json: async () => ({})}));
  page.element('reasoning-mode').value = 'off';
  page.element('response-mode').value = 'streaming';
  page.element('thinking-probe-actions').hidden = false;
  page.element('thinking-reverify-actions').hidden = false;
  vm.runInContext('formMode = "edit"; invalidateTest()', page.context);
  assert.match(page.element('streaming-capability').textContent, /UNKNOWN/);
  assert.equal(page.element('probe-streaming').hidden, true);
  assert.equal(page.element('probe-thinking-on').hidden, true);
  assert.equal(page.element('reprobe-thinking-on').hidden, true);
  assert.equal(page.element('reasoning-mode').value, 'auto');
  assert.equal(page.element('response-mode').value, 'normal');
  assert.equal(page.element('reasoning-mode').children.find((item) => item.value === 'on').disabled, true);
  assert.equal(page.element('response-mode').children.find((item) => item.value === 'streaming').disabled, true);
  assert.equal(page.element('reasoning-effort').children.find((item) => item.value === '__unknown__').disabled, true);
  assert.equal(page.element('refresh-metadata').hidden, true);
});

test('Profile switching restores saved runtime defaults and verified probes move to advanced actions', async () => {
  const first = {profile_id: 'custom-local-a', display_name: 'Local A', provider: 'custom',
    service_id: 'custom', model: 'a', profile_status: 'custom', runtime_type: 'local',
    source: 'user_custom', reasoning_modes: ['auto', 'on', 'off'],
    default_reasoning_mode: 'off', default_response_mode: 'streaming', capabilities: {
      streaming: 'supported', source: 'USER_VERIFIED',
      thinking_on: {status: 'supported', source: 'USER_VERIFIED'},
      thinking_off: {status: 'supported', source: 'USER_VERIFIED'},
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
    thinking_streaming_combination: {status: 'supported', source: 'USER_VERIFIED'}, effort_values: ['low', 'high']}};
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
    'analyze','results','empty-state','preset-variant-field','development-entry'])assert.equal(page.element(id).hidden,true,id);
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
