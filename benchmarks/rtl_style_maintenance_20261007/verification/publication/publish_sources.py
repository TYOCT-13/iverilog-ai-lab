"""Copy only bound maintenance assets and retain all closed attempts verbatim."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / '.iverilog-ai/ic-engineering-preflight-20261007'
WORK = PRIVATE / 'candidate-r3'
PUBLIC = ROOT / 'benchmarks/rtl_style_maintenance_20261007'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(relative, value):
    path = PUBLIC / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


copied = []


def copy(source, relative):
    target = PUBLIC / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    with target.open('xb') as stream:
        stream.write(data)
    assert target.read_bytes() == data
    copied.append({'source': source.relative_to(ROOT).as_posix(),
                   'public_path': relative, 'bytes': len(data), 'sha256': sha(data)})


def archive(name, items):
    path = PUBLIC / name
    members = []
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for source, relative in items:
            data = source.read_bytes()
            bundle.writestr(relative, data)
            members.append({'path': relative, 'bytes': len(data), 'sha256': sha(data)})
    with zipfile.ZipFile(path) as bundle:
        assert len(bundle.namelist()) == len(members)
        for item in members:
            data = bundle.read(item['path'])
            assert len(data) == item['bytes'] and sha(data) == item['sha256']
    write(name.replace('.zip', '_manifest.json'), {
        'archive': name, 'archive_bytes': path.stat().st_size,
        'archive_sha256': sha(path.read_bytes()), 'member_count': len(members),
        'members': members, 'all_members_verified_after_write': True})
    return len(members)


def main():
    assert not PUBLIC.exists(), 'Choose a new publication directory; never overwrite evidence.'
    bound = read(WORK / 'members-r2.json')
    assert bound['member_count'] == len(bound['members']) == 623
    for item in bound['members']:
        data = (WORK / item['path']).read_bytes()
        assert len(data) == item['bytes'] and sha(data) == item['sha256'], item['path']
    inputs = read(WORK / 'publishable_inputs.json')
    assert len(inputs['required_inputs']) == 35
    for item in inputs['required_inputs']:
        data = (WORK / item['private_path_relative_to_candidate_r3']).read_bytes()
        assert len(data) == item['bytes'] and sha(data) == item['sha256']
        if item['public_path'].startswith('originals/'):
            original = ROOT / 'benchmarks/agent_new_holdout_20261005/targets' / item['public_path'][len('originals/'):]
            assert data == original.read_bytes(), 'Frozen original mismatch'
    assert sha((WORK / 'publishable_reproduce.py').read_bytes()) == inputs['entrypoint']['sha256']
    PUBLIC.mkdir(parents=True)
    for item in inputs['required_inputs']:
        copy(WORK / item['private_path_relative_to_candidate_r3'], item['public_path'])
    for name in ('publishable_reproduce.py', 'publishable_inputs.json'):
        copy(WORK / name, name)
    for name in ('final_receipt-r2-complete.json', 'final_receipt-r2-complete.md',
                 'gate-r3/deliverable_gate.json', 'gate-r3/deliverable_gate.md',
                 'validation/public-oracle/summary.json', 'validation/four-state/summary.json',
                 'diagram-encoding-r1/encoding_equivalence.json',
                 'diagram-encoding-r1/rendered_bundle_validation.json', 'risk_review.json',
                 'operation_cones.json', 'publishable_entrypoint_receipt.json',
                 'publishable_entrypoint_checks.json', 'publishable_inputs.md'):
        copy(WORK / name, 'verification/original-run/' + name)
    visual = read(PRIVATE / 'style-visual-r2/root_visual_receipt.json')
    assert visual['status'] == 'all_6_final_browser_views_accepted' and len(visual['rows']) == 6
    for row in visual['rows']:
        name, variant = row['module'], row['variant']
        svg = PUBLIC / f'spec/targets/{name}/{variant}/waveforms/{name}_variant-behavior.svg'
        assert sha(svg.read_bytes()) == row['svg_sha256']
        for key in ('screenshot', 'geometry'):
            source = PRIVATE / 'style-visual-r2' / row[key]
            assert sha(source.read_bytes()) == row[key + '_sha256']
            copy(source, 'visual/' + row[key])
    copy(PRIVATE / 'style-visual-r2/root_visual_receipt.json', 'visual/root_visual_receipt.json')
    copy(Path(__file__).resolve(), 'verification/publication/publish_sources.py')
    bound_paths = {item['path'] for item in bound['members']}
    items = [(WORK / item['path'], 'candidate-r3/' + item['path']) for item in bound['members']]
    items.append((WORK / 'members-r2.json', 'candidate-r3/members-r2.json'))
    additions = sorted(p for p in WORK.rglob('*') if p.is_file()
                       and p.relative_to(WORK).as_posix() not in bound_paths | {'members-r2.json'})
    items.extend((p, 'candidate-r3/' + p.relative_to(WORK).as_posix()) for p in additions)
    closed_count = archive('closed_candidate_attempts.zip', items)
    visual_items = [(p, folder + '/' + p.relative_to(PRIVATE / folder).as_posix())
                    for folder in ('style-visual-r1', 'style-visual-r2')
                    for p in sorted((PRIVATE / folder).rglob('*')) if p.is_file()]
    visual_count = archive('closed_visual_attempts.zip', visual_items)
    write('publication_copy_manifest.json', {
        'schema': 'rtl-style-maintenance-publication-copy-v1',
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_commit': inputs['source_commit'], 'verified_original_bound_members': 623,
        'preserved_unbound_followup_files': len(additions),
        'closed_candidate_archive_members': closed_count,
        'closed_visual_archive_members': visual_count,
        'copied_file_count': len(copied), 'copied_files': copied,
        'all_copies_byte_identical': True, 'API_requests': 0,
        'new_DUT_executions': 0, 'public_all_replay_not_yet_run': True,
        'original_source_and_experiment_results_changed': False})
    print(json.dumps({'status': 'published_bound_sources', 'copied_files': len(copied),
                      'old_bound_members': 623, 'followup_files': len(additions),
                      'candidate_archive_members': closed_count,
                      'visual_archive_members': visual_count, 'API_requests': 0,
                      'new_DUT_executions': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
