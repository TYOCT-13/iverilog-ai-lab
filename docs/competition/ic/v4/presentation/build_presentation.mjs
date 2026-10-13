import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";

// Local artifact authoring only. No API requests, credential reads or DUT runs.
const RUNTIME_NODE_MODULES = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
const RUNTIME_PYTHON = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const SKILL_DIR = "C:/Users/TYOCT/.codex/plugins/cache/openai-primary-runtime/presentations/26.1009.11318/skills/presentations";
process.env.RUNTIME_NODE_MODULES ||= RUNTIME_NODE_MODULES;
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(
  path.join(RUNTIME_NODE_MODULES, "@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../../../..");
const FIGURES = path.join(HERE, "../figures");
const REVISION = process.env.V4_PPT_REVISION || "r1";
if (!/^r[1-9][0-9]*$/.test(REVISION)) throw new Error("Use a fresh r<number> revision");
const BUILD = path.join(HERE, "build", REVISION);
const FINAL = path.join(HERE, "output", REVISION);
try { await fs.stat(BUILD); throw new Error("Revision already exists; preserve earlier attempts"); }
catch (e) { if (e.code !== "ENOENT") throw e; }
const AUTHOR = JSON.parse(await fs.readFile(path.join(HERE, "data.json"), "utf8"));
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const sourceBytes = await fs.readFile(path.join(ROOT, AUTHOR.material_source));
if (hash(sourceBytes) !== AUTHOR.material_source_sha256) throw new Error("Frozen material source changed");
const D = JSON.parse(sourceBytes), N = D.latest_new108, O = D.historical_v8_432, A = D.new108_audit;
function assertFact(ok, message) { if (!ok) throw new Error(message); }
assertFact(N.registered_tasks === 108 && N.executed_tasks === 108, "Latest full task scope");
assertFact(N.strategies.map(x => x.detected_samples).join(",") === "12,10,8,8,11,10", "Latest identity");
assertFact(O.strategies.map(x => x.detected_samples).join(",") === "48,32,48,29,37,37", "Historical identity");
assertFact(O.registered_tasks === 432 && O.executed_tasks === 414 && O.unexecuted_task_count === 18, "Historical failure denominator");
assertFact(N.requests === 87 && N.tokens.reported_tokens === 339624, "Latest usage");
assertFact(N.strategies.map(x => x.search_cycles_recorded).join(",") === "432,432,432,236,300,290", "Actual unequal stimulus use");
assertFact(N.audited_rounds === 134 && N.pipeline_sides === 268, "Latest executions");
assertFact(N.strict_comparison_eligible === true && O.strict_comparison_eligible === false, "Strict identities");
assertFact(D.new108_budget.reported_prompt_tokens + D.new108_budget.reported_completion_tokens === 339624, "Usage arithmetic");
const TALK = Object.fromEntries((await fs.readFile(path.join(HERE, "speaker_notes.md"), "utf8"))
  .split(/^## /m).slice(1).map(section => {
    const match = section.match(/^(\d{2})[^\n]*\n([\s\S]*)$/);
    if (!match) throw new Error("Malformed notes");
    return [Number(match[1]), match[2].trim()];
  }));
assertFact(Object.keys(TALK).length === AUTHOR.slide_count, "All speaker notes");
const assetNames = AUTHOR.slides.flatMap(s => s.figure ? [s.figure] : []);
const assetBytes = new Map();
for (const name of assetNames) assetBytes.set(name, await fs.readFile(path.join(FIGURES, name + ".png")));
const evidenceBytes=new Map();
for(const item of AUTHOR.evidence_images)evidenceBytes.set(item.key,{...item,bytes:await fs.readFile(path.join(ROOT,item.path))});
// Check all figures before creating a build directory. Missing images never become placeholders.
await fs.mkdir(BUILD, { recursive: true });
await fs.mkdir(FINAL, { recursive: true });
await fs.writeFile(path.join(BUILD, "material_data.original.json"), sourceBytes, { flag: "wx" });
const trialBytes = await fs.readFile(path.join(ROOT, AUTHOR.current_facts.human_trial_source));
await fs.writeFile(path.join(BUILD, "other_pc_user_trial.original.md"), trialBytes, { flag: "wx" });
await fs.writeFile(path.join(BUILD, "source_checksums.json"), JSON.stringify({
  schema: "icarus-ic-v4-presentation-sources-v1", material_source: AUTHOR.material_source,
  material_sha256: hash(sourceBytes), trial_source: AUTHOR.current_facts.human_trial_source,
  trial_sha256: hash(trialBytes), figures: [...assetBytes].map(([name, bytes]) => ({name, sha256:hash(bytes), bytes:bytes.length})),
  evidence_images:[...evidenceBytes.values()].map(item=>({key:item.key,path:item.path,sha256:hash(item.bytes),bytes:item.bytes.length})),
  current_facts: AUTHOR.current_facts, new_API_requests:0, credential_reads:0, DUT_executions:0
}, null, 2) + "\n", {flag:"wx"});

const FONT = resolvePresentationFont({fontFamily:AUTHOR.design.body_font});
const ENGLISH = resolvePresentationFont({fontFamily:AUTHOR.design.display_font});
const C = { bg:"#F5F7F8", white:"#FFFFFF", text:"#182025", muted:"#53636B", cyan:"#00ABC8", line:"#C9D3D8", dark:"#1C2023", light:"#F1F3F4", darkMuted:"#B3BDC2", grey:"#75858D" };
const deck = Presentation.create({slideSize:{width:1280,height:720}});
deck.theme.colorScheme = {name:"ICARUS industrial cyan",themeColors:{accent1:C.cyan,accent2:C.grey,accent3:C.muted,accent4:"#DDE6E9",accent5:C.dark,accent6:"#8FA2AC",bg1:C.bg,bg2:C.dark,tx1:C.text,tx2:C.muted,dk1:C.text,dk2:C.dark,lt1:C.white,lt2:C.bg,hlink:C.cyan,folHlink:C.cyan}};
function txt(s,text,x,y,w,h,size=28,color=C.text,bold=false,family=FONT,name="") {
  const sh=s.shapes.add({geometry:"textbox",name:name||String(text).slice(0,40),position:{left:x,top:y,width:w,height:h},fill:"none",line:{fill:"none",width:0}});
  sh.text=String(text);sh.text.style={typeface:family,fontSize:size,color,bold,autoFit:"none",verticalAlignment:"top",wrap:true};return sh;
}
function rule(s,x,y,w,color=C.line,width=1) { return s.shapes.add({geometry:"line",position:{left:x,top:y,width:w,height:0},fill:"none",line:{fill:color,width}}); }
function note(s,n,extra="") {
  s.speakerNotes.textFrame.setText(TALK[n]+"\n\n事实源："+AUTHOR.material_source+"\nSHA-256："+AUTHOR.material_source_sha256+
    "\n最新原件："+D.sources.new108_receipt.path+"\n历史原件："+D.sources.old432_receipt.path+"\n异机记录："+AUTHOR.current_facts.human_trial_source+"\n"+extra);
}
function slide(n,title,statement="") {
  const s=deck.slides.add();s.background.fill=C.bg;
  txt(s,title,64,44,1080,67,46,C.text,true);
  txt(s,String(n).padStart(2,"0"),1163,47,60,52,32,C.cyan,true,ENGLISH);
  rule(s,64,127,1152);
  if(statement) txt(s,statement,64,153,1152,54,32,C.text,true);
  note(s,n);return s;
}
function foot(s,text) { txt(s,text,64,638,1152,48,22,C.muted); }
function image(s,name,y=166,h=422) {
  const bytes=assetBytes.get(name);if(!bytes)throw new Error("No asset:"+name);
  return s.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:"image/png",alt:AUTHOR.slides.find(x=>x.figure===name)?.purpose||name,fit:"contain",position:{left:64,top:y,width:1152,height:h}});
}
function figureSlide(n,title,statement,asset,footer) { const s=slide(n,title);image(s,asset);foot(s,footer);return s; }
function evidenceImage(s,key,position,crop=null){
  const item=evidenceBytes.get(key),bytes=item.bytes;
  return s.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:item.path.endsWith(".jpg")?"image/jpeg":"image/png",alt:item.alt,fit:"contain",position,...(crop?{crop}:{})});
}
function table(s,values,x,y,w,h,widths,size=27) {
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,values,columnWidths:widths});
  t.borders.assign({fill:C.line,width:1,style:"solid"});
  t.rows[0].height=55;
  for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++) {
    const cell=t.getCell(r,c);cell.fill=r===0?C.dark:C.white;
    cell.text.style={typeface:FONT,fontSize:r===0?25:size,color:r===0?C.light:C.text,bold:r===0,wrap:true};
  }
  return t;
}
function bar(s,categories,values,x,y,w,h,max,major) {
  const chart=s.charts.add("bar",{position:{left:x,top:y,width:w,height:h},categories:[...categories].reverse(),series:[{name:"检出缺陷任务",values:[...values].reverse(),fill:C.grey,points:[{idx:categories.length-1-4,fill:C.cyan}]}],barOptions:{direction:"bar",grouping:"clustered",gapWidth:58},hasLegend:false,chartFill:C.bg,plotAreaFill:C.bg,chartLine:{fill:"none"},plotAreaLine:{fill:"none"},xAxis:{visible:true,textStyle:{typeface:FONT,fontSize:26,fill:C.text},line:{fill:"none"},majorGridlines:null},yAxis:{visible:true,min:0,max,majorUnit:major,numberFormatCode:"0",textStyle:{typeface:FONT,fontSize:23,fill:C.muted},line:{fill:C.line,width:1},majorGridlines:{fill:C.line,width:0.7}},dataLabels:{showValue:true,position:"outEnd",textStyle:{typeface:FONT,fontSize:29,bold:true,fill:C.text}}});
  applyPresentationChartFont(chart,{fontFamily:FONT});return chart;
}

{
  const s=deck.slides.add();s.background.fill=C.dark;
  txt(s,"ICARUS",64,89,1120,150,126,C.light,true,ENGLISH);
  txt(s,"数字 IP 验证智能体",68,273,1080,80,50,C.light,true);
  txt(s,"AI 测试探索与真实仿真证据",68,387,1110,65,37,C.darkMuted);
  rule(s,68,520,1000,C.cyan,4);
  txt(s,"AI+集成电路",68,574,900,54,30,C.cyan,true);
  txt(s,"2026-10-13",68,642,1020,35,24,C.darkMuted,false,ENGLISH);
  note(s,1);
}
figureSlide(2,"数字 IP 的时序验证需求","验证需要覆盖连续周期中的边界行为","theme_map","需求来自公开合约、实际执行和用户问题记录");
figureSlide(3,"测试探索与独立裁决","AI 负责提议输入，独立判据决定结果","architecture","第三方 DeepSeek API（4.1f），没有训练或微调模型权重");
figureSlide(4,"验证链路的迭代过程","每轮修改都对应一类已记录的问题","timeline","各实验批次独立保留，迭代路线不代表 AI 效果增长曲线");
figureSlide(5,"规格与接口前置校验","缺少依赖和输出判据会阻断有效验证","preflight","先校验接口与依赖，再生成计划和执行仿真");
figureSlide(6,"有界测试规划","模型提案先通过格式、接口和预算约束","planner","补提仍收费，并占用原任务共享请求上限");
figureSlide(7,"FIFO 独立队列判据","同时接受读写时，占用量应保持不变","oracle_fifo","历史规格修复案例：76 拍、228 次比较，差异 66 减至 0");
figureSlide(8,"带真实端口事实的反馈循环","有限端口采样支持下一轮输入探索","agent_loop","保存 80 份端口文档，实际发给模型的反馈 STATE 为 20 个");
figureSlide(9,"请求预算与付费失败留存","用量、拒绝和终态失败进入同一账本","token_ledger","最新批次 87 请求、339,624 reported tokens，保留 1 项终态格式失败");
{
  const s=slide(10,"最新 108 任务的对照设计","两个新内部模块，六策略使用统一登记集合");
  table(s,[["模块","公开合约要点","目标与重复"],["valid/data 流水线","两级对齐、flush 优先","正确 / B / C，各 3 次"],["事件累计器","模 16 回绕、clear 优先","正确 / B / C，各 3 次"]],64,245,1152,225,[296,486,370],27);
  txt(s,"2 模块 × 3 目标 × 3 重复 × 6 策略 = 108 任务",64,508,1152,58,35,C.cyan,true);
  txt(s,"每策略 12 缺陷任务，另有 6 正确任务",64,576,1152,47,29,C.text);
  foot(s,"同团队合成集合，未提供外部盲测或预训练未见证明");
}
{
  const s=slide(11,"最新批次的六策略检出","反馈 11/12，仅比随机与无反馈各多 1 项");
  bar(s,N.strategies.map(x=>x.label),N.strategies.map(x=>x.detected_samples),64,223,835,363,12,3);
  txt(s,"11 / 12",951,228,263,104,75,C.cyan,true,ENGLISH);
  txt(s,"反馈 Agent",951,332,263,48,28,C.text,true);
  txt(s,"36 / 36",951,417,263,71,47,C.text,true,ENGLISH);
  txt(s,"正确任务实际执行\n0 实际误报",951,493,263,79,25,C.muted);
  txt(s,"差异尚不支持显著性、因果或工业普适收益",64,597,1152,42,29,C.text,true);
  foot(s,"共同 24 拍上限，single 最多 1 请求、Agent 最多 3 请求，实际耗费不同");
}
{
  const s=slide(12,"历史 432 任务的完整记录","历史反馈 37/48，与无反馈相同");
  bar(s,O.strategies.map(x=>x.label),O.strategies.map(x=>x.detected_samples),64,223,835,363,48,12);
  txt(s,"18",951,228,263,99,76,C.cyan,true,ENGLISH);
  txt(s,"任务无 DUT 执行",951,333,263,68,27,C.text,true);
  txt(s,"strict=false",951,426,263,54,31,C.text,true,ENGLISH);
  txt(s,"306 请求\n973,149 tokens",951,503,263,83,25,C.muted,false,ENGLISH);
  txt(s,"反馈未超过固定与协议随机 48/48",64,597,1152,42,29,C.text,true);
  foot(s,"每策略完整缺陷分母 48，两批模块、预算和分母分别报告");
}
{
  const s=slide(13,"执行记录与原件绑定","安全原文和执行记录进入证据链");
  const stages=[{x:64,t:"冻结输入\n458 项"},{x:365,t:"实际执行与请求\n4,359 raw 文件"},{x:666,t:"manifest 与 ZIP\n原字节绑定"},{x:967,t:"逐项机器审计\n保留失败"}];
  const nodes=stages.map(a=>txt(s,a.t,a.x,239,240,100,29,C.text,true));
  for(let i=0;i<nodes.length-1;i++)s.shapes.connect(nodes[i],nodes[i+1],{kind:"straight",fromSide:"right",toSide:"left",line:{fill:C.cyan,width:2},tail:{type:"arrow",width:"sm",length:"sm"}});
  table(s,[["审计范围","记录量","身份"],["核心审计","2,192 项机器检查","非实现者代理"],["轨迹审计","54 轨迹、87 请求","实验 entry 代码作者"]],64,378,1152,190,[265,490,397],27);
  txt(s,"机器审计非独立人工 H02",64,591,1152,43,31,C.text,true);
  foot(s,"最新 strict=true 表示证据资格，134 round / 268 DUT 与参考执行侧");
}
figureSlide(14,"跨平台运行与工程检查","工具自动发现减少开发机路径假设","engineering","历史提交 216438d 的 5 jobs 全绿，当前 df7ccfa 云端检查未通过");
figureSlide(15,"真实异机操作中的卡点","11 类问题来自一次真实 AI 辅助操作","user_trial","两次上传均编译失败，没有仿真比较或 VCD，用户复测仍待确认");
figureSlide(16,"异机反馈推动的产品修改","界面入口与运行前校验形成明确操作顺序","product_changes","修改已发布，尚无用户在该电脑使用新版本成功复测的证据");
{
  const s=slide(17,"AI 与 IC 验证的工程结合","贡献集中于模型建议到执行证据的连接");
  table(s,[["结合点","已实现的机制","针对的问题"],["公开规格与独立判据","接口约束、逐拍 oracle","无效输入与共享实现错误"],["有界模型动作","严格格式、共享请求预算","失败恢复造成无界请求"],["可核对的执行记录","原文、账本、manifest 绑定","选择性留存与结果难复核"],["真实操作反馈","依赖预查、入口与状态提示","异机环境和下一步不清楚"]],64,229,1152,336,[276,426,450],26);
  txt(s,"更广泛的效果仍需独立模块、复测与成本对照",64,594,1152,43,29,C.text,true);
  foot(s,"本项目没有证明反馈的显著收益，也没有量化工业普适提升");
}
figureSlide(18,"后续验证与交付路线","复测与独立审核需要新的真实证据","roadmap","官方截止：2026-10-30 20:00 北京时间，答辩交 PDF，编辑使用 PPTX");
{
  const s=slide(19,"附录 A  规格时序示例","两模块正确 A 规格的正常操作片段");
  txt(s,"valid/data 流水线",64,221,550,44,28,C.text,true);
  txt(s,"事件累计器",664,221,550,44,28,C.text,true);
  evidenceImage(s,"pipeline_wave",{left:64,top:282,width:550,height:298});
  evidenceImage(s,"accumulator_wave",{left:664,top:282,width:550,height:298});
  txt(s,"E0 捕获、E1 输出，flush 优先",64,584,550,41,24,C.muted);
  txt(s,"clear 优先，4 bit 计数",664,584,550,41,24,C.muted);
  foot(s,"已有规格渲染截图，非 VCD、非新增 DUT 验证，未展示场景不构成验证结论");
}
{
  const s=slide(20,"附录 B  实际浏览器界面","今天的界面观察与编译预检查");
  txt(s,"默认在线模型",64,219,530,40,27,C.text,true);
  txt(s,"校验前计划生成禁用",640,219,574,40,27,C.text,true);
  evidenceImage(s,"onboarding_ui",{left:64,top:275,width:530,height:200},{left:0.03,top:0.31,right:0.47,bottom:0.31});
  evidenceImage(s,"upload_ui",{left:64,top:491,width:530,height:130},{left:0.037,top:0.785,right:0.565,bottom:0.034});
  evidenceImage(s,"upload_ui",{left:640,top:275,width:574,height:346},{left:0.47,top:0.26,right:0.025,bottom:0.115});
  foot(s,"仅 UI 观察与 -tnull 预检，0 API，未生成计划或仿真，未确认真人复测");
}

// Add slide-specific source URLs after authoring the content.
deck.slides.getItem(13).speakerNotes.textFrame.setText(TALK[14]+"\n\n历史验证："+AUTHOR.current_facts.historical_verify_url+"\n历史CI："+AUTHOR.current_facts.historical_ci_url+"\n当前验证："+AUTHOR.current_facts.current_verify_url+"\n当前CI："+AUTHOR.current_facts.current_ci_url+"\n本轮核验日期：2026-10-13");
deck.slides.getItem(17).speakerNotes.textFrame.setText(TALK[18]+"\n\n官方通知："+AUTHOR.current_facts.official_notice+"\n规则PDF："+D.rules.rules_pdf+"\n参考大纲PDF："+D.rules.outline_pdf+"\n当前截止信息已于2026-10-13重新核验，优先于2026-10-05历史材料日期");
assertFact(deck.slides.items.length===AUTHOR.slide_count,"Slide count");
const candidate=path.join(BUILD,"candidate.pptx");
await (await PresentationFile.exportPptx(deck)).save(candidate);
console.log(JSON.stringify({stage:"candidate",slides:AUTHOR.slide_count,candidate}));
const finalPptx=path.join(FINAL,"ICARUS_AI_IC_defense_v4_"+REVISION+".pptx");
const tables=AUTHOR.design.native_table_owner_slides, charts=AUTHOR.design.native_chart_owner_slides;
const finalization=await finalizePresentation({workspaceDir:HERE,candidatePath:candidate,finalPath:finalPptx,pythonExecutable:RUNTIME_PYTHON,integrityValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_package_integrity.py"),layoutValidatorPath:path.join(SKILL_DIR,"container_tools/inspect_presentation_layout_geometry.py"),explicitTotalSlideCount:AUTHOR.slide_count,requiredNativeTableOwnerSlides:tables,requiredNativeChartOwnerSlides:charts,materializeLiteralChartWorkbooks:true,layoutArgs:["--expected-slide-size-emu","12192000,6858000","--cover-role","cover","--validate-heading-fit",...tables.flatMap(n=>["--require-native-table-slide",String(n)])],fontPolicy:{basis:"design",families:[FONT,ENGLISH]},verifyArtifactToolImport:true,receiptPath:path.join(BUILD,"validation.json")});
console.log(JSON.stringify({stage:"finalized",result:finalization}));
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(finalPptx));
const preview=path.join(BUILD,"final-render");await fs.mkdir(preview,{recursive:true});
for(let i=0;i<finalDeck.slides.items.length;i++){
  const page=finalDeck.slides.getItem(i),stem="slide-"+String(i+1).padStart(2,"0");
  const png=await finalDeck.export({slide:page,format:"png",scale:2});
  await fs.writeFile(path.join(preview,stem+".png"),new Uint8Array(await png.arrayBuffer()),{flag:"wx"});
  const layout=await page.export({format:"layout"});
  await fs.writeFile(path.join(preview,stem+".layout.json"),await layout.text(),{flag:"wx"});
  console.log(JSON.stringify({stage:"rendered",slide:i+1}));
}
await fs.writeFile(path.join(preview,"deck-inspect.ndjson"),(await finalDeck.inspect({kind:"slide,textbox,shape,image,chart,table,notes",maxChars:500000})).ndjson,{flag:"wx"});
let finalPdf=null,pdfError=null,pdfMode="native";
try {
  const pdf=await finalDeck.export({format:"pdf"});
  finalPdf=path.join(FINAL,"ICARUS_AI_IC_defense_v4_"+REVISION+".pdf");
  await fs.writeFile(finalPdf,new Uint8Array(await pdf.arrayBuffer()),{flag:"wx"});
} catch(e) {
  pdfError=String(e);console.log(JSON.stringify({stage:"pdf_export_unavailable",error:pdfError}));
  finalPdf=path.join(FINAL,"ICARUS_AI_IC_defense_v4_"+REVISION+".pdf");
  execFileSync(RUNTIME_PYTHON,[path.join(HERE,"export_image_pdf.py"),preview,finalPdf,path.join(BUILD,"pdf_receipt.json"),String(AUTHOR.slide_count)],{stdio:"inherit",windowsHide:true});
  pdfMode="image_only_from_final_artifact_tool_render";
}
assertFact(hash(await fs.readFile(path.join(ROOT,AUTHOR.material_source)))===AUTHOR.material_source_sha256,"Material changed during build");
const result={schema:"icarus-ic-v4-presentation-build-result-v1",revision:REVISION,slides:AUTHOR.slide_count,finalPptx,finalPdf,pdfMode,pdfError,preview,receipt:path.join(BUILD,"validation.json"),native_chart_owner_slides:charts,native_table_owner_slides:tables,materials_only:true,new_API_requests:0,credential_reads:0,DUT_executions:0,engineering_tests_reexecuted:0,native_Office_validation:false};
await fs.writeFile(path.join(BUILD,"build_result.json"),JSON.stringify(result,null,2)+"\n",{flag:"wx"});
console.log(JSON.stringify({stage:"complete",...result}));
