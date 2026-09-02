const dropZone = document.querySelector("#drop-zone");
const folderInput = document.querySelector("#folder-input");
const chooseFolder = document.querySelector("#choose-folder");
const convertButton = document.querySelector("#convert-button");
const downloadButton = document.querySelector("#download-button");
const sourceLimit = document.querySelector("#source-limit");
const targetWords = document.querySelector("#target-words");
const selection = document.querySelector("#selection");
const idleState = document.querySelector("#idle-state");
const statusArea = document.querySelector("#status-area");
const statusStage = document.querySelector("#status-stage");
const statusPercent = document.querySelector("#status-percent");
const statusMessage = document.querySelector("#status-message");
const progress = document.querySelector("#progress");
const result = document.querySelector("#result");
const resultGrid = document.querySelector("#result-grid");
const sourceList = document.querySelector("#source-list");
const reportContent = document.querySelector("#report-content");
const errorBox = document.querySelector("#error-box");
const errorMessage = document.querySelector("#error-message");

let exportFiles = [];
let exportKind = null;
let outputBlob = null;
let worker = null;

chooseFolder.addEventListener("click", (event) => {
  event.stopPropagation();
  folderInput.click();
});
dropZone.addEventListener("click", (event) => {
  if (event.target !== chooseFolder) folderInput.click();
});
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    folderInput.click();
  }
});
folderInput.addEventListener("change", async () => {
  const entries = [...folderInput.files].map((file) => ({
    file,
    path: file.webkitRelativePath || file.name,
  }));
  await acceptEntries(entries);
});

for (const name of ["dragenter", "dragover"]) {
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add("is-over");
  });
}
for (const name of ["dragleave", "drop"]) {
  dropZone.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove("is-over");
  });
}
dropZone.addEventListener("drop", async (event) => {
  try {
    setBusySelection("Читаю структуру папки…");
    const entries = await entriesFromDrop(event.dataTransfer);
    await acceptEntries(entries);
  } catch (error) {
    showError(error);
  }
});

sourceLimit.addEventListener("change", updateBudgetRail);
convertButton.addEventListener("click", startConversion);
downloadButton.addEventListener("click", downloadPackage);
updateBudgetRail();

async function entriesFromDrop(dataTransfer) {
  const items = [...dataTransfer.items];
  // getAsFileSystemHandle/webkitGetAsEntry must run synchronously while the
  // drop event dispatches; after the first await the items disassociate.
  const handles = items.map((item) =>
    typeof item.getAsFileSystemHandle === "function" ? item.getAsFileSystemHandle() : null,
  );
  const legacyEntries = items.map((item) =>
    typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null,
  );
  if (handles.some(Boolean)) {
    const entries = [];
    for (const handle of handles) {
      if (handle) await walkHandle(await handle, "", entries);
    }
    if (entries.length) return entries;
  }
  if (legacyEntries.some(Boolean)) {
    const entries = [];
    for (const entry of legacyEntries) {
      if (entry) await walkLegacyEntry(entry, "", entries);
    }
    if (entries.length) return entries;
  }
  return [...dataTransfer.files].map((file) => ({ file, path: file.name }));
}

async function walkHandle(handle, prefix, output) {
  const path = prefix ? `${prefix}/${handle.name}` : handle.name;
  if (handle.kind === "file") {
    output.push({ file: await handle.getFile(), path });
    return;
  }
  for await (const child of handle.values()) {
    await walkHandle(child, path, output);
  }
}

async function walkLegacyEntry(entry, prefix, output) {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    output.push({ file, path });
    return;
  }
  const reader = entry.createReader();
  while (true) {
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    for (const child of batch) await walkLegacyEntry(child, path, output);
  }
}

async function acceptEntries(entries) {
  clearError();
  const normalized = normalizeExport(entries);
  exportFiles = normalized.files;
  exportKind = normalized.kind;
  outputBlob = null;
  result.hidden = true;
  selection.hidden = false;
  document.querySelector("#selection-format").textContent = exportKind === "json" ? "Telegram JSON" : "Telegram HTML";
  const totalBytes = exportFiles.reduce((sum, entry) => sum + entry.file.size, 0);
  document.querySelector("#selection-files").textContent = exportFiles.length.toLocaleString("ru-RU");
  document.querySelector("#selection-size").textContent = formatBytes(totalBytes);
  if (totalBytes > 800 * 1024 * 1024) {
    showError(new Error(
      `Выбрано ${formatBytes(totalBytes)}. Браузерная версия работает надёжно примерно до 800 МБ — большие экспорты конвертируйте командой: tg2notebooklm convert <папка-экспорта>`,
    ));
    convertButton.disabled = true;
    idleState.hidden = false;
    statusArea.hidden = true;
    return;
  }
  convertButton.disabled = false;
  idleState.hidden = false;
  statusArea.hidden = true;
}

function normalizeExport(entries) {
  const safeEntries = entries
    .map(({ file, path }) => ({ file, path: String(path).replaceAll("\\", "/").replace(/^\/+/, "") }))
    .filter(({ path }) => path && !path.split("/").some((part) => part === ".." || part === "."));
  const jsonRoots = safeEntries.filter(({ path }) => path.toLowerCase().endsWith("/result.json") || path.toLowerCase() === "result.json");
  const htmlRoots = safeEntries.filter(({ path }) => /(^|\/)messages\.html$/i.test(path));
  if (!jsonRoots.length && !htmlRoots.length) {
    throw new Error("В папке нет result.json или messages.html. Выберите корень экспорта Telegram Desktop, а не отдельную папку files.");
  }
  if (jsonRoots.length + htmlRoots.length > 1) {
    throw new Error("Выбрано несколько экспортов. Конвертируйте каждую папку ChatExport отдельно.");
  }
  const marker = jsonRoots[0] || htmlRoots[0];
  const kind = jsonRoots.length ? "json" : "html";
  const root = marker.path.includes("/") ? marker.path.slice(0, marker.path.lastIndexOf("/")) : "";
  const prefix = root ? `${root}/` : "";
  const selected = safeEntries
    .filter(({ path }) => !prefix || path.startsWith(prefix))
    .map(({ file, path }) => ({ file, path: prefix ? path.slice(prefix.length) : path }))
    .filter(({ path }) => path && !path.startsWith("/") && !path.split("/").some((part) => !part || part === "." || part === ".."));
  const seen = new Set();
  for (const entry of selected) {
    if (seen.has(entry.path)) throw new Error(`В экспорте повторяется путь: ${entry.path}`);
    seen.add(entry.path);
  }
  return { kind, files: selected };
}

function startConversion() {
  if (!exportFiles.length) return;
  clearError();
  const warningStrip = document.querySelector("#warning-strip");
  if (warningStrip) warningStrip.hidden = true;
  convertButton.disabled = true;
  setProgress(1, "Запуск", "Подготавливаю изолированный фоновый процесс…");

  if (worker) worker.terminate();
  worker = new Worker("./converter-worker.js", { type: "module" });
  worker.addEventListener("message", handleWorkerMessage);
  worker.addEventListener("error", (event) => {
    const raw = event.message || "Фоновый процесс не запустился";
    const translated = /abort|memory|allocation|too long|OOM/i.test(raw)
      ? "Закончилась память браузера. Экспорт слишком большой для веб-версии — используйте CLI: tg2notebooklm convert <папка-экспорта>"
      : raw;
    showError(new Error(translated));
    convertButton.disabled = false;
  });
  worker.postMessage({
    type: "convert",
    files: exportFiles,
    config: {
      sourceLimit: Number(sourceLimit.value),
      targetWords: Number(targetWords.value),
      includeImages: document.querySelector("#include-images").checked,
      includeNative: document.querySelector("#include-native").checked,
    },
  });
}

function handleWorkerMessage(event) {
  const message = event.data;
  if (message.type === "progress") {
    setProgress(message.percent, message.stage, message.message);
    return;
  }
  if (message.type === "error") {
    showError(new Error(message.message));
    convertButton.disabled = false;
    return;
  }
  if (message.type === "complete") {
    outputBlob = new Blob([message.zipBuffer], { type: "application/zip" });
    renderResult(message.payload);
    setProgress(100, "Готово", "Пакет собран локально. Скачайте ZIP и загрузите содержимое sources/ в NotebookLM.");
    convertButton.disabled = false;
    if (worker) {
      worker.terminate();
      worker = null;
    }
  }
}

function renderResult(payload) {
  resultGrid.replaceChildren();
  const summary = payload.summary;
  const stats = [
    ["Сообщений", summary.message_count],
    ["Источников", summary.source_count],
    ["Markdown", summary.text_source_count],
    ["PDF-атласов", summary.image_atlas_count],
    ["Нативных", summary.native_source_count],
    ["Не влезло", summary.excluded_by_budget],
  ];
  for (const [label, value] of stats) {
    const cell = document.createElement("div");
    cell.className = "result-stat";
    const name = document.createElement("span");
    name.textContent = label;
    const number = document.createElement("strong");
    number.textContent = Number(value).toLocaleString("ru-RU");
    cell.append(name, number);
    resultGrid.append(cell);
  }

  const warnings = payload.warnings || [];
  const warningStrip = document.querySelector("#warning-strip");
  if (warnings.length) {
    warningStrip.textContent = `Замечания конвертера: ${warnings.join("; ")}`;
    warningStrip.hidden = false;
  } else {
    warningStrip.hidden = true;
  }

  sourceList.replaceChildren();
  for (const source of payload.sources) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = source.name;
    const size = document.createElement("span");
    size.textContent = formatBytes(source.bytes);
    item.append(name, size);
    sourceList.append(item);
  }
  reportContent.textContent = payload.report;
  result.hidden = false;
}

function downloadPackage() {
  if (!outputBlob) return;
  const url = URL.createObjectURL(outputBlob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "tg2notebooklm-package.zip";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function setProgress(percent, stage, message) {
  const value = Math.max(0, Math.min(100, Number(percent)));
  statusStage.textContent = stage;
  statusPercent.textContent = `${value}%`;
  statusMessage.textContent = message;
  progress.value = value;
  progress.textContent = `${value}%`;
}

function setBusySelection(message) {
  idleState.hidden = true;
  statusArea.hidden = false;
  setProgress(1, "Чтение папки", message);
}

function showError(error) {
  errorMessage.textContent = error instanceof Error ? error.message : String(error);
  errorBox.hidden = false;
  statusArea.hidden = true;
  idleState.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorMessage.textContent = "";
}

function updateBudgetRail() {
  const value = Number(sourceLimit.value);
  document.querySelector("#budget-value").textContent = `${value} slots`;
  const minWidth = 22;
  const width = minWidth + ((value - 50) / 550) * (100 - minWidth);
  document.querySelector("#budget-fill").style.width = `${Math.max(minWidth, width)}%`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} Б`;
  const units = ["КБ", "МБ", "ГБ", "ТБ"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value < 10 ? value.toFixed(1) : value.toFixed(0)} ${unit}`;
}
