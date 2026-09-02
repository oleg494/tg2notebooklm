import { APP_CONFIG } from "./site-config.js";

let runtimePromise = null;
let exportMounted = false;

self.addEventListener("message", async (event) => {
  if (event.data?.type !== "convert") return;
  try {
    const pyodide = await getRuntime();
    const { files, config } = event.data;
    validateInputs(files, config);

    progress(35, "Экспорт", "Монтирую выбранные файлы только для чтения…");
    mountExport(pyodide, files);
    pyodide.globals.set("web_config_json", JSON.stringify(config));

    progress(48, "Парсинг", "Читаю Telegram JSON/HTML и восстанавливаю связи сообщений…");
    const payloadJson = await pyodide.runPythonAsync(`
import json
import shutil
from pathlib import Path

from tg2notebooklm.model import PackageConfig
from tg2notebooklm.pack import build_package
from tg2notebooklm.parsers import parse_export

shutil.rmtree("/work", ignore_errors=True)
Path("/work").mkdir()
web_config = json.loads(web_config_json)
chats = parse_export(Path("/export"))
config = PackageConfig(
    source_limit=int(web_config["sourceLimit"]),
    target_words=int(web_config["targetWords"]),
    hard_words=500_000,
    max_source_bytes=190 * 1024 * 1024,
    include_image_atlases=bool(web_config["includeImages"]),
    include_native_files=bool(web_config["includeNative"]),
)
build_package(chats, Path("/work/package"), config)
manifest = json.loads(Path("/work/package/manifest.json").read_text(encoding="utf-8"))
sources = [
    {"name": path.name, "bytes": path.stat().st_size}
    for path in sorted((Path("/work/package") / "sources").iterdir())
    if path.is_file()
]
json.dumps({
    "summary": manifest["summary"],
    "sources": sources,
    "warnings": manifest.get("warnings", []),
    "report": Path("/work/package/report.md").read_text(encoding="utf-8"),
}, ensure_ascii=False)
`);
    const payload = JSON.parse(payloadJson);

    progress(82, "ZIP", "Сжимаю источники и аудит в один скачиваемый архив…");
    await pyodide.runPythonAsync(`
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

root = Path("/work/package")
zip_path = Path("/work/tg2notebooklm-package.zip")
with ZipFile(zip_path, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        info = ZipInfo(f"tg2notebooklm-package/{relative}", date_time=(2000, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=6)
`);
    const zipBytes = pyodide.FS.readFile("/work/tg2notebooklm-package.zip");
    const zipBuffer = zipBytes.buffer.slice(zipBytes.byteOffset, zipBytes.byteOffset + zipBytes.byteLength);
    pyodide.runPython("import shutil; shutil.rmtree('/work', ignore_errors=True)");
    self.postMessage({ type: "complete", payload, zipBuffer }, [zipBuffer]);
  } catch (error) {
    self.postMessage({ type: "error", message: conciseError(error) });
  }
});

async function getRuntime() {
  if (!runtimePromise) runtimePromise = initializeRuntime();
  return runtimePromise;
}

async function initializeRuntime() {
  progress(5, "Python", "Загружаю Pyodide. Первый запуск дольше; браузер кэширует ядро…");
  const moduleURL = new URL("pyodide.mjs", APP_CONFIG.pyodideIndexURL).href;
  const { loadPyodide } = await import(moduleURL);
  const pyodide = await loadPyodide({ indexURL: APP_CONFIG.pyodideIndexURL });

  progress(16, "Зависимости", "Загружаю Pillow и HTML-парсер…");
  await pyodide.loadPackage(["micropip", "pillow", "beautifulsoup4"]);

  progress(27, "Конвертер", "Устанавливаю проверенную сборку tg2notebooklm…");
  const wheelURL = new URL(APP_CONFIG.wheelPath, self.location.href).href;
  pyodide.globals.set("tg2notebooklm_wheel_url", wheelURL);
  await pyodide.runPythonAsync(`
import micropip
await micropip.install(tg2notebooklm_wheel_url, deps=False)
`);
  return pyodide;
}

function mountExport(pyodide, files) {
  const fs = pyodide.FS;
  if (exportMounted) {
    fs.unmount("/export");
    exportMounted = false;
  }
  try { fs.rmdir("/export"); } catch (_) { /* mount point may not exist */ }
  fs.mkdirTree("/export");
  const blobs = files.map(({ path, file }) => ({ name: path, data: file }));
  fs.mount(fs.filesystems.WORKERFS, { blobs }, "/export");
  exportMounted = true;
}

function validateInputs(files, config) {
  if (!Array.isArray(files) || files.length === 0) throw new Error("Экспорт не содержит файлов");
  for (const entry of files) {
    if (!entry?.file || typeof entry.path !== "string") throw new Error("Некорректная запись файла");
    if (entry.path.startsWith("/") || entry.path.split("/").some((part) => !part || part === "." || part === "..")) {
      throw new Error(`Небезопасный путь в экспорте: ${entry.path}`);
    }
  }
  if (!Number.isInteger(config?.sourceLimit) || config.sourceLimit < 2) throw new Error("Некорректный лимит источников");
  if (!Number.isInteger(config?.targetWords) || config.targetWords < 1 || config.targetWords > 500000) {
    throw new Error("Число слов должно быть от 1 до 500 000");
  }
}

function progress(percent, stage, message) {
  self.postMessage({ type: "progress", percent, stage, message });
}

function conciseError(error) {
  const text = error instanceof Error ? error.message : String(error);
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  return lines.at(-1) || "Неизвестная ошибка конвертации";
}
