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
  renderProviders(data.proxyProviders || []);
  elements.yamlEditor.value = data.configText || "";
  syncLineNumbers();

  targetedDirty = false;
  yamlDirty = false;
  yamlValid = Boolean(data.yaml && data.yaml.valid);
  updateButtons();
  updateYamlStatus(data.yaml || { valid: false, message: "未校验" });
  setStatus(elements.targetedStatus, "已加载当前配置。", "ok");
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
