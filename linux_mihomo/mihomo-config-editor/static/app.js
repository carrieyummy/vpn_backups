const TOKEN_KEY = "mihomoConfigToken";
const TOKEN_HEADER = "X-Mihomo-Config-Token";

const elements = {
  meta: document.getElementById("config-meta"),
  reloadBtn: document.getElementById("reload-btn"),
  restartBtn: document.getElementById("restart-btn"),
  tabs: Array.from(document.querySelectorAll(".tab")),
  targetedPanel: document.getElementById("targeted-panel"),
  yamlPanel: document.getElementById("yaml-panel"),
  lanText: document.getElementById("lan-text"),
  providers: document.getElementById("providers"),
  saveTargetedBtn: document.getElementById("save-targeted-btn"),
  targetedStatus: document.getElementById("targeted-status"),
  remoteProxyForm: document.getElementById("remote-proxy-form"),
  remoteHostControl: document.getElementById("remote-host-control"),
  remoteHost: document.getElementById("remote-host"),
  remoteHostToggle: document.getElementById("remote-host-toggle"),
  remoteHostOptions: document.getElementById("remote-host-options"),
  remoteUsername: document.getElementById("remote-username"),
  remotePassword: document.getElementById("remote-password"),
  remotePreviewBtn: document.getElementById("remote-preview-btn"),
  remoteApplyBtn: document.getElementById("remote-apply-btn"),
  remoteRemoveBtn: document.getElementById("remote-remove-btn"),
  remotePreview: document.getElementById("remote-preview"),
  remoteFingerprint: document.getElementById("remote-fingerprint"),
  remotePlan: document.getElementById("remote-plan"),
  remoteResult: document.getElementById("remote-result"),
  remoteFileResults: document.getElementById("remote-file-results"),
  remoteStatus: document.getElementById("remote-status"),
  yamlEditor: document.getElementById("yaml-editor"),
  lineNumbers: document.getElementById("line-numbers"),
  saveYamlBtn: document.getElementById("save-yaml-btn"),
  yamlStatus: document.getElementById("yaml-status"),
  authOverlay: document.getElementById("auth-overlay"),
  authForm: document.getElementById("auth-form"),
  authToken: document.getElementById("auth-token"),
  authError: document.getElementById("auth-error"),
};

let currentHash = "";
let lastLoadedText = "";
let yamlValid = false;
let targetedDirty = false;
let yamlDirty = false;
let validationTimer = null;
let validationSequence = 0;
let remotePreview = null;
let remoteLoginLookupSequence = 0;
let remoteLoginLookupTimer = null;

function token() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function setToken(value) {
  sessionStorage.setItem(TOKEN_KEY, value);
}

function showAuth(message = "") {
  elements.authOverlay.classList.remove("hidden");
  elements.authError.textContent = message;
  elements.authToken.focus();
}

function hideAuth() {
  elements.authOverlay.classList.add("hidden");
  elements.authError.textContent = "";
}

function setStatus(element, message, type = "muted") {
  element.classList.remove("ok", "error", "warn", "muted");
  element.classList.add(type);
  element.textContent = message;
}

async function api(path, options = {}) {
  const headers = {
    [TOKEN_HEADER]: token(),
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));

  if (response.status === 401) {
    showAuth("密钥错误或缺失。");
    throw new Error("密钥错误或缺失。");
  }

  if (!response.ok || data.ok === false) {
    const error = new Error(data.error || `请求失败：${response.status}`);
    error.details = data.details || {};
    error.status = response.status;
    throw error;
  }

  return data;
}

function applyState(data) {
  currentHash = data.configHash;
  lastLoadedText = data.configText;
  elements.meta.textContent = `config.yaml hash ${currentHash.slice(0, 12)}，${data.proxyProviders.length} 个 provider`;
  elements.lanText.value = data.lanAllowedIpsText || "";
  renderRemoteHostOptions(data.remoteHostCandidates || []);
  renderProviders(data.proxyProviders || []);
  elements.yamlEditor.value = data.configText || "";
  syncLineNumbers();

  targetedDirty = false;
  yamlDirty = false;
  yamlValid = Boolean(data.yaml && data.yaml.valid);
  updateButtons();
  updateYamlStatus(data.yaml || { valid: false, message: "未校验" });
  setStatus(elements.targetedStatus, "已加载当前配置。", "ok");
  clearRemotePreview({ clearPassword: true });
}

function renderRemoteHostOptions(hosts) {
  elements.remoteHostOptions.replaceChildren();
  hosts.forEach((host) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "remote-host-option";
    option.role = "option";
    option.textContent = host;
    option.addEventListener("click", () => {
      elements.remoteHost.value = host;
      closeRemoteHostOptions();
      elements.remoteHost.dispatchEvent(new Event("input", { bubbles: true }));
      elements.remoteHost.focus();
    });
    elements.remoteHostOptions.appendChild(option);
  });
}

function setRemoteHostOptionsOpen(open) {
  const hasOptions = elements.remoteHostOptions.childElementCount > 0;
  const visible = open && hasOptions;
  elements.remoteHostOptions.hidden = !visible;
  elements.remoteHost.setAttribute("aria-expanded", String(visible));
  elements.remoteHostToggle.setAttribute("aria-expanded", String(visible));
}

function openRemoteHostOptions() {
  setRemoteHostOptionsOpen(true);
}

function closeRemoteHostOptions() {
  setRemoteHostOptionsOpen(false);
}

function renderProviders(providers) {
  elements.providers.innerHTML = "";
  if (!providers.length) {
    const empty = document.createElement("p");
    empty.className = "status warn";
    empty.textContent = "没有找到带 url 字段的 proxy-providers。";
    elements.providers.appendChild(empty);
    return;
  }

  providers.forEach((provider) => {
    const row = document.createElement("label");
    row.className = "provider-row";

    const name = document.createElement("span");
    name.className = "provider-name";
    name.textContent = provider.name;

    const input = document.createElement("input");
    input.className = "provider-url";
    input.type = "url";
    input.value = provider.url || "";
    input.dataset.providerName = provider.name;
    input.autocomplete = "off";
    input.spellcheck = false;
    input.addEventListener("input", () => {
      targetedDirty = true;
      updateButtons();
      setStatus(elements.targetedStatus, "表单有未保存修改。", "warn");
    });

    row.append(name, input);
    elements.providers.appendChild(row);
  });
}

function collectProviders() {
  return Array.from(elements.providers.querySelectorAll(".provider-url")).map((input) => ({
    name: input.dataset.providerName,
    url: input.value.trim(),
  }));
}

async function loadState() {
  setStatus(elements.targetedStatus, "正在加载配置...", "muted");
  setStatus(elements.yamlStatus, "正在加载配置...", "muted");
  const data = await api("/api/state");
  hideAuth();
  applyState(data);
}

async function saveTargeted() {
  elements.saveTargetedBtn.disabled = true;
  setStatus(elements.targetedStatus, "正在保存表单修改...", "muted");

  try {
    const data = await api("/api/save-targeted", {
      method: "POST",
      body: JSON.stringify({
        baseHash: currentHash,
        lanAllowedIpsText: elements.lanText.value,
        proxyProviders: collectProviders(),
      }),
    });
    applyState(data);
    setStatus(elements.targetedStatus, `已保存。备份：${data.backupPath}`, "ok");
  } catch (error) {
    setStatus(elements.targetedStatus, error.message, error.status === 409 ? "warn" : "error");
    updateButtons();
  }
}

function clearRemotePreview({ clearPassword = false, message = "尚未检查远端文件。" } = {}) {
  remotePreview = null;
  elements.remoteApplyBtn.disabled = true;
  elements.remoteRemoveBtn.disabled = true;
  elements.remotePreview.hidden = true;
  elements.remoteResult.hidden = true;
  elements.remoteFingerprint.textContent = "";
  elements.remotePlan.replaceChildren();
  elements.remoteFileResults.replaceChildren();
  if (clearPassword) {
    elements.remotePassword.value = "";
  }
  if (message) {
    setStatus(elements.remoteStatus, message, "muted");
  }
}

function remoteCredentials() {
  const host = elements.remoteHost.value.trim();
  const username = elements.remoteUsername.value.trim();
  const password = elements.remotePassword.value;
  if (!host) {
    throw new Error("请输入或选择远端 IP 地址。");
  }
  return { host, username, password };
}

function looksLikeIpAddress(value) {
  return /^[0-9a-fA-F:.]+$/.test(value);
}

function scheduleRemoteLoginLookup() {
  clearTimeout(remoteLoginLookupTimer);
  const host = elements.remoteHost.value.trim();
  if (!host || !looksLikeIpAddress(host)) {
    elements.remotePassword.placeholder = "选择已保存 IP 后可留空";
    return;
  }
  remoteLoginLookupTimer = window.setTimeout(lookupSavedRemoteLogin, 220);
}

async function lookupSavedRemoteLogin() {
  const host = elements.remoteHost.value.trim();
  if (!host || !looksLikeIpAddress(host)) {
    return;
  }
  const sequence = ++remoteLoginLookupSequence;
  const requestedUsername = elements.remoteUsername.value;
  const requestedPassword = elements.remotePassword.value;

  try {
    const data = await api("/api/remote-login/lookup", {
      method: "POST",
      body: JSON.stringify({ host }),
    });
    if (sequence !== remoteLoginLookupSequence || host !== elements.remoteHost.value.trim()) {
      return;
    }
    if (!data.found) {
      elements.remotePassword.placeholder = "登录密码";
      return;
    }
    if (elements.remoteUsername.value === requestedUsername) {
      elements.remoteUsername.value = data.username;
    }
    if (elements.remotePassword.value === requestedPassword) {
      elements.remotePassword.value = "";
      elements.remotePassword.placeholder = "已保存，无需填写";
    }
    setStatus(elements.remoteStatus, `已加载 ${host} 的保存用户名；可直接检查。`, "ok");
  } catch (error) {
    if (sequence !== remoteLoginLookupSequence) {
      return;
    }
    elements.remotePassword.placeholder = "登录密码";
  }
}

function remoteActionText(file) {
  if (file.action === "create") {
    return "将创建文件并写入代理片段";
  }
  if (file.action === "update") {
    return "将清理旧定义并写入当前代理片段";
  }
  return "已是当前代理片段，无需修改";
}

function remoteRemovalText(file) {
  if (file.removalAction === "remove") {
    return `删除操作将移除 ${file.removalDefinitions} 条代理变量定义`;
  }
  return "删除操作无需修改";
}

function renderRemotePlan(data) {
  elements.remotePreview.hidden = false;
  elements.remoteFingerprint.textContent = data.hostFingerprint
    ? `已连接 SSH 主机；主机密钥指纹（自动接受）：${data.hostFingerprint}`
    : "已连接 SSH 主机；主机密钥按当前设置自动接受。";
  elements.remotePlan.replaceChildren();

  data.files.forEach((file) => {
    const row = document.createElement("div");
    row.className = "remote-plan-row";

    const name = document.createElement("strong");
    name.className = "remote-plan-file";
    name.textContent = file.label;

    const detail = document.createElement("span");
    detail.className = "remote-plan-detail";
    const cleanup = file.removedDefinitions ? `；将清理 ${file.removedDefinitions} 条代理变量定义` : "";
    const exists = file.exists ? "文件已存在" : "文件不存在";
    detail.textContent = `${exists}，${remoteActionText(file)}${cleanup}；${remoteRemovalText(file)}。`;

    row.append(name, detail);
    elements.remotePlan.appendChild(row);
  });
}

function renderRemoteResults(files, operation) {
  elements.remoteFileResults.replaceChildren();
  files.forEach((file) => {
    const card = document.createElement("article");
    card.className = "remote-file-result";

    const heading = document.createElement("div");
    heading.className = "remote-file-heading";
    const title = document.createElement("strong");
    title.textContent = file.label;
    const detail = document.createElement("span");
    if (file.action === "unchanged") {
      detail.textContent = operation === "remove" ? "未找到可删除的代理配置" : "未修改";
    } else if (file.backupPath) {
      detail.textContent = operation === "remove"
        ? `代理配置已删除；备份：${file.backupPath}`
        : `已同步；备份：${file.backupPath}`;
    } else {
      detail.textContent = "已创建并同步";
    }
    heading.append(title, detail);

    const content = document.createElement("pre");
    content.className = "remote-file-content";
    content.tabIndex = 0;
    content.textContent = file.content;
    card.append(heading, content);
    elements.remoteFileResults.appendChild(card);
  });
  elements.remoteResult.hidden = false;
}

async function previewRemoteProxy() {
  let credentials;
  try {
    credentials = remoteCredentials();
  } catch (error) {
    setStatus(elements.remoteStatus, error.message, "error");
    return;
  }

  clearRemotePreview({ message: "正在连接远端并检查文件..." });
  elements.remotePreviewBtn.disabled = true;

  try {
    const data = await api("/api/remote-proxy/preview", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    remotePreview = {
      baseHashes: Object.fromEntries(data.files.map((file) => [file.key, file.baseHash])),
      canRemove: data.files.some((file) => file.removalAction !== "unchanged"),
    };
    renderRemotePlan(data);
    elements.remoteApplyBtn.disabled = false;
    elements.remoteRemoveBtn.disabled = !remotePreview.canRemove;
    elements.remotePassword.value = "";
    elements.remotePassword.placeholder = "已保存，无需填写";
    const credentialMessage = data.credentialSource === "manual" ? "登录信息已加密保存。" : "已使用保存的登录信息。";
    setStatus(elements.remoteStatus, `${credentialMessage} 可选择同步或删除；两种操作都会先创建备份。`, "warn");
  } catch (error) {
    clearRemotePreview({ message: "" });
    setStatus(elements.remoteStatus, error.message, "error");
  } finally {
    elements.remotePreviewBtn.disabled = false;
  }
}

async function executeRemoteProxyOperation(operation) {
  if (!remotePreview) {
    setStatus(elements.remoteStatus, "请先检查远端文件。", "warn");
    return;
  }
  if (operation === "remove" && !remotePreview.canRemove) {
    setStatus(elements.remoteStatus, "预览中未找到可删除的代理配置。", "warn");
    return;
  }

  let credentials;
  try {
    credentials = remoteCredentials();
  } catch (error) {
    setStatus(elements.remoteStatus, error.message, "error");
    return;
  }

  const confirmation = operation === "remove"
    ? "将从两份远端文件删除受管代理片段和匹配的代理变量定义，并创建备份，是否继续？"
    : "将清理远端代理变量、创建备份并同步两份文件，是否继续？";
  if (!window.confirm(confirmation)) {
    return;
  }

  const baseHashes = remotePreview.baseHashes;
  elements.remotePreviewBtn.disabled = true;
  elements.remoteApplyBtn.disabled = true;
  elements.remoteRemoveBtn.disabled = true;
  setStatus(
    elements.remoteStatus,
    operation === "remove" ? "正在创建备份并删除远端代理配置..." : "正在创建备份并同步远端文件...",
    "muted",
  );

  try {
    const endpoint = operation === "remove" ? "/api/remote-proxy/remove" : "/api/remote-proxy/apply";
    const data = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ ...credentials, baseHashes }),
    });
    renderRemoteResults(data.files || [], operation);
    remotePreview = null;
    elements.remotePreview.hidden = true;
    elements.remotePlan.replaceChildren();
    elements.remotePassword.value = "";
    const changed = data.files.filter((file) => file.action !== "unchanged").length;
    const message = operation === "remove" ? "删除完成" : "同步完成";
    setStatus(elements.remoteStatus, `${message}：${changed} 个文件已修改，登录密码已清除。`, "ok");
  } catch (error) {
    clearRemotePreview({ clearPassword: true, message: "" });
    setStatus(elements.remoteStatus, error.message, error.status === 409 ? "warn" : "error");
  } finally {
    elements.remotePreviewBtn.disabled = false;
    if (remotePreview) {
      elements.remoteApplyBtn.disabled = false;
      elements.remoteRemoveBtn.disabled = !remotePreview.canRemove;
    }
  }
}

function applyRemoteProxy() {
  return executeRemoteProxyOperation("sync");
}

function removeRemoteProxy() {
  return executeRemoteProxyOperation("remove");
}

function invalidateRemotePreview() {
  if (!remotePreview && elements.remoteResult.hidden) {
    return;
  }
  clearRemotePreview({ message: "连接信息已变更，请重新检查远端文件。" });
}

async function saveYaml() {
  if (!yamlValid) {
    setStatus(elements.yamlStatus, "YAML 仍有错误，不能保存。", "error");
    return;
  }
  const confirmed = window.confirm("将用编辑器内容替换整个 config.yaml，是否继续？");
  if (!confirmed) {
    return;
  }

  elements.saveYamlBtn.disabled = true;
  setStatus(elements.yamlStatus, "正在保存完整 YAML...", "muted");

  try {
    const data = await api("/api/save-full", {
      method: "POST",
      body: JSON.stringify({
        baseHash: currentHash,
        configText: elements.yamlEditor.value,
      }),
    });
    applyState(data);
    setStatus(elements.yamlStatus, `已保存。备份：${data.backupPath}`, "ok");
  } catch (error) {
    const diagnostics = error.details || {};
    if (diagnostics.message) {
      updateYamlStatus(diagnostics);
    } else {
      setStatus(elements.yamlStatus, error.message, error.status === 409 ? "warn" : "error");
    }
    updateButtons();
  }
}

async function restartCore() {
  const confirmed = window.confirm("将执行 systemctl --user daemon-reload 并重启 mihomo.service，是否继续？");
  if (!confirmed) {
    return;
  }

  elements.restartBtn.disabled = true;
  const previous = elements.restartBtn.textContent;
  elements.restartBtn.textContent = "正在重启...";

  try {
    const data = await api("/api/restart", {
      method: "POST",
      body: JSON.stringify({}),
    });
    setStatus(elements.targetedStatus, data.message || "已重启。", "ok");
    setStatus(elements.yamlStatus, data.message || "已重启。", "ok");
  } catch (error) {
    setStatus(elements.targetedStatus, error.message, "error");
    setStatus(elements.yamlStatus, error.message, "error");
  } finally {
    elements.restartBtn.disabled = false;
    elements.restartBtn.textContent = previous;
  }
}

function updateYamlStatus(diagnostics) {
  const warnings = diagnostics.warnings && diagnostics.warnings.length
    ? ` 警告：${diagnostics.warnings.join(" ")}`
    : "";

  if (diagnostics.valid) {
    setStatus(elements.yamlStatus, `${diagnostics.message || "YAML 格式正确。"}${warnings}`, warnings ? "warn" : "ok");
    return;
  }

  const position = diagnostics.line ? `第 ${diagnostics.line} 行${diagnostics.column ? `，第 ${diagnostics.column} 列` : ""}：` : "";
  setStatus(elements.yamlStatus, `${position}${diagnostics.message || "YAML 格式无效。"}`, "error");
}

function scheduleYamlValidation() {
  clearTimeout(validationTimer);
  validationTimer = window.setTimeout(validateYaml, 350);
}

async function validateYaml() {
  const sequence = ++validationSequence;
  setStatus(elements.yamlStatus, "正在校验 YAML...", "muted");

  try {
    const diagnostics = await api("/api/validate-yaml", {
      method: "POST",
      body: JSON.stringify({ configText: elements.yamlEditor.value }),
    });
    if (sequence !== validationSequence) {
      return;
    }
    yamlValid = Boolean(diagnostics.valid);
    updateYamlStatus(diagnostics);
  } catch (error) {
    if (sequence !== validationSequence) {
      return;
    }
    yamlValid = false;
    setStatus(elements.yamlStatus, error.message, "error");
  } finally {
    if (sequence === validationSequence) {
      updateButtons();
    }
  }
}

function updateButtons() {
  elements.saveTargetedBtn.disabled = !targetedDirty;
  elements.saveYamlBtn.disabled = !yamlDirty || !yamlValid;
}

function syncLineNumbers() {
  const count = elements.yamlEditor.value.split("\n").length;
  const lines = Array.from({ length: count }, (_, index) => String(index + 1)).join("\n");
  elements.lineNumbers.textContent = lines;
  elements.lineNumbers.scrollTop = elements.yamlEditor.scrollTop;
}

function insertAtSelection(textarea, text) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  textarea.value = textarea.value.slice(0, start) + text + textarea.value.slice(end);
  textarea.selectionStart = textarea.selectionEnd = start + text.length;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function indentSelection(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const value = textarea.value;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const selected = value.slice(lineStart, end);
  const indented = selected.split("\n").map((line) => `  ${line}`).join("\n");
  textarea.value = value.slice(0, lineStart) + indented + value.slice(end);
  textarea.selectionStart = start + 2;
  textarea.selectionEnd = end + indented.length - selected.length;
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function unindentSelection(textarea) {
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const value = textarea.value;
  const lineStart = value.lastIndexOf("\n", start - 1) + 1;
  const selected = value.slice(lineStart, end);
  const unindented = selected.split("\n").map((line) => line.startsWith("  ") ? line.slice(2) : line).join("\n");
  textarea.value = value.slice(0, lineStart) + unindented + value.slice(end);
  textarea.selectionStart = Math.max(lineStart, start - 2);
  textarea.selectionEnd = Math.max(textarea.selectionStart, end - (selected.length - unindented.length));
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function switchTab(tabName) {
  elements.tabs.forEach((tab) => {
    const active = tab.dataset.tab === tabName;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  elements.targetedPanel.classList.toggle("active", tabName === "targeted");
  elements.yamlPanel.classList.toggle("active", tabName === "yaml");
  if (tabName === "yaml") {
    syncLineNumbers();
  }
}

elements.authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const value = elements.authToken.value.trim();
  if (!value) {
    elements.authError.textContent = "请输入密钥。";
    return;
  }
  setToken(value);
  try {
    await loadState();
  } catch (error) {
    elements.authError.textContent = error.message;
  }
});

elements.reloadBtn.addEventListener("click", async () => {
  if ((targetedDirty || yamlDirty) && !window.confirm("当前有未保存修改，刷新会丢弃它们，是否继续？")) {
    return;
  }
  try {
    await loadState();
  } catch (error) {
    setStatus(elements.targetedStatus, error.message, "error");
  }
});

elements.restartBtn.addEventListener("click", restartCore);
elements.saveTargetedBtn.addEventListener("click", saveTargeted);
elements.saveYamlBtn.addEventListener("click", saveYaml);
elements.remoteProxyForm.addEventListener("submit", (event) => {
  event.preventDefault();
  previewRemoteProxy();
});
elements.remoteApplyBtn.addEventListener("click", applyRemoteProxy);
elements.remoteRemoveBtn.addEventListener("click", removeRemoteProxy);

[elements.remoteUsername, elements.remotePassword].forEach((input) => {
  input.addEventListener("input", invalidateRemotePreview);
});
elements.remoteHost.addEventListener("input", () => {
  invalidateRemotePreview();
  scheduleRemoteLoginLookup();
});
elements.remoteHost.addEventListener("click", openRemoteHostOptions);
elements.remoteHost.addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") {
    event.preventDefault();
    openRemoteHostOptions();
  } else if (event.key === "Escape") {
    closeRemoteHostOptions();
  }
});
elements.remoteHostToggle.addEventListener("click", () => {
  const isOpen = !elements.remoteHostOptions.hidden;
  setRemoteHostOptionsOpen(!isOpen);
  elements.remoteHost.focus();
});
elements.remoteHostControl.addEventListener("focusout", (event) => {
  if (!elements.remoteHostControl.contains(event.relatedTarget)) {
    closeRemoteHostOptions();
  }
});

elements.lanText.addEventListener("input", () => {
  targetedDirty = true;
  updateButtons();
  setStatus(elements.targetedStatus, "表单有未保存修改。", "warn");
});

elements.yamlEditor.addEventListener("input", () => {
  yamlDirty = elements.yamlEditor.value !== lastLoadedText;
  syncLineNumbers();
  scheduleYamlValidation();
  updateButtons();
});

elements.yamlEditor.addEventListener("scroll", () => {
  elements.lineNumbers.scrollTop = elements.yamlEditor.scrollTop;
});

elements.yamlEditor.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") {
    return;
  }
  event.preventDefault();
  if (event.shiftKey) {
    unindentSelection(elements.yamlEditor);
  } else if (elements.yamlEditor.selectionStart === elements.yamlEditor.selectionEnd) {
    insertAtSelection(elements.yamlEditor, "  ");
  } else {
    indentSelection(elements.yamlEditor);
  }
});

elements.tabs.forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

window.addEventListener("beforeunload", (event) => {
  elements.remotePassword.value = "";
  if (!targetedDirty && !yamlDirty) {
    return;
  }
  event.preventDefault();
  event.returnValue = "";
});

updateButtons();

if (token()) {
  loadState().catch((error) => {
    setStatus(elements.targetedStatus, error.message, "error");
  });
} else {
  showAuth();
}
