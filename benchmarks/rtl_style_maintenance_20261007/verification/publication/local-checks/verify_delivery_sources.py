"""Audit local links, byte copies, archives and frozen materials; no API or DUT."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.tmp-codex/rtl-maintenance-delivery-check-r1'
RENDER = ROOT / 'docs/experiment/rtl-spec-rendering-2026-10-07'
STYLE = ROOT / 'benchmarks/rtl_style_maintenance_20261007'
ROWS = []


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def check(label, condition):
    ROWS.append({'check': label, 'passed': bool(condition)})
    if not condition:
        raise AssertionError(label)


def equal_bytes(label, data, item):
    check(label, len(data) == item['bytes'] and sha(data) == item['sha256'])


def archive(path, items, expected_sha, expected_bytes):
    check('archive bytes ' + path.name,
          path.stat().st_size == expected_bytes and sha(path.read_bytes()) == expected_sha)
    with zipfile.ZipFile(path) as bundle:
        check('archive member count ' + path.name, len(bundle.namelist()) == len(items))
        check('archive unique names ' + path.name, len(set(bundle.namelist())) == len(items))
        for item in items:
            equal_bytes(path.name + ':' + item['path'], bundle.read(item['path']), item)


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    try:
        for item in read(RENDER / 'copy_manifest.json')['copies']:
            equal_bytes('render copy ' + item['path'], (RENDER / item['path']).read_bytes(), item)
        for filename in ('publication_copy_manifest.json', 'replay_copy_manifest.json'):
            for item in read(STYLE / filename)['copied_files']:
                equal_bytes('style copy ' + item['public_path'], (STYLE / item['public_path']).read_bytes(), item)
        for folder, name in ((RENDER, 'closed_attempts_manifest.json'),
                             (STYLE, 'closed_candidate_attempts_manifest.json'),
                             (STYLE, 'closed_visual_attempts_manifest.json'),
                             (STYLE, 'public_replay_manifest.json')):
            manifest = read(folder / name)
            archive(folder / manifest['archive'], manifest['members'],
                    manifest['archive_sha256'], manifest['archive_bytes'])
        binding = read(RENDER / 'v3_material_snapshot_binding.json')
        retained = binding['retained_sources_archive']
        archive(RENDER / retained['path'], retained['members'], retained['sha256'], retained['bytes'])
        commit = binding['material_publication_commit']
        check('material snapshot commit', commit == '77d0c2f9d009696def1da895a50b4a69c6345f3d')
        with zipfile.ZipFile(RENDER / retained['path']) as bundle:
            for item in binding['bindings']:
                if item['binding_kind'] == 'retained_snapshot_archive':
                    data = bundle.read(item['archive_member'])
                else:
                    path = item.get('public_alias', {}).get('path', item['path'])
                    data = subprocess.check_output(['git', 'show', commit + ':' + path], cwd=ROOT)
                equal_bytes('frozen material source ' + item['path'], data, item)
        check('material snapshot partition', binding['counts'] == {
            'original_commit_path': 124, 'same_bytes_public_alias_at_material_commit': 12,
            'retained_snapshot_archive': 21})
        preserved = {
            'docs/competition/ic/ICARUS_技术方案_v3.pdf': '4bb214297d189ccbf446dd12e9bc848bffd216601c1c315241f6cb3bcc87f6a3',
            'docs/competition/ic/ICARUS_佐证材料_v3.pdf': '7fe5fe5aa78d654dc4e212cd25e2f2b202418d1d7a32d96ce755d8361a8e0dda',
            'docs/competition/ic/ICARUS_答辩材料_v3.pdf': '80f2fadd2304fdb7d0d7695520242239e9e31c0dbaac9db2f96e5e108fddf580',
            'docs/competition/ic/ICARUS_答辩材料_v3.pptx': '03a1cf9a47bb95576054725baf34b73a041d953983ba31ca3f8ad4c5ac8db76c',
            'docs/competition/ic/v3/material_data.json': '33a11bcce08331a5ccf18ee1c7da05059a8978a4a233a87661ff409d2d1dc8b4',
            'docs/competition/ic/v3/review/final_receipt.json': 'b2acd33125cb9005ebaf46d8a21bbc92c6ca88753194b1eef46a46ae2a6cb428'}
        for path, digest in preserved.items():
            check('immutable material ' + path, sha((ROOT / path).read_bytes()) == digest)
        inputs = read(STYLE / 'publishable_inputs.json')
        for item in inputs['required_inputs']:
            equal_bytes('published input ' + item['public_path'], (STYLE / item['public_path']).read_bytes(), item)
            if item['public_path'].startswith('originals/'):
                suffix = item['public_path'][len('originals/'):]
                frozen = ROOT / 'benchmarks/agent_new_holdout_20261005/targets' / suffix
                check('original benchmark preserved ' + suffix,
                      (STYLE / item['public_path']).read_bytes() == frozen.read_bytes())
        documents = [ROOT / name for name in (
            'README.md', 'docs/INDEX.md', 'docs/competition/ic/gap_checklist.md',
            'docs/experiment/metric_inventory.md',
            'docs/experiment/rtl_spec_rendering_2026-10-07.md',
            'docs/experiment/rtl_style_maintenance_2026-10-07.md')]
        documents += [RENDER / 'README.md', STYLE / 'README.md']
        documents += sorted((RENDER / 'bundle').rglob('*.md'))
        documents += sorted((STYLE / 'spec').rglob('*.md'))
        local_links = 0
        for path in documents:
            for match in re.finditer(r'!?\[[^\]\n]*\]\(([^)\n]+)\)', path.read_text(encoding='utf-8-sig')):
                href = match.group(1).strip().strip('<>')
                if href.startswith('#') or re.match(r'^[a-z][a-z0-9+.-]*://', href, re.I):
                    continue
                href = href.split(' "', 1)[0].split('#', 1)[0]
                target = Path(unquote(href))
                if not target.is_absolute():
                    target = path.parent / target
                local_links += 1
                check('Markdown link ' + path.relative_to(ROOT).as_posix() + ' -> ' + href, target.exists())
        command = [sys.executable, '-B', '-X', 'utf8', 'scripts/check_doc_index.py']
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=False)
        (OUT / 'doc-index.stdout.txt').write_text(result.stdout, encoding='utf-8')
        (OUT / 'doc-index.stderr.txt').write_text(result.stderr, encoding='utf-8')
        (OUT / 'doc-index.exit.json').write_text(json.dumps({'command': command, 'cwd': str(ROOT),
                                                          'exit_code': result.returncode}, indent=2), encoding='utf-8')
        check('project doc index command', result.returncode == 0)
        (OUT / 'result.json').write_text(json.dumps({
            'schema': 'rtl-maintenance-local-delivery-audit-v1',
            'created_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'passed',
            'reviewer': 'authoring root AI; not independent human H02',
            'check_count': len(ROWS), 'failed_checks': 0, 'rows': ROWS,
            'Markdown_documents_checked': len(documents), 'local_Markdown_link_occurrences': local_links,
            'frozen_v3_material_source_bindings_checked': 157,
            'moving_overviews_compared_at': commit,
            'current_overview_changes_do_not_rewrite_frozen_receipt': True,
            'API_requests': 0, 'new_DUT_executions': 0,
            'scope': 'Local byte, source-at-commit, archive and path verification; not new model, DUT, clean-clone or human evidence.'
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'passed', 'checks': len(ROWS), 'local_links': local_links,
                          'Markdown_documents': len(documents), 'v3_frozen_source_bindings': 157,
                          'immutable_materials': 6, 'API_requests': 0, 'new_DUT_executions': 0}, ensure_ascii=False))
    except BaseException:
        (OUT / 'failed_checks.json').write_text(json.dumps(ROWS, ensure_ascii=False, indent=2), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
