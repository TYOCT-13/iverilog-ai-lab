"""Verify the actual published-layout replay and seal copies without altering raw files."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'benchmarks/rtl_style_maintenance_20261007'
WORK = ROOT / '.iverilog-ai/ic-engineering-preflight-20261007/candidate-r3'
OUT = ROOT / '.iverilog-ai/ic-engineering-preflight-20261007/public-replay-r1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(relative, value):
    path = PUBLIC / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


copies = []


def copy(source, relative):
    data = source.read_bytes()
    target = PUBLIC / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as stream:
        stream.write(data)
    assert target.read_bytes() == data
    copies.append({'source': source.relative_to(ROOT).as_posix(), 'public_path': relative,
                   'bytes': len(data), 'sha256': sha(data)})


def main():
    receipt = read(OUT / 'replay_receipt.json')
    assert receipt['status'] == 'passed' and receipt['mode'] == 'all'
    assert receipt['API_requests'] == 0 and receipt['new_DUT_executions'] == 36
    gate = read(OUT / 'gate/deliverable_gate.json')
    assert gate['delivery_ready'] and gate['errors'] == gate['strict_warnings'] == 0
    states = {key: value['status'] for key, value in gate['checks'].items()}
    assert list(states.values()).count('passed') == 6
    assert states['testbench'] == states['toolchain'] == 'not_requested'
    public = read(OUT / 'validation/public-oracle/summary.json')
    four = read(OUT / 'validation/four-state/summary.json')
    assert public['status'] == four['status'] == 'passed'
    assert public['DUT_executions'] == 12 and four['DUT_executions'] == 24
    assert len(public['records']) == 12 and len(four['records']) == 24
    assert all(row['compile_exitcode'] == row['run_exitcode'] == 0
               for row in public['records'] + four['records'])
    assert all(row['same_actual_samples'] and row['same_oracle_verdict'] for row in public['pairs'])
    assert all(row['equal_samples'] and not row['differences'] for row in four['pairs'])
    expected = {'event_accumulator/A': 0, 'event_accumulator/B': 1, 'event_accumulator/C': 1,
                'valid_data_pipeline/A': 0, 'valid_data_pipeline/B': 5, 'valid_data_pipeline/C': 1}
    assert {row['case'] + '/' + row['variant']: row['original_and_candidate_failures']
            for row in public['pairs']} == expected
    paired_public = sum(row['checks_per_side'] for row in public['pairs'])
    paired_four = sum(row['binary_four_state_output_comparisons'] for row in four['pairs'])
    assert (paired_public, paired_four) == (171, 4944)
    assert all(row['executor_verdict'] == 'inconclusive' and row['executor_check_count'] == 0
               for row in four['records'])
    specs = []
    for path in sorted((PUBLIC / 'spec').rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(PUBLIC).as_posix()
        regenerated = OUT / 'bundle' / relative
        assert path.read_bytes() == regenerated.read_bytes(), relative
        specs.append({'public_path': relative, 'bytes': path.stat().st_size,
                      'sha256': sha(path.read_bytes()), 'reproduced_byte_identical': True})
    assert len(specs) == 18
    bound = read(WORK / 'members-r2.json')
    for item in bound['members']:
        data = (WORK / item['path']).read_bytes()
        assert len(data) == item['bytes'] and sha(data) == item['sha256']
    inputs = read(PUBLIC / 'publishable_inputs.json')
    for item in inputs['required_inputs']:
        data = (PUBLIC / item['public_path']).read_bytes()
        assert len(data) == item['bytes'] and sha(data) == item['sha256']
    assert sha((PUBLIC / 'publishable_reproduce.py').read_bytes()) == inputs['entrypoint']['sha256']
    for relative in ('replay_receipt.json', 'gate/deliverable_gate.json', 'gate/deliverable_gate.md',
                     'gate/official-gate.stdout.txt', 'gate/official-gate.stderr.txt', 'gate/official-gate.exit.json'):
        copy(OUT / relative, 'verification/replay/' + relative)
    for phase in ('public-oracle', 'four-state'):
        for name in ('summary.json', 'progress.json', 'exit.json', 'path_replacements.json',
                     'replayed-job.py', 'stdout.txt', 'stderr.txt'):
            copy(OUT / 'validation' / phase / name, 'verification/replay/' + phase + '/' + name)
    for path in sorted((OUT / 'spec-logs').iterdir()):
        copy(path, 'verification/replay/spec-logs/' + path.name)
    for label, folder in (('command', '.tmp-codex/rtl-style-replay-command-r1'),
                          ('publication-command', '.tmp-codex/rtl-style-publication-r1')):
        assert read(ROOT / folder / 'exit.json')['exit_code'] == 0
        for path in sorted((ROOT / folder).iterdir()):
            copy(path, 'verification/replay/' + label + '/' + path.name)
    copy(Path(__file__).resolve(), 'verification/publication/complete_public_replay.py')
    archive_path = PUBLIC / 'public_replay.zip'
    members = []
    source_sets = [('public-replay-r1', OUT),
                   ('replay-command-r1', ROOT / '.tmp-codex/rtl-style-replay-command-r1'),
                   ('publication-command-r1', ROOT / '.tmp-codex/rtl-style-publication-r1')]
    with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for prefix, folder in source_sets:
            for path in sorted(folder.rglob('*')):
                if path.is_file():
                    data = path.read_bytes()
                    relative = prefix + '/' + path.relative_to(folder).as_posix()
                    archive.writestr(relative, data)
                    members.append({'path': relative, 'bytes': len(data), 'sha256': sha(data)})
    with zipfile.ZipFile(archive_path) as archive:
        assert len(archive.namelist()) == len(members)
        for item in members:
            data = archive.read(item['path'])
            assert len(data) == item['bytes'] and sha(data) == item['sha256']
    write('public_replay_manifest.json', {
        'archive': 'public_replay.zip', 'archive_bytes': archive_path.stat().st_size,
        'archive_sha256': sha(archive_path.read_bytes()), 'member_count': len(members),
        'all_members_verified_after_write': True, 'members': members})
    write('replay_copy_manifest.json', {'copied_file_count': len(copies), 'copied_files': copies,
                                       'all_copies_byte_identical': True})
    write('release_receipt.json', {
        'schema': 'rtl-style-maintenance-release-v1',
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'client_date': '2026-10-07',
        'status': 'public_complete_replay_passed', 'source_commit': inputs['source_commit'],
        'official_gate_states': states, 'source_errors': 0, 'source_strict_warnings': 0,
        'gate_simulation_import_or_rewrite_performed': False,
        'original_private_DUT_executions': 36, 'public_repeat_DUT_executions': 36,
        'maintenance_phase_total_DUT_executions': 72,
        'public_oracle_output_comparisons_per_run': paired_public,
        'four_state_output_comparisons_per_run': paired_four,
        'paired_output_value_comparisons_per_run': paired_public + paired_four,
        'all_comparisons_equal_in_each_run': True,
        'repeated_vectors_are_new_independent_samples': False,
        'API_requests': 0, 'included_in_old_model_scores_or_tests': False,
        'intentional_variant_failures_per_side': expected,
        'four_state_driver_executor_verdict': 'inconclusive',
        'four_state_driver_builtin_checks': 0,
        'four_state_result_decided_by': 'explicit external row-by-row original/candidate comparison',
        'spec_files_reproduced_byte_identically': 18, 'spec_bindings': specs,
        'original_bound_worker_files_unchanged': 623,
        'public_required_inputs_unchanged': 35,
        'actual_final_browser_diagrams_reviewed': 6,
        'public_replay_archive_members': len(members),
        'evidence': ['publication_copy_manifest.json', 'closed_candidate_attempts_manifest.json',
                     'closed_visual_attempts_manifest.json', 'public_replay_manifest.json',
                     'replay_copy_manifest.json', 'visual/root_visual_receipt.json',
                     'verification/original-run/final_receipt-r2-complete.json',
                     'verification/replay/replay_receipt.json'],
        'limitations': [
            'Actual replay was on the same host from public files; no clean clone or second-host claim.',
            'Official gate testbench/toolchain remain not_requested; real Icarus evidence is separate.',
            'A correct; B/C retain deliberate functional defects and fail the correct oracle.',
            'Finite mixed-state and reset samples are not formal equivalence or exhaustive data proof.',
            'No synthesis, physical timing, hardware, external Actions or new API study was run.',
            'AI authoring and review are not real user trials or human H02.',
            'Frozen benchmarks, experiment outcomes, PDF/PPTX and original receipts remain unchanged.'
        ]})
    print(json.dumps({'status': 'public_replay_sealed', 'copied_files': len(copies),
                      'archive_members': len(members), 'spec_files_byte_identical': 18,
                      'paired_comparisons_per_run': paired_public + paired_four,
                      'new_DUT_executions': 36, 'maintenance_phase_total_DUT': 72,
                      'API_requests': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
