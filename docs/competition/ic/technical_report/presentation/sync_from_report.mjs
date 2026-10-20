import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../../../..");
const RUNTIME = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies";
process.env.RUNTIME_NODE_MODULES = path.join(RUNTIME, "node/node_modules");
const SKILL = "C:/Users/TYOCT/.codex/plugins/cache/openai-primary-runtime/presentations/26.1017.22136/skills/presentations";
const revision = process.argv[2] || "r1";
if (!/^r[1-9][0-9]*$/.test(revision)) throw new Error("Use a fresh r<number>");
const BUILD = path.join(ROOT, ".iverilog-ai/presentation-sync-20261020", revision);
await fs.mkdir(path.dirname(BUILD), { recursive: true });
await fs.mkdir(BUILD, { recursive: false });
const OUTPUT = path.join(HERE, "output", revision);
await fs.mkdir(OUTPUT, { recursive: true });
const { PresentationFile, FileBlob } = await import(pathToFileURL(path.join(RUNTIME, "node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs")));
const { finalizePresentation, applyPresentationChartFont } = await import(pathToFileURL(path.join(SKILL, "container_tools/artifact_tool_utils.mjs")));
const sourceRevision = "9b39751748b5739459c0f06bc69fcf344c7b94b7";
const sourceName = "docs/competition/ic/v4/presentation/output/ICARUS_AI_IC_defense_v4.pptx";
const git = path.join(RUNTIME, "native/git/cmd/git.exe");
const original = execFileSync(git, ["show", sourceRevision + ":" + sourceName], { cwd: ROOT, maxBuffer: 40_000_000 });
const sourcePath = path.join(BUILD, "source.pptx");
await fs.writeFile(sourcePath, original);
const hash = value => createHash("sha256").update(value).digest("hex");
const deck = await PresentationFile.importPptx(await FileBlob.load(sourcePath));
const inspection = await deck.inspect({ kind: "slide,textbox,image,table,chart", maxChars: 1_000_000 });
await fs.writeFile(path.join(BUILD, "before-inspection.json"), JSON.stringify(inspection, null, 2));
if (deck.slides.items.length !== 20) throw new Error("Expected original 20-slide deck");
const FONT = "Noto Sans SC";
const C = { bg: "#F5F7F8", ink: "#182025", muted: "#53636B", cyan: "#00ABC8", grey: "#75858D", line: "#C9D3D8", white: "#FFFFFF", dark: "#1C2023" };
const oldTexts = n => inspection.records.filter(r => r.kind === "textbox" && r.slideIndex === n - 1);
const shapeAt = (n, top) => deck.resolve(oldTexts(n).find(r => r.position.top === top).id);
function text(n, value, x, y, w, h, size = 28, bold = false, color = C.ink) {
  const shape = deck.slides.items[n - 1].shapes.add({ geometry: "textbox", name: value.slice(0, 60),
    position: { left: x, top: y, width: w, height: h }, fill: "none", line: { fill: "none", width: 0 } });
  shape.text = value;
  shape.text.style = { typeface: FONT, fontSize: size, bold, color, wrap: true, autoFit: "none" };
  return shape;
}
function title(n, value) { shapeAt(n, 44).text = value; }
function footer(n, value, size = 22) {
  const shape = shapeAt(n, 638);
  shape.text = value;
  shape.position = { left: 64, top: 638, width: 1152, height: 64 };
  shape.text.style = { typeface: FONT, fontSize: size, color: C.muted, wrap: true, autoFit: "none" };
}
function clearImages(n) { for (const image of [...deck.slides.items[n - 1].images.items]) image.delete(); }
function table(n, rows, widths, y = 190, h = 350, size = 25) {
  const t = deck.slides.items[n - 1].tables.add({ rows: rows.length, columns: rows[0].length,
    left: 64, top: y, width: 1152, height: h, values: rows, columnWidths: widths });
  t.borders.assign({ fill: C.line, width: 1, style: "solid" });
  t.rows[0].height = 55;
  for (let r = 0; r < rows.length; r++) for (let c = 0; c < rows[0].length; c++) {
    const cell = t.getCell(r, c);
    cell.fill = r === 0 ? C.dark : C.white;
    cell.text.style = { typeface: FONT, fontSize: size, color: r === 0 ? C.white : C.ink, bold: r === 0, wrap: true };
  }
  return t;
}

deck.resolve(oldTexts(1).find(r => r.text === "2026-10-13").id).text = "2026-10-20";
deck.resolve(oldTexts(1).find(r => r.text.startsWith("AI 测试探索")).id).text = "在线 API 规划与逐拍功能验证";
title(3, "在线规划与本地功能验证");
title(4, "模块级验证的执行流程"); clearImages(4);
table(4, [["阶段", "当前实现"], ["输入与环境", "RTL、接口、时钟、复位及验证目标"],
  ["测试计划", "JSON 向量、持续周期、采样位置与受限断言"],
  ["真实执行", "生成测试台，Icarus 编译，vvp 仿真"], ["输出核对", "规格参考或显式期望值，记录比较数与反例"]], [270, 882], 185, 380, 27);
footer(4, "验证目标引导输入探索，功能结论由实际执行和可检查的判据支持。");

title(5, "接口与多文件编译预检"); clearImages(5);
table(5, [["输入或阶段", "处理方式"], ["RTL 源文件", "保留原文件名与文件边界，按实际源文件集合预检"],
  ["上传头文件", "保留 include 指令，自动加入头文件搜索目录"],
  ["未定义宏", "即使编译器退出 0，也拒绝预检并保留原诊断"],
  ["执行前提", "接口确认且编译预检通过，才允许运行测试"]], [270, 882], 185, 380, 26);
footer(5, "预检不执行 initial 块。头文件或源码替换后，旧计划与旧结果失效。");
footer(6, "初始规划先归一化重复名与 reset 字段，再做结构校验。\n目标文字用于引导，执行检查依赖期望值、参考模型或受限断言。", 20);

title(7, "FIFO 规格判据与同拍读写"); clearImages(7);
const chart = deck.slides.items[6].charts.add("bar", {
  position: { left: 64, top: 205, width: 800, height: 350 },
  categories: ["满时写入缺陷", "满标志缺陷", "修复后基线", "修复前基线"],
  series: [{ name: "与独立队列的差异数", values: [46, 56, 0, 66], fill: C.grey }],
  barOptions: { direction: "bar", grouping: "clustered", gapWidth: 62 }, hasLegend: false,
  chartFill: C.bg, plotAreaFill: C.bg, chartLine: { fill: "none" }, plotAreaLine: { fill: "none" },
  xAxis: { visible: true, textStyle: { typeface: FONT, fontSize: 23, fill: C.ink }, line: { fill: "none" } },
  yAxis: { visible: true, min: 0, max: 80, majorUnit: 20, textStyle: { typeface: FONT, fontSize: 22, fill: C.muted }, majorGridlines: { fill: C.line, width: 1 } },
  dataLabels: { showValue: true, position: "outEnd", textStyle: { typeface: FONT, fontSize: 26, fill: C.ink } },
});
applyPresentationChartFont(chart, { fontFamily: FONT });
text(7, "66 减至 0", 900, 235, 315, 80, 52, true, C.cyan);
text(7, "相同 76 周期\n每次 228 项比较", 900, 330, 315, 120, 29);
text(7, "控制缺陷继续检出", 900, 475, 315, 55, 25, true);
footer(7, "独立 deque 用于重放及回归规格对照，运行时仍采用经过对照的指针与计数模型。", 21);
title(8, "真实端口反馈与后续输入");
title(9, "请求预算与失败响应留存");
title(10, "六策略对照的实验设计");
title(11, "两模块任务的检出结果");
footer(11, "候选侧实际激励周期：432 / 432 / 432 / 236 / 300 / 290，正确侧同量另计。\n各任务共享 24 拍上限，自动初始复位不计入该列。", 19);
title(12, "八模块批次的执行范围");
footer(12, "18 项未执行含 1 项正确控制，8 项触达 token 预算。全部缺陷分母仍为 48。", 21);

title(14, "用户自定义 RTL 核心运行"); clearImages(14);
table(14, [["记录", "执行阶段", "实际比较", "结果"], ["首次两次", "编译停止", "0 项", "缺少子模块"],
  ["后续第 4 包", "编译与仿真完成", "30 项，7 项不一致", "failed_checks"],
  ["后续第 5 包", "编译与仿真完成", "42 项，0 项不一致", "passed"]], [230, 310, 350, 262], 190, 260, 24);
text(14, "15 组向量，22 周期，报告与 VCD 已导出", 64, 490, 1152, 60, 36, true, C.cyan);
text(14, "输入源码与替换包的两个模块内容核对一致", 64, 565, 1152, 48, 27);
footer(14, "成功包实际时钟 65ns，期望值来自 AI。不同计划不作提升对照，也不外推完整 OneWire 协议通过。", 20);

title(15, "UART 时序判据补全"); clearImages(15);
const uart = await fs.readFile(path.join(HERE, "../figures/uart.png"));
deck.slides.items[14].images.add({ blob: uart.buffer.slice(uart.byteOffset, uart.byteOffset + uart.byteLength),
  contentType: "image/png", alt: "冻结UART实现的位时间规格示意", fit: "contain",
  position: { left: 64, top: 175, width: 1152, height: 275 } });
text(15, "同一组缺陷检出由 13/15 增至 15/15", 64, 475, 1152, 65, 39, true, C.cyan);
text(15, "补充位持续时间与 busy 释放检查，正确及等价控制保持无误报", 64, 558, 1152, 56, 27);
footer(15, "人工完善判据，未计为 AI 新发现。图为规格示意，时间条件仅针对冻结实现与登记参数。", 21);

title(16, "教师组织的 AI 辅助技术复核"); clearImages(16);
table(16, [["复核意见", "本次处理"], ["多文件预检", "按实际文件集合检查，自动定位头文件并拒绝未定义宏"],
  ["FIFO 参考表述", "区分独立队列对照与运行时指针模型"], ["432 任务完整性", "披露 strict=false、未执行正确控制与预算终止"],
  ["初始归一化", "披露重名修正及 reset 字段处理"], ["激励周期口径", "注明候选侧周期，正确侧同量另计"]], [290, 862], 175, 410, 24);
footer(16, "复核含统计重算和真实执行。教师亲自确认尚未取得，不记为独立人工审核通过。", 21);
title(17, "AI 与 IC 验证的工程结合");
title(18, "应用范围与后续方向"); clearImages(18);
table(18, [["方面", "当前范围及后续工作"], ["应用范围", "模块开发与教学，验证 RTL 的状态和输出行为"],
  ["协议环境", "继续补充从设备响应和采样窗口，避免仅有主机输入"],
  ["效果评价", "扩展独立模块与缺陷来源，并对齐实际请求及周期消耗"],
  ["工程交付", "代码、报告、计划、日志和波形对应保存，检查状态分别记录"]], [270, 882], 185, 380, 26);
footer(18, "当前结果属于模块级功能验证，未开展时序或物理签核、芯片流片和工业协议认证。", 21);
shapeAt(20, 153).text = "既有工作台界面的操作入口";
footer(20, "截图来自既有界面记录。用户核心运行结果见第 14 页，截图本身不作为功能验证证据。", 21);

const reportSource = "docs/competition/ic/technical_report/technical_report.md";
const reportHash = hash(await fs.readFile(path.join(ROOT, reportSource)));
for (let i = 0; i < 20; i++) {
  const notes = [
    "正文来源：" + reportSource + "\nSHA-256：" + reportHash,
    "对照数据：docs/competition/ic/v3/material_data.json。实验原始数值及全部失败分母保留。",
    "用户运行来源：docs/trial/other_pc_user_trial_2026-10-20.md 与 docs/trial/evidence_20261020/receipt.json。",
    "复核来源：docs/review/teacher_ai_review_response_20261020.md。教师组织AI辅助，未收到亲自确认原件。",
    "图表范围：FIFO差异66/0/56/46；两模块检出12/10/8/8/11/10；八模块48/32/48/29/37/37。",
  ];
  if (i === 6) notes.push("FIFO独立队列用于重放和回归；运行时oracle仍维护存储、指针和计数。");
  if (i === 11) notes.push("432登记、414执行、18未执行，含1项正确控制；8项触达token预算，严格完整比较资格false。");
  if (i === 13) notes.push("第4包与第5包的计划和时钟不同，7项不一致到0项不能解释为同测试下的能力提升。第5包实际65ns，不是精确16MHz。");
  if (i === 14) notes.push("UART同一15个人工缺陷由13/15到15/15，6个正确/等价控制无误报，3个编译失败控制不可判定。图为规格时序示意。来源：docs/experiment/protocol_oracle_improvements_2026-10-04.md。");
  if (i === 19) notes.push("界面图片来源：docs/competition/ic/v4/screenshots/；历史截图，不宣称最新提交的浏览器验收。");
  deck.slides.items[i].speakerNotes.textFrame.setText(notes.join("\n\n"));
}
const candidate = path.join(BUILD, "candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidate);
const repairedCandidate = path.join(BUILD, "candidate.source-workbooks.pptx");
execFileSync(path.join(RUNTIME, "python/python.exe"), [path.join(HERE, "restore_source_workbooks.py"),
  sourcePath, candidate, repairedCandidate, path.join(BUILD, "retained-workbooks.json")], { stdio: "inherit", windowsHide: true });
const finalPath = path.join(OUTPUT, "ICARUS_答辩材料.pptx");
await finalizePresentation({ workspaceDir: ROOT, candidatePath: repairedCandidate, finalPath,
  pythonExecutable: path.join(RUNTIME, "python/python.exe"),
  integrityValidatorPath: path.join(SKILL, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-heading-fit", "--validate-bullet-geometry",
    ...[4,5,10,13,14,16,17,18].flatMap(n => ["--require-native-table-slide", String(n)])],
  expectedSlideCount: 20,
  requiredNativeTableOwnerSlides: [4,5,10,13,14,16,17,18], requiredNativeChartOwnerSlides: [7,11,12],
  materializeLiteralChartWorkbooks: true,
  fontPolicy: { basis: "reference", families: [FONT, "Bahnschrift"], referencePath: sourcePath, referenceSha256: hash(original) },
  verifyArtifactToolImport: true, receiptPath: path.join(BUILD, "validation.json") });
const finalDeck = await PresentationFile.importPptx(await FileBlob.load(finalPath));
for (let i = 0; i < 20; i++) {
  const stem = "slide-" + String(i + 1).padStart(2, "0");
  const png = await finalDeck.slides.items[i].export({ format: "png", scale: 1.25 });
  await fs.writeFile(path.join(BUILD, stem + ".png"), new Uint8Array(await png.arrayBuffer()));
  const layout = await finalDeck.slides.items[i].export({ format: "layout" });
  await fs.writeFile(path.join(BUILD, stem + ".layout.json"), new Uint8Array(await layout.arrayBuffer()));
}
await fs.writeFile(path.join(BUILD, "after-inspection.json"), JSON.stringify(await finalDeck.inspect({ kind: "slide,textbox,table,chart,notes", maxChars: 1_000_000 }), null, 2));
await fs.writeFile(path.join(BUILD, "build.json"), JSON.stringify({ sourceRevision, sourceName, sourceSha256: hash(original), reportSource, reportSha256: reportHash,
  slides: 20, finalPath, pngDirectory: BUILD, nativeTables: [4,5,10,13,14,16,17,18], nativeCharts: [7,11,12],
  workbookNote: "Original workbooks on slides11/12 retained byte-for-byte; a literal-data snapshot is intentionally created for the new FIFO chart. Chart values verified against the source.",
  newAPIRequests: 0, newDUTRuns: 0, visualReview: "pending" }, null, 2));
console.log(JSON.stringify({ finalPath, preview: BUILD, slides: 20, visualReview: "pending" }));
