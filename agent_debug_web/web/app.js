const form = document.querySelector("#agentForm");
const prompt = document.querySelector("#prompt");
const media = document.querySelector("#media");
const audioOutput = document.querySelector("#audioOutput");
const allowTools = document.querySelector("#allowTools");
const button = document.querySelector("#submitButton");
const status = document.querySelector("#status");
const statusDot = document.querySelector("#statusDot");
const messageList = document.querySelector("#messageList");
const emptyState = document.querySelector("#emptyState");
const fileChips = document.querySelector("#fileChips");
const sessionLabel = document.querySelector("#sessionLabel");
const conversationPreview = document.querySelector("#conversationPreview");
const conversationTime = document.querySelector("#conversationTime");
const newConversation = document.querySelector("#newConversation");
const clearConversation = document.querySelector("#clearConversation");
const conversationSearch = document.querySelector("#conversationSearch");

const SESSION_KEY = "smart_car_agent_session_id";
const MESSAGES_PREFIX = "smart_car_agent_messages_";
let sessionId = sessionStorage.getItem(SESSION_KEY) || createSessionId();
let messages = loadMessages(sessionId);

function createSessionId() {
  const id = `web-${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
  sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

function storageKey(id) {
  return `${MESSAGES_PREFIX}${id}`;
}

function loadMessages(id) {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey(id)) || "[]");
    return Array.isArray(value) ? value : [];
  } catch (_) {
    return [];
  }
}

function persistMessages() {
  const persistent = messages
    .filter((message) => !message.pending)
    .map(({ audioSrc, ...message }) => message);
  sessionStorage.setItem(storageKey(sessionId), JSON.stringify(persistent));
}

function nowLabel() {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function modalityFor(file) {
  if (file.type.startsWith("audio/")) return "audio";
  if (file.type.startsWith("image/")) return "image";
  if (file.type.startsWith("video/")) return "video";
  throw new Error(`不支持的文件类型：${file.type || file.name}`);
}

function setStatus(text, kind = "ready") {
  status.textContent = text;
  statusDot.className = kind === "busy" ? "busy" : kind === "error" ? "error" : "";
}

function addMessage(message) {
  messages.push({ id: `${Date.now()}-${Math.random()}`, time: nowLabel(), ...message });
  persistMessages();
  renderMessages();
  return messages[messages.length - 1];
}

function createText(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function renderMessages(filter = conversationSearch.value.trim()) {
  messageList.querySelectorAll(".message-row").forEach((node) => node.remove());
  const normalizedFilter = filter.toLowerCase();
  const visible = normalizedFilter
    ? messages.filter((message) => `${message.text} ${(message.attachments || []).join(" ")}`.toLowerCase().includes(normalizedFilter))
    : messages;
  emptyState.hidden = messages.length > 0;

  for (const message of visible) {
    const row = document.createElement("article");
    row.className = `message-row ${message.role}`;
    row.dataset.messageId = message.id;
    row.append(createText("span", `avatar ${message.role === "user" ? "user-avatar" : "robot-avatar"}`, message.role === "user" ? "我" : "机"));

    const content = document.createElement("div");
    content.className = "message-content";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.append(createText("span", "", message.role === "user" ? "我" : "小车 Agent"));
    meta.append(createText("time", "", message.time));
    content.append(meta);

    const bubble = document.createElement("div");
    bubble.className = `message-bubble${message.error ? " error-bubble" : ""}${message.pending ? " pending" : ""}`;
    if (message.pending) {
      for (let index = 0; index < 3; index += 1) bubble.append(createText("i", "typing-dot", ""));
    } else {
      bubble.append(document.createTextNode(message.text || "（没有文本输出）"));
    }
    if (message.attachments?.length) {
      const attachments = document.createElement("div");
      attachments.className = "attachment-list";
      message.attachments.forEach((name) => attachments.append(createText("span", "attachment-chip", name)));
      bubble.append(attachments);
    }
    content.append(bubble);

    if (message.task) {
      const details = document.createElement("details");
      details.className = "task-card";
      details.append(createText("summary", "", "查看运动任务预览"));
      details.append(createText("pre", "", message.task));
      content.append(details);
    }
    if (message.audioSrc) {
      const player = document.createElement("audio");
      player.className = "message-audio";
      player.controls = true;
      player.src = message.audioSrc;
      content.append(player);
    }
    if (message.metadata) content.append(createText("div", "message-meta", message.metadata));
    row.append(content);
    messageList.append(row);
  }

  const latest = messages.at(-1);
  conversationPreview.textContent = latest?.text || "开始一段新的调试对话";
  conversationTime.textContent = latest?.time || "现在";
  sessionLabel.textContent = sessionId;
  requestAnimationFrame(() => { messageList.scrollTop = messageList.scrollHeight; });
}

function renderFiles() {
  fileChips.replaceChildren();
  [...media.files].forEach((file) => fileChips.append(createText("span", "file-chip", file.name)));
}

function resetComposer() {
  prompt.value = "";
  media.value = "";
  fileChips.replaceChildren();
  prompt.style.height = "auto";
}

async function submitRequest() {
  const promptText = prompt.value.trim();
  const selectedFiles = [...media.files];
  if (!promptText && selectedFiles.length === 0) return;

  button.disabled = true;
  setStatus("Agent 处理中…", "busy");
  addMessage({
    role: "user",
    text: promptText || "已发送多模态文件",
    attachments: selectedFiles.map((file) => file.name),
  });
  const pending = addMessage({ role: "assistant", text: "", pending: true });
  resetComposer();

  const inputs = [];
  if (promptText) inputs.push({ type: "text", name: "prompt", mime_type: "text/plain", text: promptText });
  try {
    for (const file of selectedFiles) {
      inputs.push({
        type: modalityFor(file),
        name: file.name,
        mime_type: file.type,
        data_base64: await fileToBase64(file),
      });
    }
    const started = performance.now();
    const response = await fetch("/api/agent/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        inputs,
        response_modalities: audioOutput.checked ? ["text", "audio"] : ["text"],
        allow_tools: allowTools.checked,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "请求失败");
    const text = payload.outputs.find((part) => part.type === "text");
    const voice = payload.outputs.find((part) => part.type === "audio" && part.data_base64);
    const robotTask = payload.outputs.find((part) => part.type === "json" && part.name === "robot_task");
    pending.pending = false;
    pending.text = text?.text || "（没有文本输出）";
    pending.metadata = `${payload.generation_provider || "unknown"} · ${payload.speech_provider || "no voice"} · ${((performance.now() - started) / 1000).toFixed(2)}s`;
    pending.audioSrc = voice ? `data:${voice.mime_type};base64,${voice.data_base64}` : "";
    if (robotTask) {
      try {
        pending.task = JSON.stringify(JSON.parse(robotTask.text), null, 2);
      } catch (_) {
        pending.task = `运动任务格式无效\n${robotTask.text}`;
      }
    }
    if (payload.error_message) pending.error = payload.error_message;
    setStatus(`${payload.status} · ${payload.request_id.slice(0, 8)}`);
  } catch (failure) {
    pending.pending = false;
    pending.error = true;
    pending.text = `请求未完成：${failure.message}`;
    setStatus("请求失败", "error");
  } finally {
    button.disabled = false;
    persistMessages();
    renderMessages();
    prompt.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  submitRequest();
});
prompt.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});
prompt.addEventListener("input", () => {
  prompt.style.height = "auto";
  prompt.style.height = `${Math.min(prompt.scrollHeight, 180)}px`;
});
media.addEventListener("change", renderFiles);
conversationSearch.addEventListener("input", () => renderMessages());

document.querySelectorAll("[data-prompt]").forEach((quickPrompt) => {
  quickPrompt.addEventListener("click", () => {
    prompt.value = quickPrompt.dataset.prompt;
    prompt.focus();
  });
});

newConversation.addEventListener("click", () => {
  sessionId = createSessionId();
  messages = [];
  setStatus("新会话已创建");
  renderMessages();
  prompt.focus();
});

clearConversation.addEventListener("click", () => {
  messages = [];
  sessionStorage.removeItem(storageKey(sessionId));
  renderMessages();
});

renderMessages();
