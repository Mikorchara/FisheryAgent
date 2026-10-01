const $ = (id) => document.getElementById(id);
let profiles = [];
let presets = [];
let editingId = null;
let testId = null;
let testedFingerprint = null;
let formMode = "view";
let formRevision = 0;
let probeInProgress = false;

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

function capabilityStatus(profile, name) {
  const capabilities = profile?.capabilities || {};
  const item = name === "reasoning_on" ? capabilities.thinking_on
    : name === "reasoning_off" ? capabilities.thinking_off
      : name === "reasoning_effort" ? capabilities.reasoning_effort
        : name === "thinking_streaming_combination" ? capabilities.thinking_streaming_combination : null;
  const status = (name === "streaming" ? capabilities.streaming : item?.status)?.toLowerCase();
  return ["supported", "unsupported", "unknown"].includes(status) ? status : "unknown";
}

function statusSuffix(status) {
  return status === "supported" ? "" : status === "unsupported" ? "（不支持）" : "（未验证）";
}

function appendChoice(target, value, label, disabled = false) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  item.disabled = disabled;
  target.append(item);
}

function resolveRuntimeDefaults(profile) {
  const notices = [];
  let thinking = profile.stored_default_thinking_mode || profile.default_reasoning_mode || "auto";
  let response = profile.stored_default_response_mode || profile.default_response_mode || "normal";
  if (thinking === "on" || thinking === "off") {
    const status = capabilityStatus(profile, thinking === "on" ? "reasoning_on" : "reasoning_off");
    if (status !== "supported") {
      notices.push(`默认 Thinking ${thinking.toUpperCase()} 当前${status === "unknown" ? "未验证" : "不支持"}，已回退为 AUTO。`);
      thinking = "auto";
    }
  }
  if (response === "streaming" && capabilityStatus(profile, "streaming") !== "supported") {
    const status = capabilityStatus(profile, "streaming");
    notices.push(`默认 Streaming 当前${status === "unknown" ? "未验证" : "不支持"}，已回退为 Normal。`);
    response = "normal";
  }
  const effectiveOn = thinking === "on" || (thinking === "auto" && profile.capabilities?.thinking_default === true);
  if (response === "streaming" && effectiveOn && capabilityStatus(profile, "thinking_streaming_combination") !== "supported") {
    notices.push("默认 Streaming + Thinking 组合未验证或不支持，已临时回退为 Normal；原偏好保留。");
    response = "normal";
  }
  return {thinking, response, notices};
}

function updateRuntimeOptionControls(profile, preferred = {}) {
  const thinkingSelect = $("reasoning-mode");
  const responseSelect = $("response-mode");
  const effortSelect = $("reasoning-effort");
  const requestedThinking = preferred.reasoning ?? thinkingSelect.value ?? "auto";
  const requestedResponse = preferred.response ?? responseSelect.value ?? "normal";
  const requestedEffort = preferred.effort ?? effortSelect.value ?? "";
  const onStatus = capabilityStatus(profile, "reasoning_on");
  const offStatus = capabilityStatus(profile, "reasoning_off");
  const streamingStatus = capabilityStatus(profile, "streaming");
  const effortStatus = capabilityStatus(profile, "reasoning_effort");

  thinkingSelect.replaceChildren();
  appendChoice(thinkingSelect, "auto", "AUTO（不发送参数）");
  appendChoice(thinkingSelect, "on", `ON${statusSuffix(onStatus)}`, onStatus !== "supported");
  appendChoice(thinkingSelect, "off", `OFF${statusSuffix(offStatus)}`, offStatus !== "supported");
  thinkingSelect.value = requestedThinking === "on" && onStatus === "supported"
    || requestedThinking === "off" && offStatus === "supported" ? requestedThinking : "auto";

  const effectiveOn = thinkingSelect.value === "on"
    || (thinkingSelect.value === "auto" && profile?.capabilities?.thinking_default === true);
  const combinationStatus = capabilityStatus(profile, "thinking_streaming_combination");
  const responseStatus = effectiveOn && combinationStatus !== "supported" ? combinationStatus : streamingStatus;
  responseSelect.replaceChildren();
  appendChoice(responseSelect, "normal", "Normal（不启用 Streaming）");
  appendChoice(responseSelect, "streaming", `Streaming${statusSuffix(responseStatus)}${effectiveOn && combinationStatus !== "supported" ? "（Thinking 组合待验证）" : ""}`,
    streamingStatus !== "supported" || (effectiveOn && combinationStatus !== "supported"));
  responseSelect.value = requestedResponse === "streaming" && streamingStatus === "supported" && (!effectiveOn || combinationStatus === "supported")
    ? "streaming" : "normal";

  effortSelect.replaceChildren();
  appendChoice(effortSelect, "", "UNSET（不发送参数）");
  const effortValues = profile?.capabilities?.effort_values || [];
  if (effortStatus !== "supported") {
    appendChoice(effortSelect, `__${effortStatus}__`, `Reasoning Effort${statusSuffix(effortStatus)}`, true);
  } else if (!effortValues.length) {
    appendChoice(effortSelect, "__values_unknown__", "Reasoning Effort（未提供可选值）", true);
  } else {
    for (const value of effortValues) {
      const thinkingOn = onStatus === "supported" && thinkingSelect.value === "on";
      const dependency = onStatus !== "supported"
        ? `（Thinking ON ${statusSuffix(onStatus).slice(1, -1)}）`
        : thinkingSelect.value === "on" ? "" : "（选择 Thinking ON 后可选）";
      appendChoice(effortSelect, value, `${value}${dependency}`, !thinkingOn);
    }
  }
  effortSelect.value = effortStatus === "supported" && onStatus === "supported"
      && thinkingSelect.value === "on" && effortValues.includes(requestedEffort)
    ? requestedEffort : "";
  $("effort-control").hidden = false;
}

function syncRuntimeOptionsFromCurrentSelections() {
  const profile = selectedProfile();
  if (!profile) return;
  updateRuntimeOptionControls(profile, {reasoning: $("reasoning-mode").value,
    response: $("response-mode").value, effort: $("reasoning-effort").value});
}

function updateProfile() {
  const profile = selectedProfile();
  if (!profile) return;
  const defaults = resolveRuntimeDefaults(profile);
  updateRuntimeOptionControls(profile, {reasoning: defaults.thinking, response: defaults.response,
    effort: ""});
  $("runtime-default-notice").textContent = defaults.notices.length
    ? defaults.notices.join(" ") : "当前运行选项已按此 Profile 的默认偏好恢复。";
  const revision = ++formRevision;
  editingId = null;
  setFormMode("view");
  // Clear the previous selection while the new profile details are loading.
  $("provider-preset").value = "";
  for (const id of Object.values(customFields)) $(id).value = "";
  $("secret-status").textContent = "";
  invalidateTest();
  $("profile-meta").textContent = `${profile.service_id || profile.provider} · ${profile.model_family || "unknown"} · ${profile.model} · ${profile.profile_status.toUpperCase()} · ${profile.runtime_type} · ${profile.source === "user_custom" ? "用户自定义" : "预置"}`;
  addPairs("profile-summary", [["Service", profile.service_id || profile.provider],
    ["Base URL", profile.base_url], ["Model ID", profile.model],
    ["Deployment", profile.runtime_type]]);
  const streaming = profile.capabilities?.streaming || "unknown";
  const capabilitySource = profile.capabilities?.source || "UNKNOWN";
  const capabilityLabel = streaming === "supported" && capabilitySource === "OFFICIAL_DOCS"
    ? "官方文档支持" : streaming === "supported" && capabilitySource === "USER_VERIFIED"
      ? "本机已验证" : streaming === "unsupported" ? "不支持" : "未验证";
  const scope = profile.capabilities?.streaming_scope_matches === true
    ? "已绑定当前 service / adapter / Base URL / Model" : "未绑定当前精确连接";
  $("streaming-capability").textContent = `Streaming 能力：${capabilityLabel}（${streaming.toUpperCase()}）· ${scope}`;
  renderCapabilities(profile);
  const live = profile.runtime_type !== "mock";
  const streamingSource = profile.capabilities?.source || "UNKNOWN";
  $("probe-streaming").hidden = !live || streamingSource === "USER_VERIFIED";
  $("reprobe-streaming").hidden = !live || streamingSource !== "USER_VERIFIED";
  $("refresh-metadata").hidden = profile.service_id !== "ollama"
    || profile.runtime_type !== "local" || profile.model !== "qwen3.5:4b";
  const thinkingAvailable = profile.thinking_probe_available === true;
  const onVerified = profile.capabilities?.thinking_on?.source === "USER_VERIFIED";
  const offVerified = profile.capabilities?.thinking_off?.source === "USER_VERIFIED";
  $("probe-thinking-on").hidden = onVerified;
  $("probe-thinking-off").hidden = offVerified;
  $("probe-thinking-on").disabled = !thinkingAvailable;
  $("probe-thinking-off").disabled = !thinkingAvailable;
  $("thinking-probe-actions").hidden = !live || (onVerified && offVerified);
  $("thinking-probe-help").textContent = thinkingAvailable
    ? "显式验证 ON / OFF：每次最多一个真实请求，retry=0。"
    : "当前 Adapter 没有此精确服务/模型的 Thinking 参数映射，无法安全 Probe；Normal + AUTO 仍可运行。";
  $("reprobe-thinking-on").hidden = !onVerified;
  $("reprobe-thinking-off").hidden = !offVerified;
  $("thinking-reverify-actions").hidden = !live || (!onVerified && !offVerified);
  const combinationReady = thinkingAvailable && streaming === "supported"
    && profile.capabilities?.thinking_on?.status === "supported";
  const combinationVerified = profile.capabilities?.thinking_streaming_combination?.source === "USER_VERIFIED";
  $("probe-combination").hidden = !combinationReady || combinationVerified;
  $("reprobe-combination").hidden = !combinationReady || !combinationVerified;
  $("advanced-capability-actions").hidden = !live;
  $("advanced-capability-actions").open = false;
  $("metadata-status").textContent = "";
  $("thinking-probe-status").textContent = "";
  $("capability-probe-status").textContent = "";
  const real = profile.runtime_type !== "mock";
  $("real-warning").hidden = !real;
  $("confirm-network").checked = false;
  setStatus(real ? "此 Profile 会发起真实模型请求，请先确认。" : "Mock 模式始终离线。", false);
  $("edit-profile").hidden = profile.source !== "user_custom";
  $("delete-profile").hidden = profile.source !== "user_custom";
  $("custom-editor").open = false;
  $("custom-status").textContent = "正在读取所选配置…";
  $("selected-secret-status").textContent = real ? "Secret 状态：待检查" : "Mock 无需 Secret";
  fetch(`/api/profiles/${encodeURIComponent(profile.profile_id)}`)
    .then((response) => { if (!response.ok) throw new Error("PROFILE_READ_FAILED"); return response.json(); })
    .then((data) => {
      if (revision !== formRevision || $("profile").value !== profile.profile_id) return;
      fillProfileForm(data.fields, profile);
      $("custom-status").textContent = data.editable
        ? "正在查看自定义配置；点击“编辑所选”可修改连接参数，名称不可修改。"
        : "预置配置只读；如需新配置，请点击“新建”。";
      const current = () => revision === formRevision && $("profile").value === profile.profile_id;
      showSecret(data.fields.secret_env, "secret-status", current);
      if (real) showSecret(data.fields.secret_env, "selected-secret-status", current);
    })
    .catch(() => {
      if (revision === formRevision) $("custom-status").textContent = "读取所选配置失败：PROFILE_READ_FAILED";
    });
}

function capabilityText(item) {
  const status = item?.status || "unknown";
  const source = item?.source || "UNKNOWN";
  if (status === "unknown") return "未验证（UNKNOWN）";
  const label = source === "MODEL_METADATA" ? "模型 metadata"
    : source === "USER_VERIFIED" ? "本机已验证"
      : source === "OFFICIAL_DOCS" ? "官方文档" : "来源未知";
  const sources = item?.sources?.length ? item.sources.join(" + ") : source;
  return `${status === "supported" ? "支持" : "不支持"}（${status.toUpperCase()}）· ${label} · ${sources}`;
}

function renderCapabilities(profile) {
  const caps = profile.capabilities || {};
  const on = caps.thinking_on || {};
  const off = caps.thinking_off || {};
  const thinking = `ON: ${capabilityText(on)} / OFF: ${capabilityText(off)}`;
  const streaming = caps.streaming_evidence || {status: caps.streaming, source: caps.source};
  const modes = ["AUTO"];
  if (on.status === "supported") modes.push("ON");
  if (off.status === "supported") modes.push("OFF");
  addPairs("capability-list", [
    ["Streaming", capabilityText(streaming)],
    ["Thinking ON", capabilityText(on)],
    ["Thinking OFF", capabilityText(off)],
    ["Streaming + Thinking ON", capabilityText(caps.thinking_streaming_combination)],
    ["Thinking Metadata / 支持值", `${modes.join(" / ")} · ON ${on.source || "UNKNOWN"} / OFF ${off.source || "UNKNOWN"}`],
    ["模型默认 Thinking", caps.thinking_default === null || caps.thinking_default === undefined
      ? "未知" : `${caps.thinking_default ? "ON" : "OFF"} · ${(caps.thinking_default_sources || []).join(" + ") || "UNKNOWN"}`],
    ["Reasoning Effort", capabilityText(caps.reasoning_effort)],
    ["Structured Output", capabilityText(caps.structured_output)],
    ["Tool Calling", capabilityText(caps.tool_calling)],
  ]);
  const modelDefault = caps.thinking_default === true ? "ON" : caps.thinking_default === false ? "OFF" : "未知";
  $("thinking-hint").textContent = `模型默认 ${modelDefault}；AUTO 不发送控制参数。显式 ON / OFF 独立校验，Effort 不等于 ON。`;
}

const customFields = {
  display_name: "custom-name", service_id: "custom-provider", model_family: "custom-family",
  adapter_id: "custom-adapter", base_url: "custom-url", model: "custom-model",
  secret_env: "custom-secret-env", provider_kind: "custom-deployment",
  default_thinking_mode: "custom-default-thinking",
  default_response_mode: "custom-default-response",
};

function setFormMode(mode) {
  formMode = mode;
  const editable = mode !== "view";
  $("provider-preset").disabled = !editable;
  for (const id of Object.values(customFields)) $(id).disabled = !editable;
  $("custom-name").readOnly = mode === "edit";
  $("model-options").disabled = !editable;
  $("test-method").disabled = !editable;
  for (const id of ["query-models", "test-profile", "save-profile"]) $(id).hidden = !editable;
  $("save-profile").textContent = mode === "edit" ? "保存连接修改" : "创建 Profile";
}

function fillProfileForm(fields, profile) {
  $("provider-preset").value = profile.runtime_type === "mock" ? "built_in_mock"
    : presets.some((preset) => preset.id === fields.service_id) ? fields.service_id : "custom";
  for (const [field, id] of Object.entries(customFields)) {
    const fallback = field === "default_thinking_mode" ? "auto"
      : field === "default_response_mode" ? "normal" : "";
    $(id).value = fields[field] || fallback;
  }
  $("model-options").hidden = true;
  $("models-status").textContent = "";
  $("advanced-settings").open = false;
  updateSecretRequirement();
}

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
  return JSON.stringify([fields.service_id, fields.model_family, fields.adapter_id, fields.base_url, fields.model,
    fields.secret_env, fields.provider_kind]);
}

function invalidateTest() {
  testId = null;
  testedFingerprint = null;
  $("test-status").textContent = "连接字段已改变；Cloud 保存前需重新测试。";
  if (formMode !== "view") {
    renderCapabilities({capabilities: {}, default_reasoning_mode: "auto"});
    $("streaming-capability").textContent = "当前表单的模型身份已改变；高级能力待重新加载（UNKNOWN）。";
    updateRuntimeOptionControls({capabilities: {}}, {reasoning: "auto", response: "normal", effort: ""});
    $("runtime-default-notice").textContent = "连接身份已改变；本次运行选项已回退为 AUTO + Normal，旧 Capability 不再适用。";
    $("thinking-probe-actions").hidden = true;
    $("thinking-reverify-actions").hidden = true;
    $("probe-thinking-on").hidden = true;
    $("probe-thinking-off").hidden = true;
    $("reprobe-thinking-on").hidden = true;
    $("reprobe-thinking-off").hidden = true;
    $("probe-streaming").hidden = true;
    $("reprobe-streaming").hidden = true;
    $("refresh-metadata").hidden = true;
    $("advanced-capability-actions").hidden = true;
    $("probe-combination").hidden = true;
    $("reprobe-combination").hidden = true;
  }
}

async function showSecret(name, targetId, isCurrent = () => true) {
  const target = $(targetId);
  if (!name) {
    if (isCurrent()) target.textContent = "Secret：未配置（Local 可不需要）";
    return;
  }
  try {
    const response = await fetch("/api/secret-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({secret_env: name}),
    });
    const data = await response.json();
    if (isCurrent()) target.textContent = `${name}: ${response.ok ? data.status : "MISSING"}`;
  } catch (_) {
    if (isCurrent()) target.textContent = `${name}: 状态不可用`;
  }
}

function selectPreset() {
  if (formMode === "view") return;
  const preset = presets.find((item) => item.id === $("provider-preset").value);
  if (!preset) return;
  $("custom-provider").value = preset.service_id;
  $("custom-family").value = preset.model_family || "unknown";
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
  ++formRevision;
  editingId = null;
  setFormMode("new");
  $("custom-name").value = "";
  $("provider-preset").value = "";
  $("custom-provider").value = "";
  $("custom-family").value = "";
  $("custom-adapter").value = "openai_chat";
  $("custom-url").value = "";
  $("custom-model").value = "";
  $("custom-secret-env").value = "";
  $("custom-deployment").value = "cloud";
  $("custom-default-thinking").value = "auto";
  $("custom-default-response").value = "normal";
  $("model-options").hidden = true;
  $("advanced-settings").open = false;
  $("models-status").textContent = "";
  $("custom-editor").open = true;
  showSecret("", "secret-status");
  updateSecretRequirement();
  invalidateTest();
  $("custom-status").textContent = "新配置尚未保存。";
}

async function editSelected() {
  const selected = selectedProfile();
  if (!selected || selected.source !== "user_custom") return;
  const revision = ++formRevision;
  let data;
  try {
    const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}`);
    if (!response.ok) throw new Error("PROFILE_READ_FAILED");
    data = await response.json();
  } catch (_) {
    return profileError("profile", "无法读取所选配置。");
  }
  if (revision !== formRevision || $("profile").value !== selected.profile_id) return;
  editingId = selected.profile_id;
  fillProfileForm(data.fields, selected);
  setFormMode("edit");
  showSecret(data.fields.secret_env, "secret-status");
  invalidateTest();
  $("custom-editor").open = true;
  $("custom-status").textContent = "可修改连接参数；Display Name 创建后不可修改。Cloud 修改保存前需重新测试。";
}

async function deleteSelected() {
  const selected = selectedProfile();
  if (!selected || selected.source !== "user_custom") return;
  if (!window.confirm(`删除 ${selected.display_name}？配置会移入本地 archive，可手工恢复。`)) return;
  const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}`, {method: "DELETE"});
  const data = await response.json();
  if (!response.ok) return profileError("profile", data.error_code || "删除失败");
  await refreshProfiles("mock-demo");
  $("custom-status").textContent = "配置已从列表移除，原文件保存在本地 archive。";
}

async function refreshProfiles(selectedId) {
  const initialSelection = $("profile").value;
  const response = await fetch("/api/config");
  if (!response.ok) throw new Error("PROFILE_REFRESH_FAILED");
  const data = await response.json();
  if (!data || !Array.isArray(data.profiles)) throw new Error("PROFILE_REFRESH_FAILED");
  profiles = data.profiles;
  const current = $("profile").value;
  renderProfiles(current !== initialSelection ? current : selectedId);
}

async function probeSelectedCapability(reverify = false) {
  return runExplicitProbe("streaming", null, reverify === true);
}

async function runExplicitProbe(capability, mode = null, reverify = false) {
  if (probeInProgress) {
    $("capability-probe-status").textContent = "已有能力验证正在执行，请等待完成后再验证。";
    return;
  }
  const selected = selectedProfile();
  const status = $(capability === "streaming" ? "capability-probe-status" : "thinking-probe-status");
  const label = capability === "streaming" ? "Streaming"
    : capability === "thinking_streaming_combination" ? "Streaming + Thinking ON" : `Thinking ${mode.toUpperCase()}`;
  if (!selected || selected.runtime_type === "mock") {
    status.textContent = "验证失败：PROFILE_NOT_FOUND 或 Mock 无需真实验证。";
    return;
  }
  const prefix = reverify ? "reprobe" : "probe";
  const button = $(`${prefix}-${capability === "streaming" ? "streaming" : capability === "thinking_streaming_combination" ? "combination" : `thinking-${mode}`}`);
  let stage = "confirmation";
  probeInProgress = true;
  button.disabled = true;
  status.textContent = `正在验证 ${label}...`;
  try {
    if (!window.confirm(`REAL NETWORK REQUEST：验证 ${label}，仅一次最小生成请求，Cloud 可能收费，retry=0。继续吗？`)) {
      status.textContent = "已取消；未发送请求。";
      return;
    }
    const endpoint = mode ? "thinking-probe" : "probe";
    const body = mode ? {mode, confirm_network: true, reverify}
      : {capability, confirm_network: true, reverify};
    stage = "request";
    const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}/${endpoint}`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
    });
    stage = "response";
    const data = await response.json();
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("INVALID_RESPONSE");
    const safeCode = typeof data.error_code === "string" && /^[A-Z][A-Z0-9_]{0,40}$/.test(data.error_code)
      ? data.error_code : `HTTP_${response.status || "ERROR"}`;
    if (!response.ok || !["success", "unsupported"].includes(data.status)) {
      const timeout = ["CONNECT_TIMEOUT", "READ_TIMEOUT", "TIMEOUT", "TOTAL_TIMEOUT"].includes(safeCode);
      status.textContent = `${timeout ? "验证超时" : "验证失败"}：${safeCode}；未新增能力结论。`;
      return;
    }
    if (!data.capability) throw new Error("INVALID_RESPONSE");
    stage = "refresh";
    const currentId = $("profile").value;
    await refreshProfiles(currentId);
    if ($("profile").value !== selected.profile_id) return;
    const metrics = `delta=${show(data.delta_count)}，TTFT=${show(data.ttft_ms)} ms，总耗时=${show(data.latency_ms)} ms；Usage=${JSON.stringify(data.usage || {})}`;
    status.textContent = data.status === "success"
      ? `${label} 验证成功（本机已验证）· SUPPORTED · USER_VERIFIED；${metrics}`
      : `${label} 验证失败：${safeCode}；UNSUPPORTED · USER_VERIFIED；${metrics}`;
  } catch (exc) {
    const code = stage === "request" ? (exc?.name === "AbortError" ? "TIMEOUT" : "NETWORK_ERROR")
      : stage === "response" ? "INVALID_RESPONSE" : stage === "refresh" ? "PROFILE_REFRESH_FAILED" : "PROBE_UI_ERROR";
    status.textContent = `验证失败：${code}${stage === "refresh" ? "；结果已保存，但页面刷新失败。" : "；未新增能力结论。"}`;
  } finally {
    probeInProgress = false;
    button.disabled = mode ? selectedProfile()?.thinking_probe_available !== true : false;
  }
}

async function refreshMetadata() {
  const selected = selectedProfile();
  if (!selected || selected.service_id !== "ollama") return;
  if (!window.confirm("这会向所选本地 Ollama 服务查询当前模型 metadata。继续吗？")) return;
  const button = $("refresh-metadata");
  button.disabled = true;
  $("metadata-status").textContent = "正在读取模型 metadata…";
  try {
    const response = await fetch(`/api/profiles/${encodeURIComponent(selected.profile_id)}/metadata`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({confirm_network: true}),
    });
    const data = await response.json();
    if (!response.ok) {
      $("metadata-status").textContent = `查询失败：${data.error_code || `HTTP_${response.status}`}`;
      return;
    }
    await refreshProfiles(selected.profile_id);
    $("metadata-status").textContent = "已读取并保存精确模型的 Thinking metadata。";
  } catch (_) {
    $("metadata-status").textContent = "查询失败：NETWORK_ERROR";
  } finally {
    button.disabled = false;
  }
}

async function probeThinking(mode, reverify = false) {
  if (!["on", "off"].includes(mode)) return;
  return runExplicitProbe(`reasoning_${mode}`, mode, reverify === true);
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
  if (formMode === "view") return null;
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
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(values.service_id)) {
    profileError("service_id", "使用小写字母开头的机器标识，可含数字、_ 和 -。");
    return null;
  }
  if (!values.model_family) values.model_family = "unknown";
  if (!["qwen", "deepseek", "unknown"].includes(values.model_family)) {
    profileError("model_family", "请选择 qwen、deepseek 或 unknown。");
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

async function saveCustomProfile() {
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
    const directEdit = editingId !== null;
    const url = directEdit ? `/api/profiles/${encodeURIComponent(editingId)}` : "/api/profiles";
    const response = await fetch(url, {
      method: directEdit ? "PUT" : "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...values, test_id: testId}),
    });
    const data = await response.json();
    if (!response.ok) {
      profileError(data.error_code === "PROFILE_NAME_EXISTS" || data.error_code === "PROFILE_NAME_IMMUTABLE"
        ? "display_name" : data.field || "profile",
      data.error_code === "PROFILE_NAME_EXISTS" ? "PROFILE_NAME_EXISTS：名称已被使用，请另取一个名称。"
        : data.error_code === "PROFILE_NAME_IMMUTABLE" ? "PROFILE_NAME_IMMUTABLE：如需改名，请删除后重新创建。"
          : data.message || show(data.error_code));
      return;
    }
    testId = null;
    testedFingerprint = null;
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
  $("reasoning-output").textContent = data.reasoning_content || "unavailable";
  $("reasoning-debug").open = false;
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
    ["Service ID", runtime.service_id || displayedProvider], ["Model family", runtime.model_family],
    ["Legacy provider_id", runtime.provider_id], ["Model", runtime.model],
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
  $("reasoning-output").textContent = "";
  $("reasoning-debug").open = false;
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
      if (kind === "reasoning_delta") $("reasoning-output").textContent += data.delta || "";
      if (kind === "content_delta") $("streaming-output").textContent += data.delta || "";
      if (kind === "usage") {
        liveUsage = data.usage || {};
        addPairs("runtime", [["Service ID", runtime.service_id], ["Model family", runtime.model_family],
          ["Legacy provider_id", runtime.provider_id], ["Model", runtime.model],
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
    if ($("reasoning-mode").value !== "auto" || (profile.default_reasoning_mode || "auto") !== "auto")
      body.reasoning_mode = $("reasoning-mode").value;
    if (!$("effort-control").hidden && $("reasoning-effort").value)
      body.reasoning_effort = $("reasoning-effort").value;
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
    const mock = document.createElement("option");
    mock.value = "built_in_mock";
    mock.textContent = "Mock（预置，只读）";
    mock.disabled = true;
    $("provider-preset").append(mock);
    renderProfiles();
    for (const scenario of config.scenarios) {
      const option = document.createElement("option");
      option.value = scenario;
      option.textContent = scenario;
      $("scenario").append(option);
    }
    $("scenario").value = "low_oxygen";
    $("profile").addEventListener("change", updateProfile);
    $("reasoning-mode").addEventListener("change", syncRuntimeOptionsFromCurrentSelections);
    $("response-mode").addEventListener("change", syncRuntimeOptionsFromCurrentSelections);
    $("analyze").addEventListener("click", analyze);
    $("provider-preset").addEventListener("change", selectPreset);
    $("new-profile").addEventListener("click", newProfile);
    $("edit-profile").addEventListener("click", editSelected);
    $("delete-profile").addEventListener("click", deleteSelected);
    $("probe-streaming").addEventListener("click", () => probeSelectedCapability(false));
    $("probe-combination").addEventListener("click", () => runExplicitProbe("thinking_streaming_combination"));
    $("reprobe-combination").addEventListener("click", () => runExplicitProbe("thinking_streaming_combination", null, true));
    $("reprobe-streaming").addEventListener("click", () => probeSelectedCapability(true));
    $("refresh-metadata").addEventListener("click", refreshMetadata);
    $("probe-thinking-on").addEventListener("click", () => probeThinking("on"));
    $("probe-thinking-off").addEventListener("click", () => probeThinking("off"));
    $("reprobe-thinking-on").addEventListener("click", () => probeThinking("on", true));
    $("reprobe-thinking-off").addEventListener("click", () => probeThinking("off", true));
    $("query-models").addEventListener("click", queryModels);
    $("model-options").addEventListener("change", () => { if ($("model-options").value) $("custom-model").value = $("model-options").value; invalidateTest(); });
    $("test-profile").addEventListener("click", testConnection);
    $("save-profile").addEventListener("click", saveCustomProfile);
    $("custom-deployment").addEventListener("change", updateSecretRequirement);
    for (const field of ["custom-provider", "custom-adapter", "custom-url", "custom-model", "custom-secret-env", "custom-deployment"]) {
      $(field).addEventListener("input", invalidateTest);
    }
    $("custom-secret-env").addEventListener("change", () => showSecret($("custom-secret-env").value.trim(), "secret-status"));
    updateSecretRequirement();
  } catch (_) {
    setStatus("页面配置加载失败：CONFIG_ERROR", true);
  }
}

init();
