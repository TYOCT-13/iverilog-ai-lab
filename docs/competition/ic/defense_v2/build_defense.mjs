import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
// Use the installed runtime directly; never vendor dependencies into the repository.
const RUNTIME_MODULE = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";
process.env.RUNTIME_NODE_MODULES ||= "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(RUNTIME_MODULE).href);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../../..");
const BUILD = path.join(ROOT, ".iverilog-ai/defense-v2-build");
const SKILL = "C:/Users/TYOCT/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const PYTHON = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL, "container_tools/artifact_tool_utils.mjs")).href);
const DATA = JSON.parse(await fs.readFile(path.join(HERE, "data.json"), "utf8"));
const talkSource = await fs.readFile(path.join(HERE,"speaker_notes.md"),"utf8");
const TALK = Object.fromEntries(talkSource.split(/^## /m).slice(1).flatMap(section=>{
  const match=section.match(/^(\d{2})[^\n]*\n([\s\S]*)$/);
  return match?[[Number(match[1]),match[2].trim()]]:[];
}));
const FONT = resolvePresentationFont({fontFamily:"Noto Sans SC"});
const ENGLISH = resolvePresentationFont({fontFamily:"Bahnschrift"});
const C = {bg:"#1C2023", text:"#F1F2F2", muted:"#B1B8BB", line:"#565D61", cyan:"#00C8E8", grey:"#727C82", black:"#111416"};
const DRAFT = process.argv.includes("--draft") || process.argv.includes("--review");
const INCLUDE_RESULTS = !DRAFT || process.argv.includes("--review");
const VERSION = process.env.DEFENSE_REVISION || "r1";
await fs.mkdir(BUILD, {recursive:true});
// Workbook materialization uses the working directory for temporary files.
// Keep all such files under the repository's explicitly excluded private area.
process.chdir(BUILD);
await fs.mkdir(path.join(HERE, "assets"), {recursive:true});
const sourceItems=[];
for(const [key,relative] of Object.entries({...DATA.sources,browser_crop:"docs/competition/ic/defense_v2/assets/agent-budget-crop.png",authoring_data:"docs/competition/ic/defense_v2/data.json",authoring_source:"docs/competition/ic/defense_v2/build_defense.mjs",copied_browser_controls:"docs/competition/ic/defense_v2/assets/agent-controls-1440.png"})){
  const bytes=await fs.readFile(path.join(ROOT,relative));
  sourceItems.push({key,relative_path:relative,sha256:createHash("sha256").update(bytes).digest("hex"),bytes:bytes.byteLength});
}
await fs.writeFile(path.join(HERE,"source_checksums.json"),JSON.stringify({record_kind:"defense_authoring_source_snapshot",captured_at_utc:new Date().toISOString(),formal_v2_scores_pending:DATA.v2_registration.executed_results===null,human_review_claim:false,items:sourceItems},null,2)+"\n");
await fs.writeFile(path.join(BUILD,`${VERSION}.data-snapshot.json`),JSON.stringify(DATA,null,2)+"\n");
const deck = Presentation.create({slideSize:{width:1280,height:720}});
deck.theme.colorScheme = {name:"ICARUS charcoal",themeColors:{accent1:C.cyan,accent2:C.grey,accent3:C.muted,accent4:"#CED2D4",accent5:"#32383C",accent6:"#7A8286",bg1:C.bg,bg2:C.black,tx1:C.text,tx2:C.muted,dk1:C.black,dk2:C.bg,lt1:C.text,lt2:"#CCD2D5",hlink:C.cyan,folHlink:C.cyan}};

function txt(slide, text, x,y,w,h, size=28, color=C.text, bold=false, family=FONT, name="") {
  const box=slide.shapes.add({geometry:"textbox",name:name||text.slice(0,30),position:{left:x,top:y,width:w,height:h},fill:"none",line:{fill:"none",width:0}});
  box.text=text;
  box.text.style={typeface:family,fontSize:size,color,bold,autoFit:"none",verticalAlignment:"top",wrap:true};
  return box;
}
function rule(slide,x,y,w,color=C.line,thickness=1) {
  return slide.shapes.add({geometry:"line",position:{left:x,top:y,width:w,height:0},fill:"none",line:{fill:color,width:thickness}});
}
function setSpeakerNotes(s,number,notes){
  s.speakerNotes.textFrame.setText(`${TALK[number] || ""}\n\n来源与口径：${notes}`);
}
function slide(title,notes="") {
  const s=deck.slides.add(); s.background.fill=C.bg;
  txt(s,title,64,47,1100,70,46,C.text,true);
  rule(s,64,131,1148);
  txt(s,String(deck.slides.items?.length || slide.count++).padStart(2,"0"),1160,49,60,54,34,C.cyan,true,ENGLISH);
  setSpeakerNotes(s,deck.slides.items.length,notes);
  return s;
}
slide.count=1;
function note(s, text) {txt(s,text,64,628,1148,52,22,C.muted,false);}
function metric(s, value,label,x=70,y=215,w=400) {txt(s,String(value),x,y,w,112,92,C.cyan,true,ENGLISH);txt(s,label,x,y+120,w,86,27,C.text);}
function table(s,values,x,y,width,height,widths,fontSize=26,accentColumn=null) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width,height,values,columnWidths:widths});
  t.borders.assign({fill:C.line,width:1,style:"solid"});
  for(let r=0;r<values.length;r++)for(let col=0;col<values[0].length;col++){
    const cell=t.getCell(r,col);cell.fill=r===0?C.black:C.bg;
    const numeric = r > 0 && /^\d+(?:\s*\/\s*\d+)*$/.test(String(values[r][col]));
    const accent = numeric && (accentColumn===null || col===accentColumn);
    cell.text.style={typeface:FONT,fontSize:r===0?24:fontSize,color:accent?C.cyan:C.text,bold:r===0};
  }
  return t;
}
function bar(s,cats,values,x,y,w,h,max,points=[]){
  // Native horizontal bars display categories from bottom to top. Reverse both
  // arrays (and their point styles) so the author-specified order reads top-down.
  const reversedPoints = points.map(p=>({...p,idx:cats.length-1-p.idx}));
  const ch=s.charts.add("bar",{position:{left:x,top:y,width:w,height:h},categories:[...cats].reverse(),
    series:[{name:"实际观测",values:[...values].reverse(),fill:C.grey,points:reversedPoints}],barOptions:{direction:"bar",grouping:"clustered",gapWidth:65},
    hasLegend:false,chartFill:C.bg,plotAreaFill:C.bg,chartLine:{fill:"none"},plotAreaLine:{fill:"none"},
    xAxis:{visible:true,textStyle:{typeface:FONT,fontSize:25,fill:C.text},line:{fill:"none"},majorGridlines:null},
    // In this native chart API, yAxis is the numeric value axis even when the
    // bars are horizontal. Keep zero and the actual denominator explicit.
    yAxis:{visible:true,min:0,max,majorUnit:max>15?20:max>8?5:1,numberFormatCode:"0",textStyle:{typeface:FONT,fontSize:22,fill:C.muted},line:{fill:C.line,width:1},majorGridlines:{fill:C.line,width:.5}},
    dataLabels:{showValue:true,position:"outEnd",textStyle:{typeface:FONT,fontSize:29,bold:true,fill:C.text}}});
  applyPresentationChartFont(ch,{fontFamily:FONT});return ch;
}
async function image(s,relative,x,y,w,h,alt){
  const source=path.join(ROOT,relative);const bytes=await fs.readFile(source);
  const target=path.join(HERE,"assets",path.basename(relative));
  if(path.resolve(source)!==path.resolve(target))await fs.copyFile(source,target);
  s.images.add({blob:new Uint8Array(bytes),contentType:relative.endsWith(".svg")?"image/svg+xml":"image/png",alt,fit:"contain",position:{left:x,top:y,width:w,height:h}});
}

// 01 Minimal cover. The original project illustration is not a photograph.
{
  const s=deck.slides.add();s.background.fill=C.bg;
  txt(s,"ICARUS",64,76,690,160,120,C.text,true,ENGLISH);
  txt(s,"数字 IP 验证智能体",68,247,570,68,45,C.text,true);
  txt(s,"AI+集成电路\n第三方 API 规划测试，独立判据解释仿真",68,344,565,123,28,C.muted);
  rule(s,68,504,190,C.cyan,5);
  await image(s,DATA.sources.cover_asset,574,230,694,378,"项目原创RTL验证设备示意图，非实物照片");
  txt(s,DATA.date,68,604,340,44,23,C.muted,false,ENGLISH);
  setSpeakerNotes(s,1,"项目原创示意素材：ui/assets/verification-map.svg。此图是视觉示意，不代表实物硬件或测试现场。作品没有自行训练基础模型权重，使用第三方模型API推理。真人试用与独立人工审核原件尚未补入。");
}
// 02 Needs grounded in actual development observations, not fictitious interviews.
{
  const s=slide("数字 IP 的验证需求",`来源：${DATA.sources.legacy_pilot}，${DATA.sources.protocol_oracles}。需求来自案例执行与失败记录分析，没有行业访谈数量或未测量效率百分比。`);
  txt(s,"测试输入能运行\n还需要覆盖关键行为",68,200,660,143,45,C.text,true);
  txt(s,"复位、空满边界、串行帧和反压\n都需要具体的激励与正确的采样时刻",68,383,750,100,30,C.muted);
  txt(s,"使用对象",927,201,280,45,25,C.cyan,true);
  txt(s,"数字电路学习者\n小型 IP 开发者\n技术复核人员",927,260,285,170,29);
  note(s,"需求依据是本项目的真实执行记录。真人任务计时和独立人审原件仍需补入。");
}
// 03 Editable functional architecture, no decorative UI cards.
{
  const s=slide("API 规划与仿真裁决的分工",`来源：src/iverilog_ai/ai/agent.py、core/pipeline.py、core/reference_model.py。动作仅append_vectors和stop。API不能修改RTL或期望值。外部有限差分必须保留证据类型与支持范围。`);
  const boxes=[txt(s,"人工规格\n接口合约",68,218,234,105,31,C.text,true),txt(s,"模型 API\n追加输入建议",348,218,244,105,31,C.text,true),txt(s,"受控执行器\n真实 Icarus",635,218,244,105,31,C.text,true),txt(s,"独立判据\n结果与原件",927,218,250,105,31,C.text,true)];
  for(let i=0;i<3;i++)s.shapes.connect(boxes[i],boxes[i+1],{kind:"straight",fromSide:"right",toSide:"left",line:{fill:C.cyan,width:2},tail:{type:"arrow",width:"sm",length:"sm"}});
  rule(s,68,382,1115);
  txt(s,"执行反馈",68,431,240,50,29,C.cyan,true);
  txt(s,"实际端口采样、检查摘要、覆盖缺口与剩余预算\n进入下一轮测试规划，模型期望值不参与受支持设计的判定",348,423,850,128,29);
  note(s,"内置判据来自已对齐参考模型。外部流程使用有限资格检查和限定输出差分。");
}
// 04 Native budget table.
{
  const s=slide("动作权限与统一执行预算",`来源：${DATA.sources.protocols}；${DATA.sources.v2_registration}。每轮最多追加12向量，TestPlan最多200向量。周期为多轮累计搜索激励，自动初始复位不计入，参考审计单列。UI自定义预算与实验预注册预算分开。`);
  txt(s,"仅追加输入或停止",68,175,570,54,33,C.cyan,true);
  txt(s,"不能改 RTL、旧向量、判据或执行命令",68,236,1100,54,29);
  table(s,[["模块","已审计参数","累计激励周期上限"],...DATA.protocols.map(p=>[p.case,p.parameters,p.cycles])],68,314,1130,280,[245,500,385]);
  note(s,"每轮最多追加 12 向量。轮数、请求数、向量数、超时与累计周期共同约束执行。");
}
// 05 Scenario evidence categories are deliberately distinct from correctness.
{
  const s=slide("逐周期采样与 24 个功能场景",`来源：${DATA.sources.coverage}；src/iverilog_ai/core/functional_coverage.py。7+6+6+5=24个有限命名场景。采样在真实TB采样点逐周期读取端口，验证RTL/plan/contract/TB的SHA，缺失或时序不匹配为unknown。`);
  metric(s,24,"有限命名场景\n依据真实输入与输出",68,173,405);
  table(s,[["模块","场景数","代表场景"],["FIFO","7","空满与边界请求尝试"],["UART TX","6","请求、busy、完整 41 拍帧"],["SPI 示例","6","时钟切换与完成序列"],["握手缓存","5","反压保持、消费和补入条件"]],508,180,702,370,[170,100,432]);
  note(s,"分别报告输入尝试、输出状态和协议序列。缺样本、X/Z 或工件不匹配时保留未知。");
  txt(s,"场景命中不等于功能正确，也不代表 RTL 代码覆盖率",68,554,1130,49,29,C.text,true);
}
// 06 Native chart and exact evidence; no claim that this was found by API.
{
  const s=slide("FIFO 的独立队列反例与净零修复",`来源：${DATA.sources.fifo_before}；${DATA.sources.fifo_after}；${DATA.sources.protocol_oracles}。同一76周期、228次比较。第5拍（原件zero-based cycle=4）同时读写：队列[25,66]读25并写99后为[66,99]，占用量2不变；第7拍（cycle=6）first mismatch为full旧0、应1、修复后1。旧RTL和旧oracle曾共享count错误。独立deque检查后同时修RTL与模型；新两个单点控制未继承旧共同计数错误。`);
  txt(s,"中间占用时同时接受读写\n占用量应保持",68,181,625,94,34,C.text,true);
  txt(s,"第 5 拍：读 25 + 写 99 → 队列 [66, 99]",68,294,747,50,27,C.muted);
  bar(s,["修复前","修复后"],[66,0],68,372,690,185,80,[{idx:1,fill:C.cyan}]);
  metric(s,"228","同一 76 周期\n输出比较数",866,195,320);
  txt(s,"首次端口差异：第 7 拍",866,436,337,45,26,C.text,true);
  txt(s,"full 旧实现 0 / 队列应为 1\n修复后：1",866,493,337,100,26);
  note(s,"图中为差异次数；新单点控制仍触发 56 / 46 次差异。此页为规格与实现修复，非 AI 成绩。");
}
// 07 Exact same external inputs before and after the oracle improvement.
{
  const s=slide("UART 计时补全与外部变体重放",`来源：${DATA.sources.external_after}；${DATA.sources.protocol_oracles}。同24个冻结候选模块，uart_rx、uart_tx、priority_encoder各8项；只加强UART TX人工SPEC，外部全15个历史人工变体的检出使13/15变为15/15，不是API收益。3基线3等价3编译坏控制，来自同作者两仓库，非独立holdout。`);
  bar(s,["旧规格检查","补全计时后"],[13,15],68,206,660,320,15,[{idx:1,fill:C.cyan}]);
  txt(s,"同一 24 个候选模块",832,191,370,57,34,C.text,true);
  txt(s,"15 个历史人工变体\n3 个正确基线\n3 个等价改写\n3 个编译失败控制",832,272,370,230,28);
  txt(s,"正确和等价控制无误报",832,526,380,43,27,C.cyan,true);
  note(s,"UART TX 新增逐位计时与 busy 释放期限。全 15 个外部人工变体的改进来自判据补全。");
}
// 08 Actual current UI controls, cropped without altering source evidence.
{
  const s=slide("网页与命令行操作入口",`截图：${DATA.sources.browser_controls}，当前机器浏览器操作，0API、0真人。截图展示真实预算和覆盖开关，未展示真实在线API Agent结果。离线UART运行29向量、58/58比较、切页保留；手机为桌面视口模拟，非真实设备。`);
  metric(s,"58 / 58","UART 离线实跑比较一致\n29 个测试向量",68,190,396);
  txt(s,"输入与结果切页保留\n三种视口没有横向溢出\nCLI 保存原始运行工件",68,430,400,139,27);
  // This is a pixel crop of the original screenshot; controls and evidence are
  // unchanged. Record the original path and source-pixel bounds in data.json.
  await image(s,"docs/competition/ic/defense_v2/assets/agent-budget-crop.png",507,170,702,422,"真实网页中的Agent预算与场景覆盖开关，原图局部裁切");
  note(s,"截图展示当前真实控件。本页运行数字来自离线 Icarus，在线 API 成绩另页说明。");
}
// 09 Evidence is also useful when no external network is available.
{
  const s=slide("运行证据与离线重放",`来源：${DATA.sources.evidence_pack}，docs/review/ic_pack_review_2026-10-04.md。旧包41007文件含manifest，41006对象SHA核对；同主机从外部ZIP解包source执行0API重放547输出比较零差异。此为机器复核，非独立人工审核。新v2材料不在旧包内。`);
  txt(s,"每轮保留输入、计划、测试台与仿真记录",68,185,1080,83,39,C.text,true);
  table(s,[["工件","复核用途"],["RTL / 合约 / 计划 / TB 的 SHA","核对是否使用相同输入与判据"],["逐周期采样和检查结果","定位首次差异与未知证据"],["API 轨迹和停止原因","核对请求、预算和未完成任务"],["日志、波形和冻结快照","网络中断时仍可离线重放"]],68,304,1128,280,[572,556]);
  note(s,"同主机从冻结 ZIP 解包重放：0 API 请求，547 次输出比较，0 差异。新 v2 证据另存。");
}
// 10 Historical pilot, never relabeled as the newest code's performance.
{
  const s=slide("历史 pilot 的五策略结果",`来源：${DATA.sources.legacy_pilot}；${DATA.sources.legacy_summary}。冻结源码e9b7b8a，4模块8缺陷5策略1重复60行，52真实API请求234536tokens，完整失败保留。FIFO/规格/预算/采样随后都变化，不能与新版本作单因素提升归因。`);
  bar(s,DATA.legacy_pilot.strategies,DATA.legacy_pilot.detected,68,185,733,395,8,[{idx:3,fill:C.cyan}]);
  metric(s,"4 / 8","历史反馈 Agent 检出\n固定和随机各 5/8",886,191,326);
  txt(s,"60 行 / 52 次 API 请求\n开发集，仅 1 次重复\n冻结版本 e9b7b8a",886,450,326,132,26);
  note(s,"历史结果支持流程可运行，尚未证明 Agent 普遍提高检出率。失败与不可判定保留在分母。");
}

if(INCLUDE_RESULTS){
  const live=DATA.v2_registration.executed_results;
  if(!live)throw new Error("Final export requires actual v2 execution evidence. Use --draft while waiting.");
  const smoke=DATA.v2_registration.v4_smoke_results;
  if(!DRAFT && !smoke)throw new Error("Final export requires the separately audited v4 smoke snapshot. Use --review while waiting.");
  const s=slide("Agent v2：三次重复的真实结果",live.notes || "");
  // This slide is driven only by an explicit, audited snapshot supplied by the
  // execution owner. No placeholder results or inferred successful calls.
  table(s,live.table,68,177,1129,355,live.column_widths || [402,205,240,282],24,1);
  txt(s,live.conclusion,68,555,1129,55,28,C.text,true);
  note(s,live.disclosure);
  {
    const z=slide(smoke?"v4：动作接通，检出仍待提升":"局限与下一步",smoke?.notes || `所有数字来源见各页备注。真人试用和独立人工复核原件尚未补入，不作已完成承诺。有限开发集和参数形状不支持通用SoC验证或物理签核。后续独立留出、计时效率和跨机审核仍需要实际执行。`);
    if(smoke){
      txt(z,"一次重复 / 同一开发集",68,176,715,48,30,C.text,true);
      table(z,smoke.table,68,234,704,312,[396,138,170],24,1);
      txt(z,`${smoke.validated_decisions} / ${smoke.api_requests}`,828,181,370,96,70,C.cyan,true,ENGLISH);
      txt(z,`API 决策 schema 通过 · ${smoke.policy_rejections} 拒绝`,828,280,384,46,24,C.text);
      txt(z,smoke.status_summary,828,348,384,108,24,C.muted);
      txt(z,"1 个正确 UART 基线无仿真轮\n内部完整证据条件：未满足",828,468,384,79,24,C.text);
      txt(z,smoke.conclusion,68,570,1144,48,27,C.text,true);
      note(z,smoke.disclosure);
    }else{
      txt(z,"已完成",68,180,260,54,32,C.cyan,true);
      txt(z,"真实 RTL 仿真与独立判据\n逐周期功能场景证据\nAPI 补测与预算限制",68,253,595,180,32);
      txt(z,"继续验证",821,180,387,54,32,C.text,true);
      txt(z,"独立留出模块与多次重复\n真人任务计时与原始反馈\n独立人工复核和跨机重放",821,253,387,180,29,C.muted);
      rule(z,68,506,1138);
      txt(z,"覆盖和检出结论只适用于已执行输入及已审计参数\n真实失败、未知和中断记录与成功结果一起保留",68,539,1126,101,30);
    }
  }
}

const candidate=path.join(BUILD,`candidate-${VERSION}${DRAFT?"-draft":""}.pptx`);
await (await PresentationFile.exportPptx(deck)).save(candidate);
const exportDeck=DRAFT?deck:await (async()=>{
  const output=path.join(BUILD,"final",`defense-${VERSION}.pptx`);
  await fs.mkdir(path.dirname(output),{recursive:true});
  const result=await finalizePresentation({workspaceDir:BUILD,candidatePath:candidate,finalPath:output,
    pythonExecutable:PYTHON,integrityValidatorPath:path.join(SKILL,"container_tools/inspect_presentation_package_integrity.py"),
    layoutValidatorPath:path.join(SKILL,"container_tools/inspect_presentation_layout_geometry.py"),
    explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[4,5,9,11,12],requiredNativeChartOwnerSlides:[6,7,10],
    materializeLiteralChartWorkbooks:true,layoutArgs:["--expected-slide-size-emu","12192000,6858000","--cover-role","cover","--validate-heading-fit",...[4,5,9,11,12].flatMap(n=>["--require-native-table-slide",String(n)])],
    fontPolicy:{basis:"design",families:[FONT,ENGLISH]},verifyArtifactToolImport:true,
    receiptPath:path.join(BUILD,`defense-${VERSION}.validation.json`)});
  console.log(JSON.stringify(result));
  const final=await PresentationFile.importPptx(await FileBlob.load(output));
  await fs.copyFile(output,path.join(ROOT,"docs/competition/ic/ICARUS_答辩材料_v2.pptx"));
  return final;
})();
const preview=path.join(BUILD,`${VERSION}${DRAFT?"-draft":"-final"}`);await fs.mkdir(preview,{recursive:true});
const slideCount=exportDeck.slides.items.length;
for(let index=0;index<slideCount;index++){
  const page=exportDeck.slides.getItem(index);
  const png=await exportDeck.export({slide:page,format:"png",scale:2});
  await fs.writeFile(path.join(preview,`slide-${String(index+1).padStart(2,"0")}.png`),new Uint8Array(await png.arrayBuffer()));
  const layout=await page.export({format:"layout"});await fs.writeFile(path.join(preview,`slide-${String(index+1).padStart(2,"0")}.layout.json`),await layout.text());
}
await fs.writeFile(path.join(preview,"deck-inspect.ndjson"),(await exportDeck.inspect({kind:"slide,textbox,chart,table,image,notes",maxChars:100000})).ndjson);
if(!DRAFT){
  const pdf=path.join(ROOT,"docs/competition/ic/ICARUS_答辩材料_v2.pdf");
  const script=`from pathlib import Path\nimport sys\nfrom reportlab.pdfgen.canvas import Canvas\nfrom reportlab.lib.utils import ImageReader\nroot=Path(sys.argv[1])\nout=Path(sys.argv[2])\nc=Canvas(str(out),pagesize=(960,540),pageCompression=1)\nc.setAuthor('')\nc.setTitle('ICARUS 数字IP验证智能体')\nfor image in sorted(root.glob('slide-*.png')):\n c.drawImage(ImageReader(str(image)),0,0,width=960,height=540)\n c.showPage()\nc.save()\n`;
  execFileSync(PYTHON,["-c",script,preview,pdf],{stdio:"inherit",windowsHide:true});
}
console.log(JSON.stringify({slides:slideCount,candidate,preview,draft:DRAFT}));
