const $ = (id) => document.getElementById(id);
let profiles = [];
let presets = [];
let editingId = null;
let testId = null;
let testedFingerprint = null;
let pendingConflict = null;

function show(value) {
  return value === null || value === undefined || value === "" ? "unavailable" : String(value);
}

function setStatus(message, isError = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", isError);
}

function addPairs(targetId, pairs) {
  const target = $(targetId);
  target.replaceChildren();
  for (const [label, value] of pairs) {
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = show(value);
    target.append(dt, dd);
  }
}

function addList(targetId, items, renderer) {
  const target = $(targetId);
  target.replaceChildren();
  if (!items || items.length === 0) {
    const li = document.createElement("li");
    li.textContent = "无";
    target.append(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    renderer(li, item);
    target.append(li);
  }
}

function block(li, title, body, detail = "") {
  const strong = document.createElement("strong");
  strong.textContent = title;
  const content = document.createElement("span");
  content.textContent = body;
  li.append(strong, content);
  if (detail) {
    const small = document.createElement("small");
    small.textContent = detail;
    li.append(small);
  }
}

function selectedProfile() {
  return profiles.find((item) => item.profile_id === $("profile").value);
}

function renderProfiles(selectedId = "mock-demo") {
  $("profile").replaceChildren();
  const builtIn = document.createElement("optgroup");
  builtIn.label = "Built-in Profiles";
  const custom = document.createElement("optgroup");
  custom.label = "User Custom Profiles";
  for (const item of profiles) {
    const option = document.createElement("option");
    option.value = item.profile_id;
    option.textContent = item.display_name;
    (item.source === "user_custom" ? custom : builtIn).append(option);
  }
  $("profile").append(builtIn, custom);
  $("profile").value = selectedId;
  updateProfile();
}

function updateProfile() {
  const profile = selectedProfile();
  if (!profile) return;
  if (editingId && editingId !== profile.profile_id) {
    editingId = null;
    $("save-profile").textContent = "保存 Profile";
    invalidateTest();
    $("custom-status").textContent = "已退出原配置的编辑；当前表单保存后将新建配置。";
  }
  $("profile-meta").textContent = `${profile.provider} · ${profile.model} · ${profile.profile_status.toUpperCase()} · ${profile.runtime_type} · ${profile.source === "user_custom" ? "用户自定义" : "预置"}`;
  const real = profile.runtime_type !== "mock";
  $("real-warning").hidden = !real;
  $("confirm-network").checked = false;
  setStatus(real ? "此 Profile 会发起真实模型请求，请先确认。" : "Mock 模式始终离线。", false);
  $("edit-profile").hidden = profile.source !== "user_custom";
  $("delete-profile").hidden = profile.source !== "user_custom";
  if (!real) {
    $("selected-secret-status").textContent = "Mock 无需 Secret";
  } else {
    const selectedId = profile.profile_id;
    const preset = presets.find((item) => item.provider_id === profile.provider);
    const name = preset?.secret_env || "";
    if (profile.source === "user_custom") {
      fetch(`/api/profiles/${encodeURIComponent(selectedId)}`).then((response) => response.json())
        .then((data) => { if ($("profile").value === selectedId) showSecret(data.fields?.secret_env || "", "selected-secret-status"); })
        .catch(() => { $("selected-secret-status").textContent = "Secret 状态暂不可用"; });
    } else {
      showSecret(name, "selected-secret-status");
    }
  }
}

const customFields = {
  display_name: "custom-name", provider_id: "custom-provider",
  adapter_id: "custom-adapter", base_url: "custom-url", model: "custom-model",
  secret_env: "custom-secret-env", provider_kind: "custom-deployment",
};

function updateSecretRequirement() {
  const cloud = $("custom-deployment").value === "cloud";
  $("custom-secret-env").required = cloud;
  $("custom-secret-requirement").textContent = cloud ? "Cloud 必填" : "Local 可选";
}

function collectFields() {
  return Object.fromEntries(Object.entries(customFields)
    .map(([field, id]) => [field, $(id).value.trim()]));
}

function connectionFingerprint(fields) {
  return JSON.stringify([fields.provider_id, fields.adapter_id, fields.base_url, fields.model,
    fields.secret_env, fields.provider_kind]);
}

function invalidateTest() {
  testId = null;
  testedFingerprint = null;
  $("test-status").textContent = "连接字段已改变；Cloud 保存前需重新测试。";
}

async function showSecret(name, targetId) {
  const target = $(targetId);
  if (!name) {
    target.textContent = "Secret：未配置（Local 可不需要）";
    return;
  }
  try {
    const response = await fetch("/api/secret-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({secret_env: name}),
    });
    const data = await response.json();
    target.textContent = `${name}: ${response.ok ? data.status : "MISSING"}`;
  } catch (_) {
    target.textContent = `${name}: 状态不可用`;
  }
}

function selectPreset() {
  const preset = presets.find((item) => item.id === $("provider-preset").value);
  if (!preset) return;
  $("custom-provider").value = preset.provider_id;
  $("custom-adapter").value = preset.adapter_id;
  $("custom-url").value = preset.id === "custom" ? "" : preset.base_url;
  $("custom-model").value = "";
  $("custom-secret-env").value = preset.secret_env || "";
  $("custom-deployment").value = preset.provider_kind;
  $("model-options").hidden = true;
  updateSecretRequirement();
  showSecret($("custom-secret-env").value, "secret-status");
  invalidateTest();
}

function newProfile() {
  editingId = null;
  $("save-profile").textContent = "保存 Profile";
  $("custom-name").value = "";
  $("provider-preset").value = "";
  $("custom-provider").value = "";
  $("custom-adapter").value = "openai_chat";
  $("custom-url").value = "";
  $("custom-model").value = "";
  $("custom-secret-env").value = "";
  $("custom-deployment").value = "cloud";
  $("model-options").hidden = true;
  $("advanced-settings").open = false;
  $("models-status").textContent = "";
  showSecret("", "secret-status");
  updateSecretRequirement();
  invalidateTest();
  $("custom-status").textContent = "新配置尚未保存。";
  $("conflict-panel").hidden = true;
}

async function editSelected() {
  const selected = selectedProfile();
  if (!selected || selected.source !== "user_custom") return;
  const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}`);
  if (!response.ok) return profileError("profile", "无法读取所选配置。");
  const data = await response.json();
  editingId = selected.profile_id;
  $("save-profile").textContent = "更新 Profile";
  $("provider-preset").value = presets.some((p) => p.id === data.fields.provider_id)
    ? data.fields.provider_id : "custom";
  for (const [field, id] of Object.entries(customFields)) $(id).value = data.fields[field] || "";
  updateSecretRequirement();
  $("advanced-settings").open = false;
  showSecret(data.fields.secret_env, "secret-status");
  invalidateTest();
  $("custom-editor").open = true;
  $("custom-status").textContent = "正在编辑所选 CUSTOM Profile；Cloud 修改保存前需重新测试。";
  $("conflict-panel").hidden = true;
}

async function deleteSelected() {
  const selected = selectedProfile();
  if (!selected || selected.source !== "user_custom") return;
  if (!window.confirm(`删除 ${selected.display_name}？配置会移入本地 archive，可手工恢复。`)) return;
  const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}`, {method: "DELETE"});
  const data = await response.json();
  if (!response.ok) return profileError("profile", data.error_code || "删除失败");
  await refreshProfiles("mock-demo");
  newProfile();
  $("custom-status").textContent = "配置已从列表移除，原文件保存在本地 archive。";
}

async function refreshProfiles(selectedId) {
  const response = await fetch("/api/config");
  const data = await response.json();
  profiles = data.profiles;
  renderProfiles(selectedId);
}

function profileError(field, message) {
  const control = $(field === "provider_preset" ? "provider-preset" : customFields[field]);
  if (control) {
    control.setAttribute("aria-invalid", "true");
    control.focus();
  }
  $("custom-status").textContent = `保存失败：${field || "profile"} — ${message}`;
  $("custom-status").classList.add("error");
}

function validateForm({modelOptional = false} = {}) {
  if (!$("provider-preset").value) {
    profileError("provider_preset", "请先选择 Provider。");
    return null;
  }
  $("provider-preset").removeAttribute("aria-invalid");
  for (const id of Object.values(customFields)) $(id).removeAttribute("aria-invalid");
  $("custom-status").classList.remove("error");
  const values = collectFields();
  for (const [field, id] of Object.entries(customFields)) {
    if (modelOptional && (field === "model" || field === "display_name")) continue;
    const control = $(id);
    if (!control.checkValidity()) {
      const message = field === "secret_env" && values.provider_kind === "cloud"
        ? "Cloud Profile 必须填写 Secret 环境变量名，不能填写真实 Key。"
        : `${field} 为必填项，或当前格式不正确。`;
      profileError(field, message);
      return null;
    }
  }
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(values.provider_id)) {
    profileError("provider_id", "使用小写字母开头的机器标识，可含数字、_ 和 -。");
    return null;
  }
  if (values.secret_env && !/^[A-Z_][A-Z0-9_]{0,127}$/.test(values.secret_env)) {
    profileError("secret_env", "这里只能填写大写环境变量名，不能填写真实 Key。");
    return null;
  }
  return values;
}

async function queryModels() {
  const values = validateForm({modelOptional: true});
  if (!values) return;
  $("models-status").textContent = "正在查询真实服务的模型列表…";
  $("query-models").disabled = true;
  try {
    const response = await fetch("/api/profiles/models", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...values, confirm_network: true}),
    });
    const data = await response.json();
    if (!response.ok) {
      $("models-status").textContent = `查询失败：${data.error_code}。可手动填写 Model ID。`;
      return;
    }
    $("model-options").replaceChildren();
    const first = document.createElement("option");
    first.value = "";
    first.textContent = "选择查询到的模型";
    $("model-options").append(first);
    for (const id of data.models) {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      $("model-options").append(option);
    }
    $("model-options").hidden = data.models.length === 0;
    $("models-status").textContent = `查询成功：${data.models.length} 个模型，${show(data.latency_ms)} ms。高级能力仍为 UNKNOWN。`;
  } catch (_) {
    $("models-status").textContent = "查询失败：NETWORK_ERROR。可手动填写 Model ID。";
  } finally {
    $("query-models").disabled = false;
  }
}

async function testConnection() {
  const values = validateForm();
  if (!values) return;
  const method = $("test-method").value;
  if (method === "chat" && !window.confirm("最小 Chat 会发送一次真实生成请求，可能产生费用。继续？")) return;
  $("test-profile").disabled = true;
  $("test-status").textContent = "正在测试连接…";
  try {
    const response = await fetch("/api/profiles/test", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...values, method, confirm_network: true}),
    });
    const data = await response.json();
    if (!response.ok) {
      invalidateTest();
      $("test-status").textContent = `FAILURE · ${show(data.model || values.model)} · ${show(data.latency_ms)} ms · ${data.error_code}${method === "models" ? "；若服务不支持模型列表，可手动选择最小 Chat 重试（可能收费）。" : ""}`;
      return;
    }
    testId = data.test_id;
    testedFingerprint = connectionFingerprint(values);
    $("test-status").textContent = `SUCCESS · ${data.model} · ${show(data.latency_ms)} ms · ${data.method}。高级能力未验证。`;
  } catch (_) {
    invalidateTest();
    $("test-status").textContent = "FAILURE · NETWORK_ERROR";
  } finally {
    $("test-profile").disabled = false;
  }
}

async function saveCustomProfile(action = "create", targetId = null) {
  const values = validateForm();
  if (!values) return;
  if (values.provider_kind === "cloud" && (!testId || testedFingerprint !== connectionFingerprint(values))) {
    profileError("profile", "Cloud Profile 保存前必须先对当前连接字段完成一次测试。");
    return;
  }
  const button = $("save-profile");
  button.disabled = true;
  $("custom-status").textContent = "正在保存本地 Profile…";
  try {
    const directEdit = editingId && action === "create";
    const url = directEdit ? `/api/profiles/${encodeURIComponent(editingId)}` : "/api/profiles";
    const response = await fetch(url, {
      method: directEdit ? "PUT" : "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...values, test_id: testId, conflict_action: action,
        conflict_profile_id: targetId}),
    });
    const data = await response.json();
    if (response.status === 409) {
      pendingConflict = data.existing;
      $("conflict-panel").hidden = false;
      const canUpdate = data.allowed_actions?.includes("update") === true && data.existing.source === "user_custom";
      $("conflict-message").textContent = `${data.reason === "SAME_ENDPOINT_MODEL" ? "同一 Provider、地址和模型已有配置" : "显示名称已存在"}：${data.existing.display_name}。${canUpdate ? "可更新已有自定义配置、另存为副本或取消。" : "预置配置只读，可另存为自定义副本或取消。"}`;
      $("conflict-update").hidden = !canUpdate;
      return;
    }
    if (!response.ok) {
      profileError(data.field || "profile", data.message || show(data.error_code));
      return;
    }
    editingId = data.profile.profile_id;
    $("save-profile").textContent = "更新 Profile";
    testId = null;
    testedFingerprint = null;
    pendingConflict = null;
    $("conflict-panel").hidden = true;
    await refreshProfiles(data.profile.profile_id);
    $("custom-status").textContent = "已保存。若 Secret 仅写在 .env，请重启 Web 服务后使用。";
  } catch (_) {
    profileError("profile", "页面与本地服务通信失败。");
  } finally {
    button.disabled = false;
  }
}

function renderFacts(observedFacts) {
  const reading = observedFacts?.water_quality || {};
  addPairs("facts", [
    ["水温 (°C)", reading.temperature_c], ["pH", reading.ph],
    ["溶氧 (mg/L)", reading.dissolved_oxygen_mg_l], ["质量", reading.quality],
    ["新鲜度", reading.freshness], ["观测时间", reading.observed_at],
    ["获取时间", reading.retrieved_at], ["数据来源", reading.source],
    ["检测摘要", observedFacts?.detection_summary ? JSON.stringify(observedFacts.detection_summary) : null],
  ]);
}

function renderRules(rules) {
  addList("rules", rules, (li, item) => block(li, `${item.code} · ${item.severity}`, item.message, `规则版本：${item.rule_version}`));
}

function renderEvidence(evidence) {
  addList("evidence", evidence, (li, item) => {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const content = document.createElement("p");
    summary.textContent = `${item.evidence_id} · ${item.category} · ${show(item.score)}`;
    content.textContent = item.text;
    const source = document.createElement("small");
    source.textContent = `来源：${item.source_id}`;
    details.append(summary, content, source);
    li.append(details);
  });
}

function render(data, latency, ttft = null, streaming = false) {
  const runtime = data.runtime || {};
  const usage = data.usage || {};
  const displayedProvider = profiles.find((item) => item.profile_id === runtime.profile_id)?.provider || runtime.provider_id;
  $("model-inference").hidden = false;
  $("streaming-output").hidden = !streaming;
  if (streaming) $("streaming-output").textContent = data.generated_text || $("streaming-output").textContent;
  $("model-inference").textContent = data.inference || (data.error_code ? `模型调用失败：${data.error_code}` : "无模型推断");
  $("model-output").textContent = data.generated_text || (data.error_code ? `模型调用失败：${data.error_code}` : "无模型正文");
  renderFacts(data.observed_facts);
  renderRules(data.rule_results);
  renderEvidence(data.evidence);
  addPairs("structured", [
    ["Inference", data.inference], ["解析成功", data.structured_parse_ok ? "是" : "否"],
    ["状态", data.status], ["错误码", data.error_code], ["Trace ID", data.trace_id],
  ]);
  addList("recommendations", data.recommendations, (li, item) => { li.textContent = item; });
  addList("uncertainty", data.uncertainty, (li, item) => { li.textContent = item; });
  addPairs("runtime", [
    ["Provider", displayedProvider], ["Model", runtime.model],
    ["Profile", runtime.profile_id], ["Profile 状态", runtime.profile_status],
    ["Input Tokens", usage.input_tokens], ["Output Tokens", usage.output_tokens],
    ["Total Tokens", usage.total_tokens], ["Reasoning Tokens", usage.reasoning_tokens],
    ["Cached Tokens", usage.cached_input_tokens], ["Usage Source", usage.source],
    ["TTFT (ms)", ttft],
    ["总耗时 (ms)", latency],
  ]);
  $("empty-state").hidden = true;
  $("results").hidden = false;
}

function prepareStreamView() {
  $("empty-state").hidden = true;
  $("results").hidden = false;
  $("model-inference").hidden = true;
  $("streaming-output").hidden = false;
  $("streaming-output").textContent = "";
  $("model-output").textContent = "";
  for (const id of ["facts", "rules", "evidence", "structured", "recommendations", "uncertainty", "runtime"]) {
    $(id).replaceChildren();
  }
}

async function analyzeStreaming(body) {
  try {
    prepareStreamView();
  } catch (_) {
    setStatus("流式页面显示失败：STREAM_DISPLAY_ERROR", true);
    return;
  }
  const response = await fetch("/api/analyze/stream", {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    setStatus(`请求未执行：${data.error_code || `HTTP_${response.status}`}`, true);
    return;
  }
  if (!response.body) {
    setStatus("流式响应不可用：STREAM_UNAVAILABLE", true);
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let terminal = false;
  let runtime = {};
  let liveUsage = {};
  while (true) {
    let done, value;
    try {
      ({done, value} = await reader.read());
    } catch (_) {
      setStatus("流式连接中断：STREAM_INTERRUPTED", true);
      return;
    }
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    buffer = buffer.replace(/\r\n/g, "\n");
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const kind = frame.split("\n").find((line) => line.startsWith("event: "))?.slice(7);
      const dataLine = frame.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
      if (!kind || !dataLine) continue;
      let data;
      try {
        data = JSON.parse(dataLine);
      } catch (_) {
        setStatus("流式事件格式错误：STREAM_PROTOCOL_ERROR", true);
        return;
      }
      try {
      if (kind === "analysis_started") setStatus("分析已开始，正在准备事实和证据…");
      if (kind === "facts_ready") {
        runtime = data.runtime || {};
        renderFacts(data.observed_facts);
        setStatus("事实已就绪，正在计算规则…");
      }
      if (kind === "rules_ready") renderRules(data.rule_results);
      if (kind === "evidence_ready") {
        renderEvidence(data.evidence);
        setStatus("事实、规则与证据已就绪，等待模型输出…");
      }
      if (kind === "content_delta") $("streaming-output").textContent += data.delta || "";
      if (kind === "usage") {
        liveUsage = data.usage || {};
        addPairs("runtime", [["Provider", runtime.provider_id], ["Model", runtime.model],
          ["Input Tokens", liveUsage.input_tokens], ["Output Tokens", liveUsage.output_tokens],
          ["Total Tokens", liveUsage.total_tokens], ["Usage Source", liveUsage.source]]);
      }
      if (kind === "completed" || kind === "failed") {
        terminal = true;
        if (data.result) render(data.result, data.total_latency_ms, data.ttft_ms, true);
        setStatus(kind === "completed" ? "流式分析完成。" : `流式分析失败：${show(data.error_code)}`, kind === "failed");
      }
      } catch (_) {
        setStatus("流式页面显示失败：STREAM_DISPLAY_ERROR", true);
        return;
      }
    }
    if (done) break;
  }
  if (!terminal) setStatus("流式连接中断：STREAM_INTERRUPTED", true);
}

async function analyze() {
  const profile = selectedProfile();
  if (!profile) return;
  const real = profile.runtime_type !== "mock";
  if (real && !$("confirm-network").checked) {
    setStatus("请先确认 REAL NETWORK REQUEST。", true);
    return;
  }
  $("analyze").disabled = true;
  const streaming = $("response-mode").value === "streaming";
  setStatus(real ? "正在等待真实模型…" : "正在执行离线 Mock 分析…");
  try {
    const body = {
      profile_id: profile.profile_id,
      scenario: $("scenario").value,
      question: $("question").value,
      confirm_network: real && $("confirm-network").checked,
    };
    if (streaming) {
      await analyzeStreaming(body);
      return;
    }
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (payload.result) {
      render(payload.result, payload.total_latency_ms);
      setStatus(payload.result.status === "completed" ? "分析完成。" : `分析失败：${show(payload.result.error_code)}`, payload.result.status !== "completed");
    } else {
      setStatus(`请求未执行：${show(payload.error_code)}`, true);
    }
  } catch (_) {
    setStatus("页面请求失败：NETWORK_ERROR", true);
  } finally {
    $("analyze").disabled = false;
    if (real) $("confirm-network").checked = false;
  }
}

async function init() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("config");
    const config = await response.json();
    profiles = config.profiles;
    presets = config.presets;
    renderProfiles();
    for (const preset of presets) {
      const option = document.createElement("option");
      option.value = preset.id;
      option.textContent = preset.label;
      $("provider-preset").append(option);
    }
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "请选择 Provider";
    $("provider-preset").prepend(placeholder);
    newProfile();
    for (const scenario of config.scenarios) {
      const option = document.createElement("option");
      option.value = scenario;
      option.textContent = scenario;
      $("scenario").append(option);
    }
    $("scenario").value = "low_oxygen";
    $("profile").addEventListener("change", updateProfile);
    $("analyze").addEventListener("click", analyze);
    $("provider-preset").addEventListener("change", selectPreset);
    $("new-profile").addEventListener("click", newProfile);
    $("edit-profile").addEventListener("click", editSelected);
    $("delete-profile").addEventListener("click", deleteSelected);
    $("query-models").addEventListener("click", queryModels);
    $("model-options").addEventListener("change", () => { if ($("model-options").value) $("custom-model").value = $("model-options").value; invalidateTest(); });
    $("test-profile").addEventListener("click", testConnection);
    $("save-profile").addEventListener("click", () => saveCustomProfile());
    $("conflict-update").addEventListener("click", () => { if (pendingConflict) saveCustomProfile("update", pendingConflict.profile_id); });
    $("conflict-copy").addEventListener("click", () => saveCustomProfile("copy"));
    $("conflict-cancel").addEventListener("click", () => { pendingConflict = null; $("conflict-panel").hidden = true; });
    $("custom-deployment").addEventListener("change", updateSecretRequirement);
    for (const field of ("custom-provider", "custom-adapter", "custom-url", "custom-model", "custom-secret-env", "custom-deployment")) {
      $(field).addEventListener("input", invalidateTest);
    }
    $("custom-secret-env").addEventListener("change", () => showSecret($("custom-secret-env").value.trim(), "secret-status"));
    updateSecretRequirement();
  } catch (_) {
    setStatus("页面配置加载失败：CONFIG_ERROR", true);
  }
}

init();
