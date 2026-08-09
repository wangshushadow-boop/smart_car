const form = document.querySelector("#agentForm");
const prompt = document.querySelector("#prompt");
const media = document.querySelector("#media");
const audioOutput = document.querySelector("#audioOutput");
const allowTools = document.querySelector("#allowTools");
const button = document.querySelector("#submitButton");
const status = document.querySelector("#status");
const answer = document.querySelector("#answer");
const task = document.querySelector("#task");
const audio = document.querySelector("#audio");
const metadata = document.querySelector("#metadata");
const error = document.querySelector("#error");

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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!prompt.value.trim() && media.files.length === 0) return;
  button.disabled = true;
  status.textContent = "Agent 处理中…";
  error.textContent = "";
  audio.hidden = true;
  task.hidden = true;
  const inputs = [];
  if (prompt.value.trim()) {
    inputs.push({ type: "text", name: "prompt", mime_type: "text/plain", text: prompt.value.trim() });
  }
  try {
    for (const file of media.files) {
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
    answer.textContent = text?.text || "（没有文本输出）";
    if (robotTask) {
      try {
        task.textContent = `运动任务预览\n${JSON.stringify(JSON.parse(robotTask.text), null, 2)}`;
      } catch (_) {
        task.textContent = `运动任务格式无效\n${robotTask.text}`;
      }
      task.hidden = false;
    }
    if (voice) {
      audio.src = `data:${voice.mime_type};base64,${voice.data_base64}`;
      audio.hidden = false;
    }
    metadata.textContent = `${payload.generation_provider || "unknown"} · ${payload.speech_provider || "no voice"} · ${((performance.now() - started) / 1000).toFixed(2)}s`;
    status.textContent = `${payload.status} · ${payload.request_id.slice(0, 8)}`;
    error.textContent = payload.error_message || "";
  } catch (failure) {
    status.textContent = "失败";
    answer.textContent = "请求未完成。";
    error.textContent = failure.message;
  } finally {
    button.disabled = false;
  }
});
