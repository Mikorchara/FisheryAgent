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

test('Built-in collision hides update, user collision shows it', async () => {
  let sourceType = 'built_in';
  const page = makePage(async () => ({status: 409, ok: false, json: async () => ({
    reason: 'SAME_ENDPOINT_MODEL', existing: {profile_id: 'existing',
      display_name: '已有配置', source: sourceType},
    allowed_actions: sourceType === 'built_in' ? ['copy', 'cancel'] : ['update', 'copy', 'cancel'],
  })}));
  const values = {'provider-preset': 'custom', 'custom-name': '测试配置',
    'custom-provider': 'custom', 'custom-adapter': 'generic_openai_chat',
    'custom-url': 'http://localhost:11434/v1', 'custom-model': 'demo',
    'custom-secret-env': '', 'custom-deployment': 'local'};
  for (const [id, value] of Object.entries(values)) page.element(id).value = value;
  await vm.runInContext('saveCustomProfile()', page.context);
  assert.equal(page.element('conflict-update').hidden, true);
  sourceType = 'user_custom';
  await vm.runInContext('saveCustomProfile()', page.context);
  assert.equal(page.element('conflict-update').hidden, false);
});
