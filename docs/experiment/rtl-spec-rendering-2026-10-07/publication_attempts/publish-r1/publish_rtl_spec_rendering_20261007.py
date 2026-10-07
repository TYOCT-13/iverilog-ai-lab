"""Publish a new rendering record while keeping every earlier attempt immutable."""
import hashlib
import io
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


root = Path('E:/FPGA_WORK/iverilog-ai-lab')
preflight = root / '.iverilog-ai/ic-engineering-preflight-20261007'
published = root / 'docs/experiment/rtl-spec-rendering-2026-10-07'
published.mkdir(exist_ok=False)
copies = []


def copy_file(source, relative):
    target = published / relative
    assert not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    assert target.read_bytes() == source.read_bytes()
    copies.append({'path': target.relative_to(published).as_posix(),
                   'original_path': str(source), 'bytes': target.stat().st_size,
                   'sha256': sha(target), 'byte_identical_copy': True})


prep = root / '.tmp-codex/agent-new-holdout-preparation-20261005'
copy_file(prep / 'spec_document.json', 'inputs/original_spec_document.json')
copy_file(preflight / 'spec-input-r1/spec_document.json', 'inputs/render_spec_document.json')
copy_file(preflight / 'spec-input-r1/layout_changes.json', 'inputs/layout_changes.json')
for name in ['event_accumulator', 'valid_data_pipeline']:
    relative = Path('targets') / name / 'A' / (name + '.v')
    copy_file(root / 'benchmarks/agent_new_holdout_20261005' / relative,
              Path('inputs') / relative)
final_attempt = preflight / 'spec-render-r3'
for path in sorted((final_attempt / 'bundle').rglob('*')):
    if path.is_file():
        copy_file(path, Path('bundle') / path.relative_to(final_attempt / 'bundle'))
for path in sorted((final_attempt / 'visual-check-r1').glob('*')):
    if path.suffix in {'.png', '.json'} and not path.name.startswith('server'):
        copy_file(path, Path('visual') / path.name)
for relative in ['install-r1/install.stdout.json', 'install-r1/install.stderr.txt',
                 'install-r1/install.exitcode.txt',
                 'postinstall-check-r1/check.stdout.json',
                 'postinstall-check-r1/check.stderr.txt',
                 'postinstall-check-r1/check.exitcode.txt',
                 'spec-render-r3/registered-write-spec.json',
                 'spec-render-r3/workflow.stdout.txt',
                 'spec-render-r3/workflow.stderr.txt',
                 'spec-render-r3/workflow.exitcode.txt']:
    copy_file(preflight / relative, Path('commands') / relative)

# These are closed attempts owned by the root agent. The concurrently written
# candidate-r3 directory must not enter this rendering archive.
closed = ['r1', 'install-r1', 'postinstall-check-r1', 'candidate-r1', 'candidate-r2',
          'spec-render-r1', 'spec-render-r2', 'spec-input-r1', 'spec-render-r3']
members = []
archive = published / 'closed_attempts.zip'
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for folder in closed:
        for source in sorted((preflight / folder).rglob('*')):
            if not source.is_file():
                continue
            relative = source.relative_to(preflight).as_posix()
            data = source.read_bytes()
            z.writestr(relative, data)
            members.append({'path': relative, 'bytes': len(data),
                            'sha256': hashlib.sha256(data).hexdigest()})
    for suffix in ['', '_r2', '_r3']:
        source = root / ('.tmp-codex/render_new_holdout_specs_20261007' + suffix + '.py')
        data = source.read_bytes()
        relative = 'recipes/' + source.name
        z.writestr(relative, data)
        members.append({'path': relative, 'bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest()})
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert len(z.namelist()) == len(members)
    for member in members:
        assert hashlib.sha256(z.read(member['path'])).hexdigest() == member['sha256']
write_json(published / 'closed_attempts_manifest.json', {
    'archive': archive.name, 'archive_sha256': sha(archive),
    'archive_bytes': archive.stat().st_size, 'members': members,
    'member_count': len(members), 'byte_verified': True,
    'excluded_in_progress_directory': 'candidate-r3'})
write_json(published / 'copy_manifest.json', {'copies': copies})

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

# The v3 material receipt is a frozen snapshot. Verify its source bindings against
# its publication commit, not against overview documents that will evolve later.
material_commit = '77d0c2f9d009696def1da895a50b4a69c6345f3d'
material_receipt = root / 'docs/competition/ic/v3/review/final_receipt.json'
bindings = json.loads(material_receipt.read_text(encoding='utf-8'))['current_source_bindings']
queries = b''.join((material_commit + ':' + b['path'] + '\n').encode('utf-8') for b in bindings)
result = subprocess.run(['git', 'cat-file', '--batch'], input=queries, cwd=root,
                        capture_output=True, check=True)
stream = io.BytesIO(result.stdout)
snapshot = []
for binding in bindings:
    header = stream.readline().decode('ascii').strip().split()
    assert len(header) == 3 and header[1] == 'blob', binding['path']
    data = stream.read(int(header[2]))
    assert stream.read(1) == b'\n'
    actual = hashlib.sha256(data).hexdigest()
    assert actual == binding['sha256'] and len(data) == binding['bytes'], binding['path']
    snapshot.append({'path': binding['path'], 'sha256': actual, 'bytes': len(data),
                     'git_blob': header[0], 'matches_frozen_receipt': True})
assert not stream.read()
write_json(published / 'v3_material_snapshot_binding.json', {
    'material_publication_commit': material_commit,
    'immutable_receipt_path': 'docs/competition/ic/v3/review/final_receipt.json',
    'immutable_receipt_sha256': sha(material_receipt),
    'all_157_bindings_match_commit': len(snapshot) == 157,
    'bindings': snapshot,
    'explanation': 'Later overview edits do not rewrite the frozen v3 receipt.'})
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
                  'frozen_v3_bindings_verified_against_commit': len(snapshot)}, ensure_ascii=False))
