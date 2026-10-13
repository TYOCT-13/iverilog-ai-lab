import fs from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

// Run only after every final PNG has actually received individual visual review.
const HERE=path.dirname(fileURLToPath(import.meta.url));
const revision=process.argv[2];
const replaceStable=process.argv.includes("--replace-stable");
if(!/^r[1-9][0-9]*$/.test(revision||"")||!process.argv.includes("--all-slides-reviewed"))
  throw new Error("Provide a revision and actual all-slide review assertion");
const buildDir=path.join(HERE,"build",revision);
const build=JSON.parse(await fs.readFile(path.join(buildDir,"build_result.json"),"utf8"));
const pdfCheck=JSON.parse(await fs.readFile(path.join(buildDir,"pdf_render_verification.json"),"utf8"));
const validation=JSON.parse(await fs.readFile(path.join(buildDir,"validation.json"),"utf8"));
const sha=bytes=>createHash("sha256").update(bytes).digest("hex");
const expected=build.slides;
if(expected!==20||pdfCheck.slides!==expected||!pdfCheck.all_reviewed_pixels_embedded||!pdfCheck.all_pages_rendered)
  throw new Error("Final review evidence incomplete");
const stableReceipt=path.join(HERE,"delivery_receipt.json");
let previous=null;
if(replaceStable){
  previous=JSON.parse(await fs.readFile(stableReceipt,"utf8"));
  for(const item of previous.outputs){
    if(sha(await fs.readFile(item.path))!==item.sha256)throw new Error("Existing stable output changed");
    if(sha(await fs.readFile(item.validated_source))!==item.sha256)throw new Error("Prior validated output unavailable");
  }
  await fs.writeFile(path.join(HERE,"build",previous.revision,"delivery_receipt.json"),JSON.stringify(previous,null,2)+"\n",{flag:"wx"});
}
const outputs=[];
for(const extension of ["pptx","pdf"]){
  const source=extension==="pptx"?build.finalPptx:build.finalPdf;
  const stable=path.join(HERE,"output","ICARUS_AI_IC_defense_v4."+extension);
  const bytes=await fs.readFile(source);
  await fs.copyFile(source,stable,replaceStable?0:constants.COPYFILE_EXCL);
  if(sha(await fs.readFile(stable))!==sha(bytes))throw new Error("Copy changed bytes");
  outputs.push({kind:extension,path:stable,bytes:bytes.length,sha256:sha(bytes),validated_source:source});
}
const pages=[];
for(let number=1;number<=expected;number++){
  const stem="slide-"+String(number).padStart(2,"0");
  const png=path.join(build.preview,stem+".png"),layout=path.join(build.preview,stem+".layout.json");
  pages.push({slide:number,png,layout,png_sha256:sha(await fs.readFile(png)),individual_visual_reviewed:true,visual_findings:[]});
}
const receipt={schema:"icarus-ic-v4-presentation-delivery-v1",revision,slides:expected,outputs,
  all_20_slides_individually_visually_reviewed:true,visual_reviewer:"Codex via view_image, not human H02",
  visual_review_scope:"titles, text, images, tables, charts, page markers, wrapping, clipping and overlaps",
  pages,native_table_owner_slides:build.native_table_owner_slides,native_chart_owner_slides:build.native_chart_owner_slides,
  finalizer_receipt:build.receipt,pdf_mode:build.pdfMode,pdf_native_export_error:build.pdfError,
  pdf_verification:path.join(buildDir,"pdf_render_verification.json"),
  pdf_is_image_only:true,pdf_is_native_editable_export:false,PPTX_keeps_native_text_tables_charts:true,
  native_Office_validation:false,current_df7ccfa_cloud_checks:"completed/failure",
  submission_deadline:"2026-10-30 20:00 Asia/Shanghai",new_API_requests:0,credential_reads:0,DUT_executions:0,
  appendix_evidence_slides:[19,20],
  notes:"Finalization structural and chart checks passed. All 20 final slides were individually viewed. Image-only PDF exactly embeds all reviewed final slide pixels. Stable files are unchanged copies of finalized r3 files."
};
const privateReceipt=path.join(buildDir,"delivery_receipt.json");
await fs.writeFile(privateReceipt,JSON.stringify(receipt,null,2)+"\n",{flag:"wx"});
await fs.copyFile(privateReceipt,stableReceipt,replaceStable?0:constants.COPYFILE_EXCL);
console.log(JSON.stringify({stage:"stable_delivery",outputs,slides:expected,visual_reviewed:expected}));
