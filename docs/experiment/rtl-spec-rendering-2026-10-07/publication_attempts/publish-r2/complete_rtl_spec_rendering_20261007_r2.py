import hashlib, io, json, shutil, subprocess, xml.etree.ElementTree as ET, zipfile
from pathlib import Path
from datetime import datetime, timezone
root=Path('E:/FPGA_WORK/iverilog-ai-lab')
preflight=root/'.iverilog-ai/ic-engineering-preflight-20261007'
published=root/'docs/experiment/rtl-spec-rendering-2026-10-07'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write_json(p,d):
    assert not p.exists(), p
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
copies=json.loads((published/'copy_manifest.json').read_text(encoding='utf-8'))['copies']
members=json.loads((published/'closed_attempts_manifest.json').read_text(encoding='utf-8'))['members']
for copied in copies:
    p=published/copied['path']
    assert sha(p)==copied['sha256'] and p.stat().st_size==copied['bytes']
check = json.loads((preflight / 'postinstall-check-r1/check.stdout.json').read_text(encoding='utf-8'))
assert check['ok'] and check['smoke']['ok'] and check['smoke']['status'] == 'passed'
assert check['wavedrom']['version'] == '3.6.1'
command = json.loads((final_attempt / 'registered-write-spec.json').read_text(encoding='utf-8'))
assert command['returncode'] == 0 and len(command['files']) == 6
svg_checks = []
for svg in sorted((published / 'bundle').rglob('*.svg')):
    tree = ET.fromstring(svg.read_bytes())
    ids = {e.attrib['id'] for e in tree.iter() if 'id' in e.attrib}
    hrefs = [v for e in tree.iter() for k, v in e.attrib.items() if k.endswith('href')]
    missing = sorted({v[1:] for v in hrefs if v.startswith('#')} - ids)
    external = [v for v in hrefs if not v.startswith('#')]
    assert not missing and not external
    texts = [''.join(e.itertext()).strip() for e in tree.iter()
             if e.tag.split('}')[-1] == 'text']
    svg_checks.append({'path': svg.relative_to(published).as_posix(),
                       'sha256': sha(svg), 'width': int(tree.get('width')),
                       'height': int(tree.get('height')), 'viewBox': tree.get('viewBox'),
                       'missing_internal_references': missing,
                       'external_asset_references': external, 'labels': texts})
assert len(svg_checks) == 2

material_commit='77d0c2f9d009696def1da895a50b4a69c6345f3d'
material_receipt=root/'docs/competition/ic/v3/review/final_receipt.json'
bindings=json.loads(material_receipt.read_text(encoding='utf-8'))['current_source_bindings']
queries=''.join(material_commit+':'+b['path']+'\n' for b in bindings).encode('utf-8')
r=subprocess.run(['git','cat-file','--batch'],input=queries,cwd=root,capture_output=True,check=True)
stream=io.BytesIO(r.stdout)
snapshot=[]
retained=[]
for binding in bindings:
    header=stream.readline().decode('utf-8').strip().split()
    if header[-1]=='missing':
        data=(root/binding['path']).read_bytes()
        kind='retained_local_snapshot'
        blob=None
    else:
        assert len(header)==3 and header[1]=='blob'
        data=stream.read(int(header[2])); assert stream.read(1)==b'\n'
        kind='original_commit_path'; blob=header[0]
    assert hashlib.sha256(data).hexdigest()==binding['sha256'] and len(data)==binding['bytes'], binding['path']
    row={'path':binding['path'],'sha256':binding['sha256'],'bytes':len(data),'binding_kind':kind,'git_blob':blob,'matches_frozen_receipt':True}
    snapshot.append(row)
    if blob is None: retained.append(row)
assert not stream.read()
# Existing public PNG copies can bind retained local preview paths without
# committing the same 28 images a second time.
sizes={row['bytes'] for row in retained}
index={}
ls=subprocess.run(['git','ls-tree','-r','-l','-z',material_commit],cwd=root,capture_output=True,check=True).stdout
for entry in ls.split(b'\0'):
    if not entry: continue
    meta,path_raw=entry.split(b'\t',1)
    fields=meta.decode('ascii').split()
    if fields[1]!='blob' or int(fields[3]) not in sizes: continue
    relative=path_raw.decode('utf-8')
    p=root/relative
    if not p.is_file(): continue
    data=p.read_bytes()
    if len(data)!=int(fields[3]): continue
    git_sha=hashlib.sha1(b'blob '+str(len(data)).encode('ascii')+b'\0'+data).hexdigest()
    if git_sha!=fields[2]: continue
    index.setdefault(hashlib.sha256(data).hexdigest(),{'path':relative,'git_blob':fields[2]})
archive=published/'v3_retained_sources.zip'
assert not archive.exists()
archive_members=[]
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for row in retained:
        alias=index.get(row['sha256'])
        if alias:
            row['binding_kind']='same_bytes_public_alias_at_material_commit'
            row['public_alias']=alias
        else:
            data=(root/row['path']).read_bytes()
            z.writestr(row['path'],data)
            row['binding_kind']='retained_snapshot_archive'
            row['archive']=archive.name
            row['archive_member']=row['path']
            archive_members.append({'path':row['path'],'sha256':row['sha256'],'bytes':len(data)})
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for m in archive_members:
        assert hashlib.sha256(z.read(m['path'])).hexdigest()==m['sha256']
counts={kind:sum(row['binding_kind']==kind for row in snapshot) for kind in ['original_commit_path','same_bytes_public_alias_at_material_commit','retained_snapshot_archive']}
assert sum(counts.values())==157
write_json(published/'v3_material_snapshot_binding.json',{'material_publication_commit':material_commit,'immutable_receipt_path':'docs/competition/ic/v3/review/final_receipt.json','immutable_receipt_sha256':sha(material_receipt),'all_157_bindings_verified':True,'counts':counts,'bindings':snapshot,'retained_sources_archive':{'path':archive.name,'sha256':sha(archive),'bytes':archive.stat().st_size,'members':archive_members},'explanation':'124 original paths and public byte-identical aliases are verified at the material commit; remaining local originals are copied into a new archive. This is a local byte audit, not an independently executed clean-clone reproduction. Later overview edits do not rewrite the frozen v3 receipt.'})
shutil.copytree(preflight/'publication-r1',published/'publication_attempts/publish-r1')
print(json.dumps({'material_binding_counts':counts,'retained_archive_members':len(archive_members)},ensure_ascii=False))
write_json(published / 'rendering_receipt.json', {
    'schema': 'icarus-rtl-spec-rendering-v1',
    'client_date': '2026-10-07', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
    'status': 'renderer_and_two_A_spec_bundles_complete',
    'base_commit': material_commit,
    'renderer': check, 'workflow_returncode': command['returncode'],
    'declared_diagrams': 2, 'correct_A_sources': 2,
    'original_rtl_modified': False, 'old_results_or_materials_rewritten': False,
    'new_model_api_requests': 0, 'new_dut_executions_for_rendering': 0,
    'diagram_kind': 'declared normal-operation specification, not measured simulator output',
    'initial_condition': 'Reset has completed before the first shown active edge.',
    'input_edit': 'Only two wavejson.head.text fields shortened; all other JSON fields unchanged.',
    'svg_checks': svg_checks,
    'root_visual_review': {
        'reviewer_kind': 'authoring AI; not human H02', 'browser': 'Codex in-app browser',
        'actual_individual_browser_screenshots_viewed': 2,
        'titles_ports_values_visible_without_glyph_clipping': True,
        'final_screenshot_paths': ['visual/event_accumulator_normal-operation.png',
                                   'visual/valid_data_pipeline_normal-operation.png'],
        'bbox_diagnostic': 'Raw text rectangles include indentation whitespace; potential outside values retained, not labeled as zero warnings.',
        'earlier_failures_retained': ['spec-render-r1: wrong workspace exit 2',
                                     'spec-render-r2: long heading clipped in browser',
                                     'spec-render-r2/visual-check-r1: MuPDF SVG CSS rendering unsuitable']},
    'limitations': ['Only correct A sources receive these two declared diagrams.',
                    'Normal-operation pictures do not demonstrate reset pulses or wraparound.',
                    'Original six-source r3 style gate still has 12 recorded issues.',
                    'Private failed style candidates are not accepted RTL.',
                    'No new model effectiveness, human trial, external CI, hardware timing or independent human review claim.'],
    'copies_sha256': sha(published / 'copy_manifest.json'),
    'closed_attempts_manifest_sha256': sha(published / 'closed_attempts_manifest.json'),
    'v3_snapshot_binding_sha256': sha(published / 'v3_material_snapshot_binding.json')})
print(json.dumps({'published': str(published), 'byte_identical_copies': len(copies),
                  'closed_attempts_members': len(members), 'two_svg_checks': True,
                  'frozen_v3_bindings_verified': len(snapshot)}, ensure_ascii=False))
