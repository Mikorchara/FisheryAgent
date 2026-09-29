const $ = (id) => document.getElementById(id);
let profiles = [];

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
  $("profile-meta").textContent = `${profile.provider} · ${profile.model} · ${profile.profile_status.toUpperCase()} · ${profile.runtime_type} · ${profile.source === "user_custom" ? "用户自定义" : "预置"}`;
  const real = profile.runtime_type !== "mock";
  $("real-warning").hidden = !real;
  $("confirm-network").checked = false;
  setStatus(real ? "此 Profile 会发起真实模型请求，请先确认。" : "Mock 模式始终离线。", false);
}

async function saveCustomProfile() {
  const button = $("save-profile");
  button.disabled = true;
  $("custom-status").textContent = "正在保存本地 Profile…";
  const values = {
    display_name: $("custom-name").value,
    provider_id: $("custom-provider").value,
    adapter_id: $("custom-adapter").value,
    base_url: $("custom-url").value,
    model: $("custom-model").value,
    secret_env: $("custom-secret-env").value,
    provider_kind: $("custom-deployment").value,
  };
  try {
    const response = await fetch("/api/profiles", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values),
    });
    const data = await response.json();
    if (!response.ok) {
      $("custom-status").textContent = `保存失败：${show(data.error_code)}`;
      return;
    }
    profiles.push(data.profile);
    renderProfiles(data.profile.profile_id);
    $("custom-status").textContent = "已保存。若 Secret 仅写在 .env，请重启 Web 服务后使用。";
  } catch (_) {
    $("custom-status").textContent = "保存失败：NETWORK_ERROR";
  } finally {
    button.disabled = false;
  }
}

function render(data, latency) {
  const reading = data.observed_facts?.water_quality || {};
  const runtime = data.runtime || {};
  const usage = data.usage || {};
  const displayedProvider = profiles.find((item) => item.profile_id === runtime.profile_id)?.provider || runtime.provider_id;
  $("model-inference").textContent = data.inference || (data.error_code ? `模型调用失败：${data.error_code}` : "无模型推断");
  $("model-output").textContent = data.generated_text || (data.error_code ? `模型调用失败：${data.error_code}` : "无模型正文");
  addPairs("facts", [
    ["水温 (°C)", reading.temperature_c], ["pH", reading.ph],
    ["溶氧 (mg/L)", reading.dissolved_oxygen_mg_l], ["质量", reading.quality],
    ["新鲜度", reading.freshness], ["观测时间", reading.observed_at],
    ["获取时间", reading.retrieved_at], ["数据来源", reading.source],
    ["检测摘要", data.observed_facts?.detection_summary ? JSON.stringify(data.observed_facts.detection_summary) : null],
  ]);
  addList("rules", data.rule_results, (li, item) => block(li, `${item.code} · ${item.severity}`, item.message, `规则版本：${item.rule_version}`));
  addList("evidence", data.evidence, (li, item) => {
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
    ["总耗时 (ms)", latency],
  ]);
  $("empty-state").hidden = true;
  $("results").hidden = false;
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
  setStatus(real ? "正在等待真实模型…" : "正在执行离线 Mock 分析…");
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        profile_id: profile.profile_id,
        scenario: $("scenario").value,
        question: $("question").value,
        confirm_network: real && $("confirm-network").checked,
      }),
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
    renderProfiles();
    for (const scenario of config.scenarios) {
      const option = document.createElement("option");
      option.value = scenario;
      option.textContent = scenario;
      $("scenario").append(option);
    }
    $("scenario").value = "low_oxygen";
    $("profile").addEventListener("change", updateProfile);
    $("analyze").addEventListener("click", analyze);
    $("save-profile").addEventListener("click", saveCustomProfile);
  } catch (_) {
    setStatus("页面配置加载失败：CONFIG_ERROR", true);
  }
}

init();
