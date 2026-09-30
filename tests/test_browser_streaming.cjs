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
const knownIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]));

function makePage(fetch) {
  const controls = new Map();
  class Element {
    constructor() {
      this.value = '';
      this.textContent = '';
      this.hidden = false;
      this.disabled = false;
      this.checked = false;
      this.children = [];
      this.classList = {toggle() {}, add() {}, remove() {}};
    }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children = items; }
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
  const context = vm.createContext({document, fetch, TextDecoder, Uint8Array});
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

function setProfile(page, real = false) {
  const profile = real
    ? {profile_id: 'qwen-plus-experimental', runtime_type: 'cloud'}
    : {profile_id: 'mock-demo', runtime_type: 'mock'};
  vm.runInContext(`profiles = [${JSON.stringify(profile)}]`, page.context);
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
  assert.equal(page.element('streaming-output').textContent, '你好');
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
  assert.match(page.element('streaming-capability').textContent, /本机已验证.*SUPPORTED.*精确 Model \/ Base URL/);
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
  assert.match(page.element('streaming-capability').textContent, /UNKNOWN.*未绑定当前 Model \/ Base URL/);
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
    'custom-secret-env': '', 'custom-deployment': 'local'};
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
  vm.runInContext(`profiles = [${JSON.stringify(exact)}]`, page.context);
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
  page.element('confirm-network').checked = true;
  await vm.runInContext('analyze()', page.context);
  assert.equal(Object.hasOwn(sent, 'reasoning_mode'), false);
});
