import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";

// Installed Codex runtime only. No vendored dependencies or provider imports.
const RUNTIME_NODE_MODULES = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";
process.env.RUNTIME_NODE_MODULES ||= RUNTIME_NODE_MODULES;
const { Presentation, PresentationFile, FileBlob } = await import(pathToFileURL(
  path.join(RUNTIME_NODE_MODULES, "@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "../../../..");
const SKILL = "C:/Users/TYOCT/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations";
const PYTHON = "C:/Users/TYOCT/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
const { resolvePresentationFont, applyPresentationChartFont, finalizePresentation } = await import(
  pathToFileURL(path.join(SKILL, "container_tools/artifact_tool_utils.mjs")).href);
const REVISION = process.env.DEFENSE_V3_REVISION || "r1";
if (!/^r[1-9][0-9]*$/.test(REVISION)) throw new Error("Use a fresh r<number> revision");
const BUILD_ROOT = path.join(ROOT, ".iverilog-ai/defense-v3-build");
const BUILD = path.join(BUILD_ROOT, REVISION);
try { await fs.stat(BUILD); throw new Error("Revision already exists; preserve original attempt"); }
catch (error) { if (error.code !== "ENOENT") throw error; }
await fs.mkdir(BUILD, {recursive: true});
process.chdir(BUILD);
const authorRaw = await fs.readFile(path.join(HERE, "data.json"));
const AUTHOR = JSON.parse(authorRaw);
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
const materialRaw = await fs.readFile(path.join(ROOT, AUTHOR.material_source));
if (hash(materialRaw) !== AUTHOR.material_source_sha256) throw new Error("Final material source SHA changed");
const D = JSON.parse(materialRaw);
const N = D.latest_new108, O = D.historical_v8_432, A = D.new108_audit, B = D.new108_budget, E = D.latest_engineering;
const firstDetectionRounds = JSON.parse(await fs.readFile(path.join(ROOT,D.sources.new108_receipt.path),"utf8")).first_detection_rounds;
function requireFact(ok, message) { if (!ok) throw new Error(message); }
requireFact(N.registered_tasks === 2*3*3*6 && N.executed_tasks === N.registered_tasks, "New full task scope");
requireFact(N.strategies.every(s => s.registered_defect_samples === 4*3), "New defect denominator");
requireFact(B.reported_prompt_tokens+B.reported_completion_tokens === N.tokens.reported_tokens, "Token arithmetic");
requireFact(N.schema_counts.passed + N.schema_counts.rejected === N.requests, "Paid schema denominator");
requireFact(A.json_parseable_responses+1 === A.raw_response_files && A.raw_response_missing === 0, "Raw reply classification");
requireFact(N.pipeline_sides === 2*N.audited_rounds, "Actual episode sides");
requireFact(O.executed_tasks+O.unexecuted_task_count === O.registered_tasks, "Old failed-task denominator");
requireFact(Object.values(N.correct_controls).reduce((sum, c)=>sum+c.executed,0) === 36, "Correct controls");
requireFact(N.strategies.map(s=>s.detected_samples).join(",")==="12,10,8,8,11,10", "Frozen new result identity");
requireFact(O.strategies.map(s=>s.detected_samples).join(",")==="48,32,48,29,37,37", "Frozen old result identity");
const talkSource = await fs.readFile(path.join(HERE, "speaker_notes.md"), "utf8");
const TALK = Object.fromEntries(talkSource.split(/^## /m).slice(1).flatMap(section=>{
  const match=section.match(/^(\d{2})[^\n]*\n([\s\S]*)$/);
  return match ? [[Number(match[1]), match[2].trim()]] : [];
}));
requireFact(Object.keys(TALK).length === 12, "Twelve real slide notes");
const FONT = resolvePresentationFont({fontFamily: AUTHOR.design.body_font});
const ENGLISH = resolvePresentationFont({fontFamily: AUTHOR.design.display_font});
const C = {bg:"#1C2023", black:"#111517", text:"#F1F3F4", muted:"#B3BDC2", cyan:"#00C8E8", grey:"#738188", line:"#566168"};
const sourcePaths = new Map([[AUTHOR.material_source, {key:"final_material_data", expected:AUTHOR.material_source_sha256}]]);
for (const [key,item] of Object.entries(D.sources)) sourcePaths.set(item.path,{key,expected:item.sha256,expectedBytes:item.bytes});
for (const relative of D.source_documents) sourcePaths.set(relative,{key:"source_document"});
for (const [key,relative] of Object.entries(AUTHOR.extra_original_sources)) sourcePaths.set(relative,{key});
for (const file of ["data.json","build_defense.mjs","speaker_notes.md","qa_questions.md","strip_pptx_metadata.py","create_image_pdf.py","inspect_artifacts.py","assets/README.md"]) {
  sourcePaths.set(path.relative(ROOT,path.join(HERE,file)).replaceAll("\\","/"),{key:"authoring_source"});
}
const sourceItems = [];
for (const [relative,declared] of sourcePaths) {
  const target=path.resolve(ROOT,relative);
  requireFact(target.startsWith(ROOT+path.sep),"Source outside project");
  const bytes=await fs.readFile(target);
  requireFact(!declared.expected || hash(bytes)===declared.expected,"Source original SHA mismatch");
  requireFact(declared.expectedBytes===undefined || bytes.length===declared.expectedBytes,"Source original byte size mismatch");
  const copy=path.join(BUILD,"source-snapshot",relative);
  await fs.mkdir(path.dirname(copy),{recursive:true});
  await fs.writeFile(copy,bytes,{flag:"wx"});
  sourceItems.push({key:declared.key,relative_path:relative,sha256:hash(bytes),size_bytes:bytes.length,
    private_snapshot:path.relative(ROOT,copy).replaceAll("\\","/")});
}
await fs.writeFile(path.join(BUILD,"source_checksums.json"),JSON.stringify({
  schema:"icarus-defense-v3-source-byte-snapshot-v1",captured_at_utc:new Date().toISOString(),revision:REVISION,
  material_source_sha256:hash(materialRaw),evidence_base_commit:D.evidence_base_commit,
  live_API_requests:0,credential_file_reads:0,DUT_executions:0,engineering_tests_reexecuted:0,
  independent_human_review:false,items:sourceItems},null,2)+"\n",{flag:"wx"});
await fs.writeFile(path.join(BUILD,"material_data.original.json"),materialRaw,{flag:"wx"});

const deck=Presentation.create({slideSize:{width:1280,height:720}});
deck.theme.colorScheme={name:"ICARUS charcoal cyan",themeColors:{
  accent1:C.cyan,accent2:C.grey,accent3:C.muted,accent4:"#CFD8DC",accent5:"#343C40",accent6:"#7A858A",
  bg1:C.bg,bg2:C.black,tx1:C.text,tx2:C.muted,dk1:C.black,dk2:C.bg,lt1:C.text,lt2:"#D0D9DD",hlink:C.cyan,folHlink:C.cyan
}};
function txt(s,text,x,y,w,h,size=28,color=C.text,bold=false,family=FONT,name=""){
  const box=s.shapes.add({geometry:"textbox",name:name||String(text).slice(0,32),
    position:{left:x,top:y,width:w,height:h},fill:"none",line:{fill:"none",width:0}});
  box.text=String(text);
  box.text.style={typeface:family,fontSize:size,color,bold,autoFit:"none",verticalAlignment:"top",wrap:true};
  return box;
}
function rule(s,x,y,w,color=C.line,thickness=1){
  return s.shapes.add({geometry:"line",position:{left:x,top:y,width:w,height:0},fill:"none",line:{fill:color,width:thickness}});
}
function notes(s,number,extra=""){
  const source=D.sources.new108_receipt.path;
  s.speakerNotes.textFrame.setText(TALK[number]+"\n\n材料事实源："+AUTHOR.material_source+
    "\n事实源 SHA-256："+AUTHOR.material_source_sha256+"\n主要原件："+source+"\n"+extra);
}
function slide(number,title){
  const s=deck.slides.add();s.background.fill=C.bg;
  txt(s,title,64,46,1060,70,46,C.text,true);
  rule(s,64,131,1150);
  txt(s,String(number).padStart(2,"0"),1158,48,64,54,34,C.cyan,true,ENGLISH);
  notes(s,number);
  return s;
}
function foot(s,text,y=630){txt(s,text,64,y,1150,62,23,C.muted);}
function table(s,values,x,y,w,h,widths,size=27,accentColumn=null){
  const t=s.tables.add({rows:values.length,columns:values[0].length,left:x,top:y,width:w,height:h,
    values,columnWidths:widths});
  t.borders.assign({fill:C.line,width:1,style:"solid"});
  for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){
    const cell=t.getCell(r,c);cell.fill=r===0?C.black:C.bg;
    const numeric=r>0 && /^[0-9, /]+$/.test(String(values[r][c]));
    cell.text.style={typeface:FONT,fontSize:r===0?25:size,
      color:numeric&&(accentColumn===null||accentColumn===c)?C.cyan:C.text,bold:r===0};
  }
  return t;
}
function metric(s,value,label,x,y,w,size=86){
  txt(s,value,x,y,w,115,size,C.cyan,true,ENGLISH);
  txt(s,label,x,y+120,w,100,28,C.text);
}
function bar(s,categories,values,x,y,w,h,max,major=3,points=[]){
  const chart=s.charts.add("bar",{position:{left:x,top:y,width:w,height:h},
    categories:[...categories].reverse(),series:[{name:"实际观测",values:[...values].reverse(),
      fill:C.grey,points:points.map(p=>({...p,idx:categories.length-1-p.idx}))}],
    barOptions:{direction:"bar",grouping:"clustered",gapWidth:62},
    hasLegend:false,chartFill:C.bg,plotAreaFill:C.bg,chartLine:{fill:"none"},plotAreaLine:{fill:"none"},
    xAxis:{visible:true,textStyle:{typeface:FONT,fontSize:25,fill:C.text},line:{fill:"none"},majorGridlines:null},
    yAxis:{visible:true,min:0,max,majorUnit:major,numberFormatCode:"0",
      textStyle:{typeface:FONT,fontSize:22,fill:C.muted},line:{fill:C.line,width:1},
      majorGridlines:{fill:C.line,width:0.5}},
    dataLabels:{showValue:true,position:"outEnd",textStyle:{typeface:FONT,fontSize:29,bold:true,fill:C.text}}
  });
  applyPresentationChartFont(chart,{fontFamily:FONT});
  return chart;
}

// 01 Typography-led anonymous cover; no fabricated image or team identity.
{
  const s=deck.slides.add();s.background.fill=C.bg;
  txt(s,"ICARUS",64,86,1060,162,126,C.text,true,ENGLISH);
  txt(s,"数字 IP 验证智能体",68,264,1090,83,49,C.text,true);
  txt(s,"第三方 API 建议测试输入\n真实 Icarus 仿真与独立判据核验",68,380,1000,108,32,C.muted);
  rule(s,68,531,950,C.cyan,4);
  txt(s,"AI+集成电路    2026-10-05",68,593,1010,53,27,C.muted);
  notes(s,1,"不使用虚构机构、队号、签字或真人参与记录");
}
// 02 Concrete public-interface needs.
{
  const s=slide(2,"数字 IP 的验证需求");
  txt(s,"可运行的输入仍可能遗漏时序边界",68,178,1110,69,40,C.text,true);
  txt(s,"valid/data 流水线",68,291,524,55,34,C.cyan,true);
  txt(s,"两级延迟与 valid/data 对齐\nflush 优先、invalid 数据归零",68,365,532,134,30);
  txt(s,"事件累计器",719,291,490,55,34,C.cyan,true);
  txt(s,"使能条件与模 16 回绕\nclear 不受 enable 限制",719,365,490,134,30);
  rule(s,68,526,1138);
  txt(s,"使用对象：数字电路学习者、小型 IP 开发者、技术复核人员",68,563,1120,54,28);
  foot(s,"需求来自本项目合约与执行记录。未提供行业访谈人数或真人计时结果");
}
// 03 Requested native editable architecture with real information boundaries.
{
  const s=slide(3,"API 规划与仿真裁决");
  const stages=[
    {x:68,w:204,text:"正确规格\n完整合约"},
    {x:303,w:204,text:"第三方 API\n提议输入"},
    {x:538,w:204,text:"权限与预算\n检查"},
    {x:773,w:204,text:"真实 Icarus\n实际执行"},
    {x:1008,w:204,text:"独立判据\n逐拍比较"}
  ];
  const nodes=stages.map(a=>txt(s,a.text,a.x,227,a.w,107,31,C.text,true));
  for(let i=0;i<nodes.length-1;i++)s.shapes.connect(nodes[i],nodes[i+1],
    {kind:"straight",fromSide:"right",toSide:"left",line:{fill:C.cyan,width:2},
      tail:{type:"arrow",width:"sm",length:"sm"}});
  rule(s,68,375,1138);
  txt(s,"模型接收",68,425,230,54,28,C.cyan,true);
  txt(s,"公开接口、自己的计划、剩余预算\n实际执行摘要与绑定的端口采样",303,416,905,108,30);
  txt(s,"模型动作",68,555,230,54,28,C.cyan,true);
  txt(s,"追加输入或停止",303,548,905,65,34,C.text,true);
  foot(s,"目标 RTL、私有变体标签、路径和 witness 不进入 API。正确 RTL 逐 episode 独立重放");
}
// 04 Cohort geometry and editable public-contract table.
{
  const s=slide(4,"新内部模块集合留出");
  txt(s,"108 项全部实际执行",68,171,1114,65,42,C.text,true);
  table(s,[["新模块","公开合约要点","目标与重复"],
    ["valid/data 流水线","8 bit、两级、flush 优先","正确 / B / C，各 3 次"],
    ["事件累计器","4 bit 模 16、clear 优先","正确 / B / C，各 3 次"]],
    68,271,1138,215,[270,490,378],27);
  txt(s,"2 模块 × 3 目标 × 3 重复 × 6 策略 = 108 任务",68,522,1138,58,33,C.cyan,true);
  foot(s,"每策略 4 不同缺陷 × 3 重复 = 12 缺陷任务，另有 6 正确任务\n同团队合成设计，无独立选型时间戳、外部盲测或预训练未见证明",606);
}
// 05 Shared caps and actual payment usage.
{
  const s=slide(5,"共享请求与执行预算");
  metric(s,N.tokens.reported_tokens.toLocaleString("en-US"),"reported tokens\n独立单批上限 1,000,000",68,177,390,76);
  txt(s,N.requests+" 次收费请求",68,425,383,55,31,C.text,true);
  txt(s,"输入 "+B.reported_prompt_tokens.toLocaleString("en-US")+"\n输出 "+B.reported_completion_tokens.toLocaleString("en-US"),68,493,383,91,27,C.muted);
  table(s,[["统一约束","单次 API","反馈 / 无反馈"],
    ["共享请求上限","1","3"],
    ["实际 episode 上限","1","3"],
    ["累计刺激拍上限","24","24"],
    ["每次提案 / 累计接受","12 / 64","12 / 64"]],
    493,181,714,331,[330,150,234],26);
  txt(s,"格式与预算补提仍收费，共用原任务上限",493,548,712,72,28,C.text,true);
  foot(s,"0 unknown / pending，0 自动传输重试。自动复位与正确 RTL 重放成本单列");
}
// 06 Literal native chart, common defect denominator only.
{
  const s=slide(6,"新108任务的六策略检出");
  bar(s,N.strategies.map(x=>x.label),N.strategies.map(x=>x.detected_samples),
    68,191,804,383,12,3,[{idx:0,fill:"#BBC8CE"},{idx:4,fill:C.cyan}]);
  metric(s,"11 / 12","反馈 Agent",929,188,283,73);
  txt(s,"固定测试 12 / 12 最好\n随机与无反馈各 10 / 12",929,391,286,92,25,C.text);
  txt(s,"反馈：首轮 "+firstDetectionRounds.feedback["1"]+" / 次轮 "+firstDetectionRounds.feedback["2"]+"\n无反馈：首轮 "+firstDetectionRounds.no_feedback["1"]+" / 后续 "+((firstDetectionRounds.no_feedback["2"]||0)+(firstDetectionRounds.no_feedback["3"]||0)),929,494,286,80,25,C.muted);
  txt(s,"仅多检出 1 项，不支持因果或显著性",68,582,1130,48,31,C.text,true);
  foot(s,"分母：4 不同缺陷 × 3 重复 = 12。另有 36/36 正确实际执行，0 实际误报");
}
// 07 Preserved episode feedback versus paid states sent to the model.
{
  const s=slide(7,"实际端口事实与无反馈对照");
  metric(s,String(A.actual_feedback_states_with_ports),"已发送 feedback STATE\n带真实端口事实",68,183,385,94);
  table(s,[["证据口径","实际值"],
    ["保存的端口文档",String(A.port_documents)],
    ["原始 / 返回 / 省略采样",A.port_raw_finite_samples+" / "+A.port_returned_samples+" / "+A.port_omitted_samples],
    ["模型实际收到返回 / 省略",A.actual_sent_feedback_returned_samples+" / "+A.actual_sent_feedback_omitted_samples]],
    506,193,703,277,[485,218],27);
  txt(s,"每份最多 12 个端点与等间隔样本，保留省略和 X/Z",68,522,1138,54,28,C.text,true);
  txt(s,A.no_feedback_states+" 个无反馈 STATE 的三项诊断全部 None",68,584,1140,49,29,C.cyan,true);
  foot(s,"自身计划、预算与执行器早停仍保留。两新模块覆盖 unsupported/unknown，未补造 bins",642);
}
// 08 Paid failures remain auditable, including terminal format failure after execution.
{
  const s=slide(8,"付费拒绝与真实执行");
  table(s,[["拒绝类","收费请求","后续执行任务","后续检出任务"],
    ["预算拒绝（schema 通过子集）",String(N.plan_budget_rejections),String(A.budget_post_reject_executed_tasks),String(A.budget_post_reject_detected_tasks)],
    ["动作格式拒绝",String(N.format_rejections),String(A.format_post_reject_executed_tasks),String(A.format_post_reject_detected_tasks)]],
    68,177,1138,194,[518,160,240,220],27);
  txt(s,"第 108 行：实际执行后，终态格式失败",68,412,1140,57,34,C.text,true);
  txt(s,"请求 1 执行 14 拍    请求 2 预算拒绝    请求 3 格式拒绝",68,486,1139,55,29,C.muted);
  txt(s,"decision_format_error，未检出，仍计入完整分母",68,552,1138,61,30,C.cyan,true, FONT);
  foot(s,"85 schema 通过 / 2 拒绝，预算 5 是通过子集。87 原回复保存，86 可解析 / 1 不解析");
}
// 09 Native evidence chain and reviewer roles.
{
  const s=slide(9,"原件绑定与机器审计");
  const nodes=[
    txt(s,"458 登记输入\n冻结快照",68,198,238,98,31,C.text,true),
    txt(s,"4,359 raw 文件\n真实执行与请求",370,198,238,98,31,C.text,true),
    txt(s,"manifest 与 ZIP\n保留原字节",672,198,238,98,31,C.text,true),
    txt(s,"逐项绑定核验\n失败一并保留",974,198,238,98,31,C.text,true)
  ];
  for(let i=0;i<3;i++)s.shapes.connect(nodes[i],nodes[i+1],
    {kind:"straight",fromSide:"right",toSide:"left",line:{fill:C.cyan,width:2},
      tail:{type:"arrow",width:"sm",length:"sm"}});
  table(s,[["机器审计","范围","身份"],
    ["核心审计",A.non_feature_author_core_checks.toLocaleString("en-US")+" 项检查","非实现者代理"],
    ["轨迹审计",A.trace_trajectories+" 轨迹 / "+N.requests+" 请求","entry 代码作者"]],
    68,356,1138,188,[282,520,336],28);
  txt(s,"strict=true 仅表示证据资格",68,581,1134,48,31,C.text,true);
  foot(s,"机器审计非真人 / H02。Git 446 exact、12 仅换行差异，原始登记快照仍为权威");
}
// 10 Historical results remain a separate cohort and full denominator.
{
  const s=slide(10,"旧v8的开发与复用集合");
  txt(s,O.registered_tasks+" 注册 / "+O.executed_tasks+" 实际执行 / "+O.unexecuted_task_count+" 无 DUT",68,172,1140,59,37,C.text,true);
  table(s,[["策略","旧批检出 / 48","API 请求"],...O.strategies.map(x=>[x.label,x.detected_samples+" / "+x.registered_defect_samples,String(x.requests)])],
    68,260,721,325,[322,236,163],26);
  txt(s,O.requests+" 请求\n"+O.tokens.reported_tokens.toLocaleString("en-US")+" tokens\nstrict=false",866,274,345,149,30,C.cyan,true);
  txt(s,"正确任务 143 / 144 实际执行\n0 实际误报，1 未执行",866,470,342,106,27,C.text);
  foot(s,"两批模块集合、分母与预算不同，不合并，也不作增益趋势图。旧失败没有补跑");
}
// 11 Native charts show manual-spec repair only, not AI performance.
{
  const s=slide(11,"判据独立性的规格案例");
  const fifo=D.historical_support.fifo, ext=D.historical_support.external;
  txt(s,"FIFO 独立队列检查",68,179,536,51,34,C.text,true);
  txt(s,fifo.cycles+" 拍 / "+fifo.comparisons+" 次比较",68,243,536,46,27,C.muted);
  bar(s,["修复前","修复后"],[fifo.before_differences,fifo.after_differences],68,313,537,205,80,20,[{idx:1,fill:C.cyan}]);
  txt(s,"中间占用同时读写，占用量保持",68,548,540,72,28,C.text);
  txt(s,"外部人工计时 SPEC",710,179,499,51,34,C.text,true);
  txt(s,"同字节 "+ext.manual_variants+" 人工变体 / "+ext.candidate_modules+" 候选",710,243,499,46,27,C.muted);
  bar(s,["旧人工规格","补全计时后"],[ext.before_detected,ext.after_detected],710,313,499,205,15,5,[{idx:1,fill:C.cyan}]);
  txt(s,"13/15 至 15/15 来自人工 SPEC 补全",710,548,499,72,28,C.text);
  foot(s,"此页是规格独立性与实现修复案例，0 新 API / DUT。外部有限集合来自同作者仓库");
}
// 12 One consolidated page for finite scope, missing evidence and official delivery.
{
  const s=slide(12,"证据边界与交付");
  txt(s,E.pytest_passed.toLocaleString("en-US")+" pass / "+E.pytest_skipped+" skip    mypy "+E.mypy_files+" 源文件零错",68,172,1138,58,37,C.cyan,true);
  txt(s,E.frozen_fingerprinted_files+" 冻结指纹无变化，工程记录不等于 AI 或真人验收",68,244,1138,52,28,C.muted);
  table(s,[["边界","当前证据"],
    ["适用范围","已审计合约 / 参数、有限拍数与有限端口采样"],
    ["尚未提供","硬件、异机 Actions、真人试用、独立人工 H02"],
    ["已披露残项",E.strict_rtl_style_issues_pending+" 项严格 RTL 样式 / WaveDrom 3.6.1 缺失"]],
    68,332,1138,216,[240,898],27);
  txt(s,"截止 "+D.rules.submission_deadline,68,588,1141,49,31,C.text,true);
  foot(s,"方案 PDF ≤10MB，答辩 PDF，佐证合一 PDF，视频可选。真人 / H02 非官方硬门槛",646);
  notes(s,12,"官方通知："+D.rules.notice+"\n规则 PDF："+D.rules.rules_pdf+"\n参考大纲 PDF："+D.rules.outline_pdf);
}

requireFact(deck.slides.items.length===AUTHOR.slide_count,"Final slide count");
const exported=path.join(BUILD,"candidate-export.pptx");
const candidate=path.join(BUILD,"candidate-anonymous.pptx");
console.log(JSON.stringify({stage:"export_candidate",revision:REVISION,slides:deck.slides.items.length,fonts:[FONT,ENGLISH]}));
await (await PresentationFile.exportPptx(deck)).save(exported);
execFileSync(PYTHON,[path.join(HERE,"strip_pptx_metadata.py"),exported,candidate],{stdio:"inherit",windowsHide:true});
const finalDir=path.join(BUILD,"final");await fs.mkdir(finalDir,{recursive:true});
const finalPptx=path.join(finalDir,"defense-"+REVISION+".pptx");
const receipt=path.join(BUILD,"defense-"+REVISION+".validation.json");
const tableOwners=[4,5,7,8,9,10,12], chartOwners=[6,11];
console.log(JSON.stringify({stage:"finalizePresentation",required_native_tables:tableOwners,required_native_charts:chartOwners}));
const result=await finalizePresentation({
  workspaceDir:BUILD,candidatePath:candidate,finalPath:finalPptx,pythonExecutable:PYTHON,
  integrityValidatorPath:path.join(SKILL,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(SKILL,"container_tools/inspect_presentation_layout_geometry.py"),
  explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:tableOwners,
  requiredNativeChartOwnerSlides:chartOwners,requiredEmbeddedWorkbookChartOwnerSlides:chartOwners,
  materializeLiteralChartWorkbooks:true,
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--cover-role","cover","--validate-heading-fit",
    ...tableOwners.flatMap(n=>["--require-native-table-slide",String(n)])],
  fontPolicy:{basis:"design",families:[FONT,ENGLISH]},verifyArtifactToolImport:true,receiptPath:receipt
});
console.log(JSON.stringify({stage:"finalization_result",result}));
const finalDeck=await PresentationFile.importPptx(await FileBlob.load(finalPptx));
const preview=path.join(BUILD,"final-render");await fs.mkdir(preview,{recursive:true});
for(let index=0;index<finalDeck.slides.items.length;index++){
  const page=finalDeck.slides.getItem(index), stem="slide-"+String(index+1).padStart(2,"0");
  const png=await finalDeck.export({slide:page,format:"png",scale:2});
  await fs.writeFile(path.join(preview,stem+".png"),new Uint8Array(await png.arrayBuffer()),{flag:"wx"});
  const layout=await page.export({format:"layout"});
  await fs.writeFile(path.join(preview,stem+".layout.json"),await layout.text(),{flag:"wx"});
  console.log(JSON.stringify({stage:"rendered_final_slide",slide:index+1}));
}
await fs.writeFile(path.join(preview,"deck-inspect.ndjson"),
  (await finalDeck.inspect({kind:"slide,textbox,shape,chart,table,notes",maxChars:250000})).ndjson,{flag:"wx"});
const pdf=path.join(finalDir,"defense-"+REVISION+".pdf");
execFileSync(PYTHON,[path.join(HERE,"create_image_pdf.py"),preview,pdf],{stdio:"inherit",windowsHide:true});
execFileSync(PYTHON,[path.join(HERE,"inspect_artifacts.py"),BUILD,finalPptx,pdf],{stdio:"inherit",windowsHide:true});
for(const item of sourceItems){
  requireFact(hash(await fs.readFile(path.join(ROOT,item.relative_path)))===item.sha256,"Source changed during build");
}
await fs.writeFile(path.join(BUILD,"build_result.json"),JSON.stringify({
  schema:"icarus-defense-v3-build-result-v1",revision:REVISION,slides:12,
  final_pptx:path.relative(ROOT,finalPptx).replaceAll("\\","/"),final_pdf:path.relative(ROOT,pdf).replaceAll("\\","/"),
  final_render:path.relative(ROOT,preview).replaceAll("\\","/"),receipt:path.relative(ROOT,receipt).replaceAll("\\","/"),
  native_chart_owner_slides:chartOwners,native_table_owner_slides:tableOwners,
  materials_only:true,API_requests:0,credential_file_reads:0,DUT_executions:0,engineering_tests_reexecuted:0,
  native_Office_validation:false
},null,2)+"\n",{flag:"wx"});
console.log(JSON.stringify({stage:"complete_private_build",revision:REVISION,finalPptx,pdf,preview,slides:12}));

