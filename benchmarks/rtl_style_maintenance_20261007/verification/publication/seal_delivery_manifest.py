"""Seal release-time bytes after real replay, local checks and independent AI review."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / 'docs/experiment/rtl-spec-rendering-2026-10-07'
STYLE = ROOT / 'benchmarks/rtl_style_maintenance_20261007'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def row(path):
    data = path.read_bytes()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': len(data), 'sha256': sha(data)}


def main():
    parent_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert parent_commit == '77d0c2f9d009696def1da895a50b4a69c6345f3d'
    assert load(STYLE / 'release_receipt.json')['status'] == 'public_complete_replay_passed'
    audit = load(STYLE / 'verification/independent-review/review-r2.json')
    assert audit['status'] == 'passed_with_limits' and len(audit['checks']) == 1511
    assert not audit['failed_checks'] and audit['is_H02_human_review'] is False
    target = STYLE / 'verification/publication/seal_delivery_manifest.py'
    with target.open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    for component, report in (
        (RENDER, 'docs/experiment/rtl_spec_rendering_2026-10-07.md'),
        (STYLE, 'docs/experiment/rtl_style_maintenance_2026-10-07.md')):
        manifest_path = component / 'delivery_manifest.json'
        assert not manifest_path.exists()
        files = [row(path) for path in sorted(component.rglob('*')) if path.is_file()]
        external = [row(ROOT / name) for name in (
            report, '.gitattributes', 'README.md', 'docs/INDEX.md',
            'docs/competition/ic/gap_checklist.md', 'docs/experiment/metric_inventory.md')]
        manifest = {
            'schema': 'icarus-rtl-maintenance-component-delivery-manifest-v1',
            'created_at_utc': datetime.now(timezone.utc).isoformat(), 'client_date': '2026-10-07',
            'publication_parent_commit': parent_commit,
            'component': component.relative_to(ROOT).as_posix(),
            'manifest_excluded_from_its_own_files': True,
            'file_count': len(files), 'files': files,
            'external_release_time_bindings': external,
            'external_binding_semantics': 'Working-tree snapshot at this release; recover from its publishing commit after later valid overview edits. These are not all bytes at the parent commit.',
            'API_requests_from_sealing': 0, 'new_DUT_executions_from_sealing': 0,
            'existing_frozen_materials_and_experiment_results_overwritten': False,
            'human_or_second_host_review_claimed': False}
        with manifest_path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        for item in files + external:
            data = (ROOT / item['path']).read_bytes()
            assert len(data) == item['bytes'] and sha(data) == item['sha256']
        print(json.dumps({'component': manifest['component'], 'sealed_files': len(files),
                          'external_release_bindings': len(external), 'all_bytes_verified': True}))
    documents = [ROOT / name for name in (
        'README.md', 'docs/INDEX.md', 'docs/competition/ic/gap_checklist.md',
        'docs/experiment/metric_inventory.md',
        'docs/experiment/rtl_spec_rendering_2026-10-07.md',
        'docs/experiment/rtl_style_maintenance_2026-10-07.md')]
    documents += [RENDER / 'README.md', STYLE / 'README.md']
    documents += sorted((RENDER / 'bundle').rglob('*.md'))
    documents += sorted((STYLE / 'spec').rglob('*.md'))
    links = 0
    for path in documents:
        for match in re.finditer(r'!?\[[^\]\n]*\]\(([^)\n]+)\)', path.read_text(encoding='utf-8-sig')):
            href = match.group(1).strip().strip('<>')
            if href.startswith('#') or re.match(r'^[a-z][a-z0-9+.-]*://', href, re.I):
                continue
            href = href.split(' "', 1)[0].split('#', 1)[0]
            location = Path(unquote(href))
            if not location.is_absolute():
                location = path.parent / location
            assert location.exists(), (path, href)
            links += 1
    print(json.dumps({'final_Markdown_documents': len(documents),
                      'local_link_occurrences_existing': links,
                      'API_requests': 0, 'new_DUT_executions': 0}))


if __name__ == '__main__':
    main()
