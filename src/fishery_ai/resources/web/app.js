const $ = (id) => document.getElementById(id);
let profiles = [];
let presets = [];
let editingId = null;
let testId = null;
let testedFingerprint = null;
let formMode = "view";
let formRevision = 0;
let probeInProgress = false;
let credentialState = null;
let credentialRevision = 0;
let credentialBusy = false;
let credentialEpoch = 0;
let credentialCsrf = null;
let activeExecution = null;
let accessMode = "";
let manualTargetId = null;

function setAccessMode(mode, selectedId) {
  if (activeExecution) return;
  accessMode = mode;
  $("access-mode").value = mode;
  renderProfiles(selectedId ?? (mode === "manual_expert" ? manualTargetId : undefined));
}

function developmentProfiles() {
  return profiles.filter(item => item.runtime_type === "mock"
    || (item.source === "built_in" && item.runtime_type === "local"));
}

function modelLabel(profile) {
  return profile.display_name.split(" · ")[0].replace(/^Preset\s+/, "");
}

function visibleProfiles() {
  if (accessMode === "managed_custom") return profiles.filter(item => item.source === "user_custom");
  if (accessMode === "development") return developmentProfiles();
  const seen = new Set();
  return profiles.filter(item => {
    if (accessMode === "preset") {
      if (item.source !== "preset" || seen.has(item.preset_id)) return false;
      seen.add(item.preset_id);
      return true;
    }
    // Manual selects saved targets, not a Manual Profile; do not repeat Variant connections.
    if (item.runtime_type === "mock" || (item.source === "built_in" && item.runtime_type !== "local")) return false;
    // Only coalesce Variants of one Preset. Custom connections may use different
    // credentials / timeouts even when their endpoint and model are identical.
    if (item.source === "preset") {
      if (seen.has(item.preset_id)) return false;
      seen.add(item.preset_id);
    }
    return true;
  });
}

function renderPresetVariants(selectedId) {
  const model = profiles.find(item => item.profile_id === $("profile").value);
  const variants = model?.source === "preset"
    ? profiles.filter(item => item.source === "preset" && item.preset_id === model.preset_id) : [];
  $("preset-variant").replaceChildren();
  for (const variant of variants) appendChoice($("preset-variant"), variant.profile_id,
    variant.preset_variant === "auto" ? "Provider Default (AUTO)" : `Thinking ${variant.preset_variant.toUpperCase()}`);
  $("preset-variant").value = variants.some(item => item.profile_id === selectedId) ? selectedId
    : (variants.find(item => item.preset_variant === "auto") || variants[0])?.profile_id || "";
  $("preset-variant").disabled = variants.length <= 1;
}

function updateModeView() {
  const manual = accessMode === "manual_expert";
  const custom = accessMode === "managed_custom";
  const fixed = accessMode === "preset";
  $("preset-variant-field").hidden = !fixed;
  $("custom-editor").hidden = !custom;
  $("development-entry").hidden = manual;
  $("new-profile").hidden = !custom;
  $("credential-manager").hidden = manual;
  $("capability-panel").hidden = manual;
  $("managed-thinking-field").hidden = fixed;
  $("analysis-inputs").hidden = manual;
  $("analyze").hidden = manual;
  $("manual-expert").hidden = !manual;
  $("profile-meta").hidden = manual;
  $("profile-summary").hidden = manual;
  $("selected-secret-status").hidden = manual;
  $("results").hidden = true;
  $("empty-state").hidden = manual;
  $("profile-label").textContent = manual ? "Connection / Target（已保存连接）" : fixed ? "Model" : "模型连接";
  $("mode-note").textContent = manual ? "独立 Raw JSON 请求；不参与水质分析或 Capability 管理。"
    : fixed ? "项目维护的固定模型与版本化合同。Thinking Variant 与 Response Mode 独立。"
      : custom ? "管理自定义连接；高级能力由当前精确 Identity 的证据决定。"
        : "Development / Test：Mock 完全离线；Local Experimental 尚未发布为 Preset。";
  if (manual) {
    ++credentialRevision;
    credentialState = null;
    $("credential-value").value = "";
    $("credential-manager").open = false;
  }
}

function updateManualTarget(profile) {
  ++formRevision; // Ignore pending Managed profile form responses.
  editingId = null;
  setFormMode("view");
  addPairs("manual-connection", [["Service", profile.service_id], ["Base URL", profile.base_url],
    ["Model", profile.model], ["Credential", profile.auth_spec === "NONE" ? "NONE_REQUIRED" : profile.credential_ref]]);
  if (manualTargetId !== profile.profile_id) {
    manualTargetId = profile.profile_id;
    $("manual-body").value = JSON.stringify({model: profile.model,
      messages: [{role: "user", content: "只回复 OK"}], max_tokens: 32}, null, 2);
    $("manual-output").textContent = "";
  }
  $("manual-status").textContent = "独立实验路径；切换目标会重置请求模板，切换运行模式保留当前草稿。";
  setStatus("Manual Expert：Send 时确认真实网络请求；Stop 复用后端取消机制。");
}

function bindAccessModeControls() {
  $("access-mode").addEventListener("change", () => setAccessMode($("access-mode").value));
  $("profile").addEventListener("change", () => {
    if (accessMode === "preset") renderPresetVariants();
    updateProfile();
  });
  $("preset-variant").addEventListener("change", () => {
    const response = $("response-mode").value;
    updateProfile();
    const profile = selectedProfile();
    if (profile) updateRuntimeOptionControls(profile, {reasoning: profile.default_reasoning_mode,
      response, effort: ""});
  });
  $("use-development").addEventListener("click", () => setAccessMode("development", $("development-target").value));
}

async function executionHeaders() {
  if (!credentialCsrf) {
    const response = await fetch("/api/credential-session", {credentials: "same-origin"});
    const data = await response.json();
    if (!response.ok || !data.csrf_token) throw new Error(safeCredentialCode(data, "CSRF_INVALID"));
    credentialCsrf = data.csrf_token;
  }
  return {"Content-Type": "application/json", "X-CSRF-Token": credentialCsrf};
}

async function beginExecution() {
  const headers = await executionHeaders();
  const response = await fetch("/api/requests", {method: "POST", headers, body: "{}"});
  const data = await response.json();
  if (!response.ok || !data.control_token || !data.request_id) throw new Error(safeCredentialCode(data, "REQUEST_PREPARE_FAILED"));
  activeExecution = {...data, headers, controller: new AbortController(), cancelled: false};
  $("stop-generation").disabled = false;
  $("manual-send").disabled = true;
  $("profile").disabled = true;
  for (const id of ["access-mode", "preset-variant", "use-development", "development-target"]) $(id).disabled = true;
  return activeExecution;
}

function finishExecution() {
  activeExecution = null;
  $("stop-generation").disabled = true;
  $("manual-send").disabled = false;
  $("profile").disabled = false;
  for (const id of ["access-mode", "use-development", "development-target"]) $(id).disabled = false;
  $("preset-variant").disabled = $("preset-variant").children.length <= 1;
}

async function stopGeneration() {
  const running = activeExecution;
  if (!running || running.cancelled) return;
  running.cancelled = true;
  $("stop-generation").disabled = true;
  setStatus("正在请求后端停止生成…");
  try {
    const post = async (action) => {
      const response = await fetch(`/api/requests/${running.request_id}/${action}`, {
        method: "POST", headers: running.headers,
        body: JSON.stringify({control_token: running.control_token}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(safeCredentialCode(data, "CANCEL_FAILED"));
      return data;
    };
    let state = await post("cancel"); // Independent request reaches server before browser abort.
    running.controller.abort();
    for (let attempt = 0; state.state === "CANCEL_REQUESTED" && attempt < 20; attempt++) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      state = await post("status");
    }
    const closed = state.backend_io_closed === true ? "后端 I/O 已关闭" : "后端 I/O 关闭尚未确认";
    const outcome = state.state === "COMPLETED" ? "请求已经完成" : state.state === "CANCELLED" ? "USER_CANCELLED" : state.state;
    setStatus(`${outcome}；${closed}；远端计算 / 计费是否停止：UNKNOWN。`);
    $("manual-status").textContent = $("status").textContent;
  } catch (exc) {
    running.controller.abort();
    setStatus(`取消未确认：${/^[A-Z][A-Z0-9_]{0,40}$/.test(exc.message) ? exc.message : "NETWORK_ERROR"}；仅停止浏览器显示，后端状态未知。`, true);
  } finally {
    // Keep the run locked until the stop acknowledgement is resolved.
    if (activeExecution === running) finishExecution();
    $("analyze").disabled = false;
  }
}

function credentialContext() {
  if (formMode === "view") {
    const profile = selectedProfile();
    return profile ? {profile_id: profile.profile_id} : null;
  }
  const fields = validateForm({modelOptional: true});
  return fields ? {draft: fields} : null;
}

function resetCredentialManager() {
  ++credentialRevision;
  credentialState = null;
  $("credential-value").value = "";
  $("credential-edit-fields").hidden = true;
  $("credential-summary").replaceChildren();
  const auth = formMode === "view" ? selectedProfile()?.auth_spec : $("custom-auth").value;
  $("credential-status").textContent = auth === "NONE" ? "不需要凭据（NONE_REQUIRED）" : "配置已改变，请刷新凭据状态。";
  if ($("credential-manager").open && formMode === "view" && !credentialBusy) Promise.resolve().then(refreshCredentialStatus);
}

function invalidateCredentialCaches() {
  ++credentialEpoch;
  testId = null;
  testedFingerprint = null;
  $("model-options").replaceChildren();
  $("model-options").hidden = true;
  $("models-status").textContent = "凭据已改变；模型列表需重新查询。";
  $("test-status").textContent = "凭据已改变；旧连接测试授权失效，请重新测试。";
}

function safeCredentialCode(data, fallback = "CREDENTIAL_ERROR") {
  return typeof data?.error_code === "string" && /^[A-Z][A-Z0-9_]{0,40}$/.test(data.error_code)
    ? data.error_code : fallback;
}

function renderCredentialState(data) {
  credentialState = data;
  addPairs("credential-summary", [["Provider", data.provider], ["Credential 名", data.credential_name],
    ["状态", data.availability], ["来源", data.source],
    ["文件位置", data.storage === "USER_PRIVATE" ? "用户私有存储（不是源码根目录 .env）" : "应用注入的凭据文件"]]);
  const editable = data.editable === true && !!data.revision;
  $("credential-edit-fields").hidden = !editable;
  $("credential-create").hidden = !editable || data.exists;
  $("credential-replace").hidden = !editable || !data.exists;
  $("credential-remove").hidden = !editable || !data.exists;
  $("credential-status").textContent = data.availability === "NONE_REQUIRED" ? "不需要凭据"
    : data.source === "PROCESS_ENV" ? "PROCESS_ENV：外部只读，需在应用外修改。"
      : data.error_code ? `无法编辑：${safeCredentialCode(data)}`
        : `PROJECT_ENV / ${data.storage === "USER_PRIVATE" ? "用户私有存储" : "应用注入的凭据文件"} 可编辑；修改后新请求立即生效，在途请求保持原快照。`;
}

async function refreshCredentialStatus() {
  if (credentialBusy) return;
  const context = credentialContext();
  if (!context) {
    $("credential-status").textContent = "请先选择配置，或填写 Provider、连接地址与凭据变量名。";
    return;
  }
  const revision = ++credentialRevision;
  $("credential-value").value = "";
  $("credential-edit-fields").hidden = true;
  $("credential-status").textContent = "正在检查凭据状态…";
  try {
    const response = await fetch("/api/credentials/status", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(context),
    });
    const data = await response.json();
    if (revision !== credentialRevision) return;
    if (!response.ok) throw new Error(safeCredentialCode(data));
    if (!data || !["PRESENT", "MISSING", "NONE_REQUIRED"].includes(data.availability)) throw new Error("INVALID_RESPONSE");
    renderCredentialState(data);
  } catch (exc) {
    if (revision === credentialRevision) {
      const code = /^[A-Z][A-Z0-9_]{0,40}$/.test(exc.message) ? exc.message : "CREDENTIAL_STATUS_ERROR";
      $("credential-status").textContent = `状态检查失败：${code}`;
      credentialState = null;
    }
  }
}

async function changeCredential(action) {
  if (credentialBusy) return;
  const context = credentialContext();
  const state = credentialState;
  if (!context || !state?.editable || !state.revision) {
    $("credential-value").value = "";
    $("credential-status").textContent = "请先刷新可编辑的凭据状态。";
    return;
  }
  let value = $("credential-value").value;
  $("credential-value").value = ""; // Clear before every await, including CSRF failure.
  if (action !== "remove" && !value) {
    $("credential-status").textContent = "请填写新 Key；不会显示已有值。";
    return;
  }
  if (!window.confirm(action === "remove" ? "删除该项目凭据？新请求将不能再使用此值。"
    : "将新 Key 写入当前项目的用户私有凭据文件（不是源码根目录 .env）。继续？")) return;
  const revision = credentialRevision;
  credentialBusy = true;
  for (const id of ["credential-create", "credential-replace", "credential-remove", "credential-refresh"]) $(id).disabled = true;
  $("credential-status").textContent = "正在安全写入项目凭据…";
  let stage = "session";
  try {
    if (!credentialCsrf) {
      const response = await fetch("/api/credential-session", {credentials: "same-origin"});
      const data = await response.json();
      if (!response.ok || typeof data.csrf_token !== "string") throw new Error(safeCredentialCode(data, "CSRF_INVALID"));
      credentialCsrf = data.csrf_token;
    }
    if (revision !== credentialRevision) return;
    stage = "write";
    const response = await fetch("/api/credentials", {
      method: {create: "POST", replace: "PUT", remove: "DELETE"}[action], credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": credentialCsrf},
      body: JSON.stringify({...context, revision: state.revision, ...(action === "remove" ? {} : {secret: value})}),
    });
    value = "";
    const data = await response.json();
    if (!response.ok) {
      if (data.error_code === "CSRF_INVALID") credentialCsrf = null;
      throw new Error(safeCredentialCode(data));
    }
    invalidateCredentialCaches(); // Never reset Capability or runtime preferences here.
    if (revision !== credentialRevision) return;
    renderCredentialState(data);
    $("credential-status").textContent = `凭据${action === "remove" ? "已删除" : "已保存"}；新请求立即生效，旧连接测试和模型列表已失效。`;
    const selected = selectedProfile();
    if (formMode === "view" && selected) showSecret(data.credential_name, "selected-secret-status", () => revision === credentialRevision, selected);
    showSecret(data.credential_name, "secret-status", () => revision === credentialRevision, formMode === "view" ? selected : null);
  } catch (exc) {
    const code = /^[A-Z][A-Z0-9_]{0,40}$/.test(exc.message) ? exc.message : stage === "write" ? "CREDENTIAL_WRITE_ERROR" : "CSRF_ERROR";
    if (revision === credentialRevision) $("credential-status").textContent = `凭据修改失败：${code}${code === "ENV_REVISION_CONFLICT" ? "；请刷新状态后重新输入。" : ""}`;
    // The write may have committed even if the response was lost; discard old authorization.
    if (stage === "write") invalidateCredentialCaches();
  } finally {
    value = "";
    credentialBusy = false;
    $("credential-value").value = "";
    for (const id of ["credential-create", "credential-replace", "credential-remove", "credential-refresh"]) $(id).disabled = false;
  }
}

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
  const model = profiles.find(item => item.profile_id === $("profile").value);
  const variant = profiles.find(item => item.profile_id === $("preset-variant").value);
  return accessMode === "preset" && model?.source === "preset" && variant?.preset_id === model.preset_id
    ? variant : model;
}

function renderProfiles(selectedId) {
  const selected = profiles.find(item => item.profile_id === selectedId);
  if (!accessMode) accessMode = selected?.source === "preset" ? "preset"
    : selected?.source === "user_custom" ? "managed_custom" : "development";
  $("access-mode").value = accessMode;
  $("profile").replaceChildren();
  const visible = visibleProfiles();
  for (const item of visible) {
    const option = document.createElement("option");
    option.value = item.profile_id;
    option.textContent = item.source === "preset" ? modelLabel(item)
      : item.runtime_type === "mock" ? "Mock · Development / Test"
        : item.source === "built_in" ? `${item.display_name} · Local Experimental` : item.display_name;
    $("profile").append(option);
  }
  const representative = visible.find(item => item.profile_id === selectedId
    || (accessMode === "preset" && selected?.preset_id && item.preset_id === selected.preset_id));
  $("profile").value = (representative || visible[0])?.profile_id || "";
  if (!visible.length) appendChoice($("profile"), "", "尚无自定义连接，请点击新建", true);
  renderPresetVariants(selectedId);
  $("development-target").replaceChildren();
  for (const item of developmentProfiles()) appendChoice($("development-target"), item.profile_id,
    item.runtime_type === "mock" ? "Mock · 完全离线" : `${item.display_name} · Local Experimental`);
  $("development-target").value = developmentProfiles()[0]?.profile_id || "";
  $("use-development").disabled = !developmentProfiles().length;
  updateModeView();
  $("manual-send").disabled = !visible.length;
  $("analyze").disabled = !visible.length;
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
  thinkingSelect.disabled = profile?.access_mode === "preset";
  effortSelect.disabled = profile?.access_mode === "preset";
  if (profile?.access_mode === "preset") {
    thinkingSelect.value = profile.default_reasoning_mode || "auto";
    effortSelect.value = "";
  }
}

function syncRuntimeOptionsFromCurrentSelections() {
  const profile = selectedProfile();
  if (!profile) return;
  updateRuntimeOptionControls(profile, {reasoning: $("reasoning-mode").value,
    response: $("response-mode").value, effort: $("reasoning-effort").value});
}

function updateProfile() {
  const profile = selectedProfile();
  if (!profile) {
    ++formRevision;
    resetCredentialManager();
    for (const id of ["profile-meta", "selected-secret-status"]) $(id).textContent = "";
    $("profile-summary").replaceChildren();
    $("capability-panel").hidden = true;
    $("edit-profile").hidden = true;
    $("delete-profile").hidden = true;
    setStatus("尚无自定义连接，请新建并保存后运行。", false);
    return;
  }
  if (accessMode === "manual_expert") { updateManualTarget(profile); return; }
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
  $("custom-auth").value = profile.auth_spec || (profile.credential_ref || profile.runtime_type === "cloud"
    ? "REQUIRED_BEARER" : "OPTIONAL_BEARER");
  updateSecretRequirement();
  $("secret-status").textContent = "";
  invalidateTest();
  $("profile-meta").textContent = `${profile.service_id || profile.provider} · ${profile.model_family || "unknown"} · ${profile.model} · ${profile.profile_status.toUpperCase()} · ${profile.runtime_type} · ${profile.source === "user_custom" ? "用户自定义" : "预置"}`;
  addPairs("profile-summary", [["Service", profile.service_id || profile.provider],
    ["Base URL", profile.base_url], ["Model ID", profile.model],
    ["Deployment", profile.runtime_type], ["Auth", profile.auth_spec || "OPTIONAL_BEARER"]]);
  $("selected-secret-status").hidden = profile.auth_spec === "NONE" || profile.runtime_type === "mock";
  const streaming = profile.capabilities?.streaming || "unknown";
  const capabilitySource = profile.capabilities?.source || "UNKNOWN";
  const capabilityLabel = streaming === "supported" && capabilitySource === "OFFICIAL_DOCS"
    ? "官方文档支持" : streaming === "supported" && capabilitySource === "USER_VERIFIED"
      ? "本机已验证" : streaming === "unsupported" ? "不支持" : "未验证";
  const scope = profile.capabilities?.streaming_scope_matches === true
    ? "已绑定当前 service / adapter / Base URL / Model" : "未绑定当前精确连接";
  $("streaming-capability").textContent = `Streaming 能力：${capabilityLabel}（${streaming.toUpperCase()}）· ${scope}`;
  renderCapabilities(profile);
  const live = profile.runtime_type !== "mock" && profile.access_mode !== "preset";
  const streamingSource = profile.capabilities?.source || "UNKNOWN";
  $("probe-streaming").hidden = !live || streamingSource === "USER_VERIFIED";
  $("reprobe-streaming").hidden = !live || streamingSource !== "USER_VERIFIED";
  $("refresh-metadata").hidden = !live || profile.service_id !== "ollama"
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
  if (profile.access_mode === "preset") {
    $("profile-meta").textContent += ` · Preset ${profile.preset_id} / ${profile.preset_variant} · 合同 v${profile.preset_contract_version}`;
    $("thinking-probe-help").textContent = "Preset 使用版本化固定合同；切换 Thinking 请选其他 Variant，本地 Probe 不会修改合同。";
  }
  $("custom-status").textContent = "正在读取所选配置…";
  $("selected-secret-status").textContent = real ? "Secret 状态：待检查" : "Mock 无需 Secret";
  fetch(`/api/profiles/${encodeURIComponent(profile.profile_id)}`)
    .then((response) => { if (!response.ok) throw new Error("PROFILE_READ_FAILED"); return response.json(); })
    .then((data) => {
      if (revision !== formRevision || selectedProfile()?.profile_id !== profile.profile_id) return;
      fillProfileForm(data.fields, profile);
      $("custom-status").textContent = data.editable
        ? "正在查看自定义配置；点击“编辑所选”可修改连接参数，名称不可修改。"
        : "预置配置只读；如需新配置，请点击“新建”。";
      const current = () => revision === formRevision && selectedProfile()?.profile_id === profile.profile_id;
      showSecret(data.fields.secret_env, "secret-status", current, profile);
      if (real) showSecret(data.fields.secret_env, "selected-secret-status", current, profile);
    })
    .catch(() => {
      if (revision === formRevision) $("custom-status").textContent = "读取所选配置失败：PROFILE_READ_FAILED";
    });
}

function capabilityText(item) {
  const status = item?.status || "unknown";
  const source = item?.source || "UNKNOWN";
  const records = item?.evidence?.length ? ` · 证据：${item.evidence.map((record) =>
    `${record.source} ${record.status} ${record.observed_at || "时间未记录"}`).join("；")}` : "";
  if (status === "unknown") return item?.resolution === "EVIDENCE_CONFLICT"
    ? `证据冲突（UNKNOWN）· ${(item.sources || []).join(" + ")}${records}` : "未验证（UNKNOWN）";
  const label = source === "MODEL_METADATA" ? "模型 metadata"
    : source === "USER_VERIFIED" ? "本机已验证"
      : source === "OFFICIAL_DOCS" ? "官方文档" : "来源未知";
  const sources = item?.sources?.length ? item.sources.join(" + ") : source;
  return `${status === "supported" ? "支持" : "不支持"}（${status.toUpperCase()}）· ${label} · ${sources}${records}`;
}

function renderCapabilities(profile) {
  const caps = profile.capabilities || {};
  const on = caps.thinking_on || {};
  const off = caps.thinking_off || {};
  const streaming = caps.streaming_evidence || {status: caps.streaming, source: caps.source};
  const modes = ["AUTO"];
  if (on.status === "supported") modes.push("ON");
  if (off.status === "supported") modes.push("OFF");
  const items = [
    ["Streaming", streaming], ["Thinking ON", on], ["Thinking OFF", off],
    ["Streaming + Thinking ON", caps.thinking_streaming_combination],
    ["Reasoning Effort", caps.reasoning_effort],
    ["Structured Output", caps.structured_output], ["Tool Calling", caps.tool_calling],
  ];
  const summary = $("capability-list");
  summary.replaceChildren();
  for (const [label, item] of items) {
    const status = ["supported", "unsupported"].includes(item?.status) ? item.status : "unknown";
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = status === "supported" ? "支持" : status === "unsupported" ? "不支持"
      : item?.resolution === "EVIDENCE_CONFLICT" ? "证据冲突" : "未验证";
    dd.className = `capability-status capability-${status}`;
    summary.append(dt, dd);
  }
  addPairs("capability-evidence", [
    ...items.map(([label, item]) => [label, capabilityText(item)]),
    ["Identity", [profile.service_id, profile.adapter_id, profile.base_url, profile.model].map(show).join(" / ")],
    ["Thinking Metadata / 支持值", `${modes.join(" / ")} · ON ${on.source || "UNKNOWN"} / OFF ${off.source || "UNKNOWN"}`],
    ["模型默认 Thinking", caps.thinking_default === null || caps.thinking_default === undefined
      ? "未知" : `${caps.thinking_default ? "ON" : "OFF"} · ${(caps.thinking_default_sources || []).join(" + ") || "UNKNOWN"}`],
    ["Effort 支持值", caps.effort_values?.join(" / ")],
  ]);
  const modelDefault = caps.thinking_default === true ? "ON" : caps.thinking_default === false ? "OFF" : "未知";
  $("thinking-hint").textContent = `模型默认 ${modelDefault}；AUTO 不发送控制参数。显式 ON / OFF 独立校验，Effort 不等于 ON。`;
}

const customFields = {
  display_name: "custom-name", service_id: "custom-provider", model_family: "custom-family",
  adapter_id: "custom-adapter", base_url: "custom-url", model: "custom-model",
  secret_env: "custom-secret-env", provider_kind: "custom-deployment", auth_spec: "custom-auth",
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

let defaultPreferenceProfile = null;
let savedThinkingPreference = "auto";

function updateDefaultPreferenceSummary() {
  const profile = defaultPreferenceProfile;
  const current = $("custom-default-thinking").value || "auto";
  const descriptions = ["on", "off"].map((mode) => {
    const item = profile?.capabilities?.[`thinking_${mode}`];
    const reason = item?.resolution === "EVIDENCE_CONFLICT" ? "证据冲突，需要人工处理"
      : item?.status === "supported" ? "已支持" : item?.status === "unsupported" ? "不支持" : "尚未验证";
    return `${mode.toUpperCase()}：${reason}`;
  });
  const effective = current === "auto" || capabilityStatus(profile, `reasoning_${current}`) === "supported" ? current : "auto";
  $("runtime-default-summary").textContent = `已保存偏好：${formMode === "new" ? "尚未保存" : savedThinkingPreference.toUpperCase()}；当前表单偏好：${current.toUpperCase()}；当前有效能力：${descriptions.join("；")}；实际安全运行值：${effective.toUpperCase()}。修改偏好不产生能力证据。`;
}

function updateDefaultPreferenceControls(profile, preference = "auto") {
  defaultPreferenceProfile = profile;
  savedThinkingPreference = profile?.stored_default_thinking_mode || preference;
  const select = $("custom-default-thinking");
  select.replaceChildren();
  appendChoice(select, "auto", "AUTO（使用服务默认，不发送开关）");
  for (const mode of ["on", "off"]) {
    const item = profile?.capabilities?.[`thinking_${mode}`];
    const status = item?.status || "unknown";
    const reason = item?.resolution === "EVIDENCE_CONFLICT" ? "证据冲突，需要人工处理"
      : status === "supported" ? "已支持" : status === "unsupported" ? "不支持"
        : `尚未验证，请先执行 Thinking ${mode.toUpperCase()} Probe`;
    appendChoice(select, mode, `${mode.toUpperCase()}（${reason}）`, status !== "supported");
  }
  // A disabled, selected historical option remains readable and serializable;
  // it cannot be newly chosen. Never erase it just because capability changed.
  select.value = ["auto", "on", "off"].includes(preference) ? preference : "auto";
  updateDefaultPreferenceSummary();
}

function fillProfileForm(fields, profile) {
  $("provider-preset").value = profile.runtime_type === "mock" ? "built_in_mock"
    : presets.some((preset) => preset.id === fields.service_id) ? fields.service_id : "custom";
  for (const [field, id] of Object.entries(customFields)) {
    const fallback = field === "default_thinking_mode" ? "auto"
      : field === "default_response_mode" ? "normal"
        : field === "auth_spec" ? (profile.auth_spec || (fields.secret_env || fields.provider_kind === "cloud"
          ? "REQUIRED_BEARER" : "OPTIONAL_BEARER")) : "";
    $(id).value = fields[field] || fallback;
  }
  $("model-options").hidden = true;
  $("models-status").textContent = "";
  $("advanced-settings").open = false;
  $("runtime-default-fields").open = false;
  updateDefaultPreferenceControls(profile, fields.default_thinking_mode || "auto");
  updateSecretRequirement();
}

function updateSecretRequirement() {
  const auth = $("custom-auth").value || "REQUIRED_BEARER";
  const none = auth === "NONE";
  $("secret-env-fields").hidden = none;
  $("secret-status").hidden = none;
  $("custom-secret-env").required = auth === "REQUIRED_BEARER";
  $("custom-secret-requirement").textContent = auth === "REQUIRED_BEARER" ? "认证必填" : "认证可选";
}

function collectFields() {
  return Object.fromEntries(Object.entries(customFields)
    .map(([field, id]) => [field, $(id).value.trim()]));
}

function connectionFingerprint(fields) {
  return JSON.stringify([fields.service_id, fields.model_family, fields.adapter_id, fields.base_url, fields.model,
    fields.secret_env, fields.provider_kind, fields.auth_spec]);
}

function invalidateTest() {
  resetCredentialManager();
  testId = null;
  testedFingerprint = null;
  $("test-status").textContent = "连接字段已改变；Cloud 保存前需重新测试。";
  if (formMode !== "view") {
    updateDefaultPreferenceControls({capabilities: {}}, "auto");
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

async function showSecret(name, targetId, isCurrent = () => true, connection = null) {
  const target = $(targetId);
  const auth = connection?.auth_spec || $("custom-auth").value || "REQUIRED_BEARER";
  if (auth === "NONE") {
    if (isCurrent()) { target.hidden = true; target.textContent = ""; }
    return;
  }
  if (isCurrent()) target.hidden = false;
  if (!name) {
    if (isCurrent()) target.textContent = auth === "OPTIONAL_BEARER"
      ? "未配置变量（可选认证）" : "Secret: MISSING；请填写环境变量名";
    return;
  }
  try {
    const response = await fetch("/api/secret-status", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(connection?.profile_id ? {profile_id: connection.profile_id}
        : {secret_env: name, auth_spec: auth}),
    });
    const data = await response.json();
    if (isCurrent()) {
      if (!response.ok) target.textContent = `${name}: ${data.error_code || "CREDENTIAL_STATUS_ERROR"}`;
      else {
        const source = data.source || "UNKNOWN";
        const access = source === "PROCESS_ENV" ? "外部只读"
          : data.editable === true ? "可在本地凭据管理中编辑" : "只读";
        const location = source === "PROJECT_ENV" && data.storage === "USER_PRIVATE" ? " / 用户私有存储" : "";
        target.textContent = `${name}: ${data.availability || data.status} · ${source}${location} · ${access}`;
      }
    }
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
  $("custom-auth").value = preset.auth_spec || (preset.secret_env ? "REQUIRED_BEARER" : "OPTIONAL_BEARER");
  $("custom-deployment").value = preset.provider_kind;
  $("model-options").hidden = true;
  updateSecretRequirement();
  showSecret($("custom-secret-env").value, "secret-status");
  invalidateTest();
}

function newProfile() {
  if (activeExecution || accessMode === "preset" || accessMode === "manual_expert") return;
  if (accessMode !== "managed_custom") setAccessMode("managed_custom");
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
  $("custom-auth").value = "REQUIRED_BEARER";
  $("custom-default-thinking").value = "auto";
  $("custom-default-response").value = "normal";
  $("runtime-default-fields").open = false;
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
    const resolved = capability === "streaming" ? data.capability.streaming_evidence
      : capability === "reasoning_on" ? data.capability.thinking_on
        : capability === "reasoning_off" ? data.capability.thinking_off
          : data.capability.thinking_streaming_combination;
    status.textContent = resolved?.resolution === "EVIDENCE_CONFLICT"
      ? `${label} 请求${data.status === "success" ? "验证成功" : "被明确拒绝"}，但证据冲突；UNKNOWN，选项仍锁定；${metrics}`
      : data.status === "success"
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
      const message = field === "secret_env" && values.auth_spec === "REQUIRED_BEARER"
        ? "必须认证的 Profile 需要 Secret 环境变量名，不能填写真实 Key。"
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
  const epoch = credentialEpoch;
  const revision = formRevision;
  const fingerprint = connectionFingerprint(values);
  $("models-status").textContent = "正在查询真实服务的模型列表…";
  $("query-models").disabled = true;
  try {
    const response = await fetch("/api/profiles/models", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...values, confirm_network: true}),
    });
    const data = await response.json();
    if (epoch !== credentialEpoch || revision !== formRevision || fingerprint !== connectionFingerprint(collectFields())) return;
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
  const epoch = credentialEpoch;
  const revision = formRevision;
  const fingerprint = connectionFingerprint(values);
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
    if (epoch !== credentialEpoch || revision !== formRevision || fingerprint !== connectionFingerprint(collectFields())) return;
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
    $("custom-status").textContent = "已保存。凭据在每次新请求开始时重新读取；外部环境变量优先，页面仅显示状态。";
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

function render(data, latency, ttft = null) {
  const runtime = data.runtime || {};
  const usage = data.usage || {};
  const displayedProvider = profiles.find((item) => item.profile_id === runtime.profile_id)?.provider || runtime.provider_id;
  $("model-inference").hidden = false;
  // Final rendering is independent of transport. Raw content belongs to debug only.
  $("streaming-preview").hidden = true;
  $("streaming-output").textContent = "";
  const inference = data.error_code ? `模型调用失败：${data.error_code}`
    : data.structured_parse_ok ? (data.inference || "无模型推断")
      : "模型输出未能解析为结构化结果；请展开调试原文检查。";
  $("model-inference").textContent = inference;
  $("reasoning-output").textContent = data.reasoning_content || "unavailable";
  $("reasoning-debug").open = false;
  $("model-output").textContent = data.generated_text || (data.error_code ? `模型调用失败：${data.error_code}` : "无模型正文");
  $("raw-model-debug").open = false;
  renderFacts(data.observed_facts);
  renderRules(data.rule_results);
  renderEvidence(data.evidence);
  addPairs("structured", [
    ["Inference", inference], ["解析成功", data.structured_parse_ok ? "是" : "否"],
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
  $("model-inference").hidden = false;
  $("model-inference").textContent = "正在生成；完成后将在这里显示解析后的模型推断。";
  $("streaming-preview").hidden = false;
  $("streaming-preview").open = true;
  $("streaming-output").textContent = "";
  $("model-output").textContent = "";
  $("raw-model-debug").open = false;
  $("reasoning-output").textContent = "";
  $("reasoning-debug").open = false;
  for (const id of ["facts", "rules", "evidence", "structured", "recommendations", "uncertainty", "runtime"]) {
    $(id).replaceChildren();
  }
}

async function analyzeStreaming(body, execution = null) {
  try {
    prepareStreamView();
  } catch (_) {
    setStatus("流式页面显示失败：STREAM_DISPLAY_ERROR", true);
    return;
  }
  const response = await fetch("/api/analyze/stream", {
    method: "POST", headers: execution?.headers || {"Content-Type": "application/json"}, body: JSON.stringify(body),
    ...(execution ? {signal: execution.controller.signal} : {}),
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
      if (execution?.cancelled) return;
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
      if (execution?.cancelled) return;
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
        if (data.result) render(data.result, data.total_latency_ms, data.ttft_ms);
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
  if (activeExecution) return;
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
  let execution = null;
  try {
    execution = await beginExecution();
    const body = {
      request_id: execution.request_id, control_token: execution.control_token,
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
      await analyzeStreaming(body, execution);
      return;
    }
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: execution.headers,
      signal: execution.controller.signal,
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (execution.cancelled) return;
    if (payload.result) {
      render(payload.result, payload.total_latency_ms);
      setStatus(payload.result.status === "completed" ? "分析完成。" : `分析失败：${show(payload.result.error_code)}`, payload.result.status !== "completed");
    } else {
      setStatus(`请求未执行：${show(payload.error_code)}`, true);
    }
  } catch (exc) {
    if (!execution?.cancelled) setStatus(`页面请求失败：${/^[A-Z][A-Z0-9_]{0,40}$/.test(exc.message) ? exc.message : "NETWORK_ERROR"}`, true);
  } finally {
    if (activeExecution === execution && !execution?.cancelled) {
      finishExecution();
      $("analyze").disabled = false;
    }
    if (real && !activeExecution) $("confirm-network").checked = false;
  }
}

async function sendManual() {
  if (activeExecution) return;
  const profile = selectedProfile();
  if (!profile || profile.runtime_type === "mock") {
    $("manual-status").textContent = "请先选择已保存的 Cloud / Local 连接。";
    return;
  }
  let body;
  try { body = JSON.parse($("manual-body").value); }
  catch (_) { $("manual-status").textContent = "INVALID_REQUEST：请求体必须是 JSON。"; return; }
  if (!window.confirm("REAL NETWORK REQUEST：发送专家请求，可能产生费用。系统不会判断高级参数能力，不会执行返回的 tool_calls。继续？")) return;
  $("analyze").disabled = true;
  $("manual-output").textContent = "";
  $("manual-status").textContent = "正在发送 Manual 请求…";
  let execution = null;
  try {
    execution = await beginExecution();
    const response = await fetch("/api/manual", {method: "POST", headers: execution.headers,
      signal: execution.controller.signal,
      body: JSON.stringify({profile_id: profile.profile_id, confirm_network: true, body,
        request_id: execution.request_id, control_token: execution.control_token})});
    if (!response.ok) {
      const data = await response.json();
      throw new Error(safeCredentialCode(data));
    }
    if (body.stream === true) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "", terminal = false;
      while (!execution.cancelled) {
        const {done, value} = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
        buffer = buffer.replace(/\r\n/g, "\n");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const kind = frame.split("\n").find(line => line.startsWith("event: "))?.slice(7);
          const data = JSON.parse(frame.split("\n").find(line => line.startsWith("data: "))?.slice(6) || "{}");
          if (execution.cancelled) return;
          if (kind === "failed") throw new Error(safeCredentialCode(data));
          if (kind === "raw_delta") $("manual-output").textContent += JSON.stringify(data, null, 2) + "\n";
          if (kind === "completed") { terminal = true; $("manual-status").textContent = `Manual 完成 · ${show(data.total_latency_ms)} ms`; }
        }
        if (done) break;
      }
      if (!terminal && !execution.cancelled) throw new Error("STREAM_INTERRUPTED");
    } else {
      const data = await response.json();
      if (execution.cancelled) return;
      $("manual-output").textContent = JSON.stringify(data, null, 2);
      $("manual-status").textContent = `Manual 完成 · ${show(data.total_latency_ms)} ms · Usage 在原始响应下方；没有执行 tool_calls。`;
    }
  } catch (exc) {
    if (!execution?.cancelled) $("manual-status").textContent = `Manual 失败：${/^[A-Z][A-Z0-9_]{0,40}$/.test(exc.message) ? exc.message : "NETWORK_ERROR"}`;
  } finally {
    if (activeExecution === execution && !execution?.cancelled) { finishExecution(); $("analyze").disabled = false; }
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
    accessMode = "preset";
    renderProfiles();
    for (const scenario of config.scenarios) {
      const option = document.createElement("option");
      option.value = scenario;
      option.textContent = scenario;
      $("scenario").append(option);
    }
    $("scenario").value = "low_oxygen";
    bindAccessModeControls();
    $("reasoning-mode").addEventListener("change", syncRuntimeOptionsFromCurrentSelections);
    $("response-mode").addEventListener("change", syncRuntimeOptionsFromCurrentSelections);
    $("custom-default-thinking").addEventListener("change", updateDefaultPreferenceSummary);
    $("analyze").addEventListener("click", analyze);
    $("stop-generation").addEventListener("click", stopGeneration);
    $("manual-send").addEventListener("click", sendManual);
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
    $("credential-manager").addEventListener("toggle", () => { if ($("credential-manager").open) refreshCredentialStatus(); });
    $("credential-refresh").addEventListener("click", refreshCredentialStatus);
    $("credential-create").addEventListener("click", () => changeCredential("create"));
    $("credential-replace").addEventListener("click", () => changeCredential("replace"));
    $("credential-remove").addEventListener("click", () => changeCredential("remove"));
    $("custom-deployment").addEventListener("change", updateSecretRequirement);
    $("custom-auth").addEventListener("change", () => {
      updateSecretRequirement();
      showSecret($("custom-secret-env").value.trim(), "secret-status");
      invalidateTest();
    });
    for (const field of ["custom-provider", "custom-adapter", "custom-url", "custom-model", "custom-secret-env", "custom-deployment", "custom-auth"]) {
      $(field).addEventListener("input", invalidateTest);
    }
    $("custom-secret-env").addEventListener("change", () => showSecret($("custom-secret-env").value.trim(), "secret-status"));
    updateSecretRequirement();
  } catch (_) {
    setStatus("页面配置加载失败：CONFIG_ERROR", true);
  }
}

init();
