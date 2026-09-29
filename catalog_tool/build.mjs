import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

function args() {
  const result = {};
  for (let i = 2; i < process.argv.length; i += 2) {
    const key = process.argv[i];
    if (!key?.startsWith("--") || !process.argv[i + 1]) throw new Error(`Invalid argument: ${key}`);
    result[key.slice(2)] = process.argv[i + 1];
  }
  for (const key of ["work-dir", "output", "config", "workspace-dir"]) {
    if (!result[key]) throw new Error(`Missing --${key}`);
  }
  return result;
}

const options = args();
const workDir = path.resolve(options["work-dir"]);
const finalPath = path.resolve(options.output);
const workspaceDir = path.resolve(options["workspace-dir"]);
const config = JSON.parse(await fs.readFile(path.resolve(options.config), "utf8"));
const products = JSON.parse(await fs.readFile(path.join(workDir, "catalog-data.json"), "utf8"));
const skillDir = process.env.PRESENTATION_SKILL_DIR;
const pythonExecutable = process.env.RUNTIME_PYTHON;
if (!skillDir || !pythonExecutable) throw new Error("PRESENTATION_SKILL_DIR and RUNTIME_PYTHON are required");
if (!finalPath.startsWith(workspaceDir + path.sep)) throw new Error("Output must be inside the workspace");
try { await fs.access(finalPath); throw new Error(`Output already exists: ${finalPath}`); }
catch (error) { if (error.code !== "ENOENT") throw error; }
const { resolvePresentationFont, finalizePresentation } = await import(
  pathToFileURL(path.join(skillDir, "container_tools/artifact_tool_utils.mjs")).href
);
const font = resolvePresentationFont({ fontFamily: "Microsoft YaHei" });
const accent = String(config.brandColor ?? "#17345A");
const placeholderHashes = new Set(config.placeholderProductImageSha256 ?? []);
const presentation = Presentation.create({ slideSize: { width: 1280, height: 690 } });
const manifest = [];

function addText(slide, value, box, fontSize, opts = {}) {
  const shape = slide.shapes.add({ geometry: "textbox", position: box,
    fill: "none", line: { fill: "none", width: 0 } });
  shape.text = String(value);
  shape.text.style = { typeface: font, fontSize, bold: opts.bold ?? false,
    color: opts.color ?? "#111111", alignment: opts.align ?? "left",
    verticalAlignment: "top", wrap: "square", autoFit: opts.autoFit ?? "shrinkText",
    insets: { left: 0, right: 0, top: 0, bottom: 0 } };
  return shape;
}

function weightedLength(s) {
  let width = 0;
  for (const char of s) {
    if (/\p{Script=Han}|[\u3000-\u303f\uff00-\uffef]/u.test(char)) width += 1;
    else if (/[A-Z0-9]/.test(char)) width += 0.67;
    else width += 0.55;
  }
  return width;
}

function featurePages(text, capacity = 31.5) {
  const lines = [];
  for (const sourceLine of text.split("\n")) {
    if (!sourceLine) { lines.push(""); continue; }
    let line = "";
    for (const char of sourceLine) {
      if (line && weightedLength(line + char) > capacity) { lines.push(line); line = ""; }
      line += char;
    }
    lines.push(line);
  }
  const pages = [];
  for (let i = 0; i < lines.length; i += 15) pages.push(lines.slice(i, i + 15).join("\n"));
  return pages;
}

function mime(imagePath) { return imagePath.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg"; }

for (const item of products) {
  const brand = String(item.brand || config.brand || "").trim();
  const prices = item.display_prices ?? Object.values(item.prices ?? {});
  if (!prices.length || prices.length > 2) throw new Error(`Choose 1 or 2 displayed prices for ${item.id}`);
  const placeholder = placeholderHashes.has(item.product_image_sha256);
  const mainImage = (placeholder ? null : item.product_image) ?? item.package_image;
  const thumbImage = item.package_image && item.package_image !== mainImage ? item.package_image : null;
  const hasImage = Boolean(mainImage);
  const features = item.features == null || String(item.features).trim() === ""
    ? "表格未提供功能特点" : String(item.features).replace(/\r\n?/g, "\n").trim();
  const pages = featurePages(features, hasImage ? 31.5 : 54);
  for (let page = 0; page < pages.length; page++) {
    const lineCount = pages[page].split("\n").length;
    const panelHeight = Math.min(519, Math.max(hasImage ? 320 : 260, 120 + lineCount * 26));
    const slide = presentation.slides.add();
    manifest.push({ slide: presentation.slides.items.length, product_id: item.id, source_row: item.row,
      part: page + 1, parts: pages.length,
      image_source: mainImage === item.package_image ? "package_image" : mainImage ? "product_image" : null });
    slide.background.fill = "#FFFFFF";
    if (thumbImage) slide.images.add({ blob: await fs.readFile(thumbImage), contentType: mime(thumbImage),
      alt: `包装图：${item.name}`, fit: "contain", position: { left: 30, top: 29, width: 104, height: 104 } });
    let title = String(item.name).replace(/[\r\n]+/g, " ").replace(/\s+/g, " ").trim();
    if (item.model != null && String(item.model).trim() && !title.includes(String(item.model))) {
      title += ` / ${String(item.model).replace(/\s+/g, " ").trim()}`;
    }
    addText(slide, title, { left: thumbImage ? 155 : 30, top: 28,
      width: hasImage ? (thumbImage ? 825 : 950) : 730, height: 108 }, 34, { bold: true });
    if (brand) addText(slide, brand, { left: 1000, top: 15, width: 250, height: 47 }, 30,
      { bold: true, color: accent, align: "right" });
    slide.shapes.add({ geometry: "rect", position: { left: 20, top: 151,
      width: hasImage ? 730 : 1230, height: panelHeight }, fill: "#F0F2F4",
      line: { fill: "none", width: 0 } });
    const heading = pages.length === 1 ? "功能特点" : `功能特点（${page + 1}/${pages.length}）`;
    addText(slide, heading, { left: 48, top: 176, width: 650, height: 55 }, 26,
      { bold: true, color: accent, autoFit: "none" });
    addText(slide, `序号 ${item.serial ?? "未提供"}`,
      { left: hasImage ? 591 : 1100, top: 182, width: 130, height: 34 }, 18,
      { color: "#555555", align: "right" });
    addText(slide, pages[page], { left: 49, top: 231,
      width: hasImage ? 670 : 1160, height: panelHeight - 100 }, 20);
    if (mainImage) slide.images.add({ blob: await fs.readFile(mainImage), contentType: mime(mainImage),
      alt: `产品图：${item.name}`, fit: "contain",
      position: { left: 785, top: 110, width: 470, height: 470 } });
    slide.shapes.add({ geometry: "rect", position: { left: 815, top: hasImage ? 590 : 69,
      width: 435, height: 73 }, fill: accent, line: { fill: "none", width: 0 } });
    const priceText = prices.map(({ label, value }) => `${label}  ${value == null || String(value).trim() === "" ? "未提供" : String(value)}`).join("\n");
    addText(slide, priceText,
      { left: 834, top: hasImage ? 597 : 76, width: 396, height: 59 }, 22,
      { color: "#FFFFFF", align: "right" });
    const cells = item.source_cells;
    slide.speakerNotes.textFrame.setText(
      `来源：${item.source_file}；工作表：${item.sheet}；第${item.row}行；产品ID：${item.id}。` +
      Object.entries(cells).map(([label, cell]) => `${label}：${cell}`).join("；") + "。" +
      `源文件SHA256：${item.source_hash}。` +
      (item.issues?.length ? `源数据提示：${item.issues.join("；")}。` : "") +
      `功能特点第${page + 1}/${pages.length}页。` +
      (placeholder ? "产品图片列是占位图，展示包装图列图片。" : "")
    );
  }
}

await fs.mkdir(workDir, { recursive: true });
await fs.mkdir(path.dirname(finalPath), { recursive: true });
await fs.writeFile(path.join(workDir, "catalog-manifest.json"), JSON.stringify(manifest, null, 2));
const candidatePath = path.join(workDir, "candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
const receiptPath = path.join(workDir, `${path.parse(finalPath).name}.validation.json`);
await finalizePresentation({ workspaceDir, candidatePath, finalPath, pythonExecutable,
  integrityValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(skillDir, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6572250", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: [font], scriptFonts: { ea: font } },
  verifyArtifactToolImport: true, receiptPath });
console.log(`Built ${manifest.length} slides for ${products.length} products`);
