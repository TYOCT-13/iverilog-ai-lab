from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root/'src')]
from scripts.summarize_agent_comparison import summarize_rows
raw_root = root / '.iverilog-ai/agent-new-holdout-study-live-20261005'
public = root / 'docs/experiment/agent-new-holdout-study-live-2026-10-05'

def read(name):
    return json.loads((raw_root / name).read_text(encoding='utf-8'))

def digest(data):
    return hashlib.sha256(data).hexdigest()

def write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')

report, summary, registration, budget = [read(name) for name in
    ('results.json', 'strict_summary.json', 'preregistration.json', 'token_budget.json')]
rows = report['rows']
assert len(rows) == len(registration['rows']) == 108
assert report['record_kind'] == 'api_and_local_simulation'
assert report.get('finished_at') and report['changed_inputs_at_finish'] == []
assert summary['frozen_input_snapshot_verified'] is True
decisions = [d for row in rows for d in row.get('usage_by_decision', [])]
sent = [d for d in decisions if d.get('error_type') != 'TokenBudgetExceeded']
assert len(sent) == report['requests_attempted'] == len(budget['records'])
for decision, record in zip(sent, budget['records']):
    if record['status'] == 'known_usage':
        usage = decision['usage']
        assert record['charged_tokens'] == usage['prompt_tokens'] + usage['completion_tokens'] == usage['total_tokens']
    assert record['output_cap'] == 4096
assert budget['limit'] == 1_000_000
assert budget['totals']['conservative_total'] <= budget['limit']
assert sum(d.get('usage', {}).get('total_tokens', 0) for d in sent if isinstance(d.get('usage'), dict)) == budget['totals']['reported_tokens']
public.mkdir(parents=True, exist_ok=False)
artifacts = []

def remember(path):
    raw = path.read_bytes()
    artifacts.append({'path': path.relative_to(public).as_posix(), 'sha256': digest(raw), 'size_bytes': len(raw)})

for name in ('preregistration.json', 'run_settings.json', 'token_budget.json', 'strict_summary.json'):
    (public / name).write_bytes((raw_root / name).read_bytes())
    remember(public / name)
# Keep the original report in a compressed archive, rather than duplicate large row JSON files.
with zipfile.ZipFile(public / 'results.zip', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    archive.writestr('results.json', (raw_root / 'results.json').read_bytes())
remember(public / 'results.zip')
specs = public / 'specs'
specs.mkdir()
for case, config in registration['protocol_config']['cases'].items():
    data = (root / config['spec_path']).read_bytes()
    assert digest(data) == registration['code_and_input_sha256'][config['spec_path']]
    target = specs / (case + '_spec.md')
    target.write_bytes(data)
    remember(target)
manifest_raw = (raw_root / 'registered-inputs/manifest.json').read_bytes()
manifest = json.loads(manifest_raw)
(public / 'registered_inputs_manifest.json').write_bytes(manifest_raw)
remember(public / 'registered_inputs_manifest.json')
with zipfile.ZipFile(public / 'registered_inputs.zip', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    archive.writestr('manifest.json', manifest_raw)
    for item in manifest['files']:
        data = (raw_root / item['copy']).read_bytes()
        assert digest(data) == item['sha256'] and len(data) == item['size_bytes']
        archive.writestr('files/' + item['path'], data)
with zipfile.ZipFile(public / 'registered_inputs.zip') as archive:
    assert archive.testzip() is None and len(archive.namelist()) == len(manifest['files']) + 1
remember(public / 'registered_inputs.zip')
rejections, recoveries, trace_records, schema_counts = [], [], [], Counter()
response_records = []
with zipfile.ZipFile(public / 'traces_and_decisions.zip', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for index, row in enumerate(rows):
        if not row.get('trajectory'):
            continue
        trace_path = Path(row['trajectory']).resolve(strict=True)
        assert trace_path.is_relative_to(raw_root.resolve())
        trace_raw = trace_path.read_bytes()
        trace = json.loads(trace_raw)
        entry = trace_path.relative_to(raw_root).as_posix()
        archive.writestr(entry, trace_raw)
        trace_records.append({'row_index': index, 'entry': entry, 'sha256': digest(trace_raw), 'size_bytes': len(trace_raw)})
        pending_rejections = []
        for decision_index, decision in enumerate(trace['decisions']):
            schema_counts[decision.get('schema_validation_status', 'not_reached')] += 1
            metadata = decision.get('untrusted_response')
            if metadata:
                path = (trace_path.parent / metadata['path']).resolve(strict=True)
                assert path.is_relative_to(raw_root.resolve())
                data = path.read_bytes()
                assert metadata['trusted'] is False and digest(data) == metadata['sha256'] and len(data) == metadata['bytes']
                response_entry = path.relative_to(raw_root).as_posix()
                archive.writestr(response_entry, data)
                response_records.append({'row_index': index, 'decision_index': decision_index, 'entry': response_entry, **metadata})
            if decision.get('retry_eligible'):
                rejected = {'row_index': index, 'case': row['case'], 'variant': row['variant'], 'strategy': row['strategy'],
                            'seed': row['seed'], 'decision_index': decision_index, 'request_id': f'{index}:{decision_index}',
                            'kind': 'plan_budget' if decision.get('plan_error', {}).get('code') in {'stimulus_budget_exceeded','accepted_vector_budget_exceeded'} else 'decision_format' if decision.get('decision_error') else 'plan_preflight',
                            'diagnostic': decision.get('decision_error', decision.get('plan_error')), 'usage': decision.get('usage'),
                            'response_status': decision.get('untrusted_response_status'), 'response_artifact': metadata,
                            'response_sha256': decision.get('response_sha256'), 'response_bytes': decision.get('response_bytes'),
                            'executed_after_recovery': False}
                rejections.append(rejected)
                pending_rejections.append(rejected)
            elif 'action' in decision and pending_rejections:
                executed = isinstance(decision.get('executed_round'), int)
                for item in pending_rejections:
                    item['recovered_to_schema'] = True
                    item['executed_after_recovery'] = executed
                recoveries.append({'row_index': index, 'decision_index': decision_index,
                                   'rejected_decision_indices': [d['decision_index'] for d in pending_rejections],
                                   'action': decision['action']['action'], 'executed_after_recovery': executed})
                pending_rejections = []
remember(public / 'traces_and_decisions.zip')
write(public / 'trace_manifest.json', {'traces': trace_records, 'responses': response_records,
                                     'rejections': rejections, 'recoveries': recoveries})
remember(public / 'trace_manifest.json')
raw_files = [{'path': path.relative_to(raw_root).as_posix(), 'sha256': digest(path.read_bytes()),
              'size_bytes': path.stat().st_size} for path in sorted(raw_root.rglob('*')) if path.is_file()]
write(public / 'full_raw_manifest.json', {'schema': 'complete-study-raw-bytes-v1', 'files': raw_files,
    'scope': 'all files from the finished local raw folder, including every execution side and frozen inputs',
    'portable_reproduction_validated': False})
remember(public / 'full_raw_manifest.json')
with zipfile.ZipFile(public / 'full_raw_evidence.zip', 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for item in raw_files:
        data = (raw_root / item['path']).read_bytes()
        assert digest(data) == item['sha256'] and len(data) == item['size_bytes']
        archive.writestr(item['path'], data)
with zipfile.ZipFile(public / 'full_raw_evidence.zip') as archive:
    assert archive.testzip() is None and len(archive.namelist()) == len(raw_files)
remember(public / 'full_raw_evidence.zip')

strategies = ('fixed', 'random', 'protocol_random', 'single', 'feedback', 'no_feedback')
controls = {strategy: {'registered': 6, 'executed': sum(bool(r['rounds']) for r in rows if r['strategy'] == strategy and r['variant'] == 'reference'),
                      'terminal_statuses': dict(Counter(r['status'] for r in rows if r['strategy'] == strategy and r['variant'] == 'reference')),
                      'actual_false_alarms': summary['strategies'][strategy]['reference_target_false_alarms']}
            for strategy in strategies}
matrix = [{'case': case, 'variant': variant, 'detected_by_strategy': {
    strategy: sum(r['detected'] for r in rows if (r['strategy'], r['case'], r['variant']) == (strategy, case, variant))
    for strategy in strategies}} for case, variant in dict.fromkeys((r['case'], r['variant']) for r in rows if r['variant'] != 'reference')]
totals = budget['totals']
revision = registration['study']['source_revision']
cohorts = registration['study'].get('cohorts', {'new_internal_synthetic_modules': ['valid_data_pipeline', 'event_accumulator']})
cohort_summaries = {cohort: summarize_rows([r for r in summary['rows'] if r['case'] in cases])
    for cohort, cases in cohorts.items()}
write(public/'cohort_summaries.json', cohort_summaries)
remember(public/'cohort_summaries.json')
byte_bindings = []
for item in manifest['files']:
    raw = (raw_root/item['copy']).read_bytes()
    committed = subprocess.check_output(['git','show',revision+':'+item['path']],cwd=root)
    kind = 'exact' if raw==committed else 'newline_only' if raw.replace(b'\r\n',b'\n')==committed.replace(b'\r\n',b'\n') else 'content_difference'
    byte_bindings.append({'path':item['path'],'registered_sha256':digest(raw),'git_blob_sha256':digest(committed),'binding':kind})
assert all(b['binding']!='content_difference' for b in byte_bindings)
write(public/'source_byte_binding.json', {'source_revision':revision,'counts':dict(Counter(b['binding'] for b in byte_bindings)),
    'files':byte_bindings,'clean_checkout_byte_identical_claim':all(b['binding']=='exact' for b in byte_bindings),
    'registered_snapshot_remains_authoritative':True})
remember(public/'source_byte_binding.json')
port_facts = Counter()
port_model_states = Counter()
no_feedback_states = 0
for task in rows:
    if not task.get('trajectory'):
        continue
    trajectory = json.loads(Path(task['trajectory']).read_text(encoding='utf-8'))
    for episode in trajectory['rounds']:
        facts = episode['observation'].get('port_observations')
        port_facts['episodes'] += 1
        if isinstance(facts, dict):
            port_facts['status.' + facts['status']] += 1
            port_facts['returned_samples'] += facts['returned_samples']
            port_facts['omitted_samples'] += facts['omitted_samples']
            assert len(facts['samples']) <= 12
    for decision in trajectory['decisions']:
        if decision.get('error_type') == 'TokenBudgetExceeded':
            continue
        state = decision['state']
        if task['strategy'] == 'no_feedback':
            no_feedback_states += 1
            assert state['observation'] is None and state['plan_error'] is None and state['latest_decision_error'] is None
        observation = state.get('observation')
        if isinstance(observation, dict):
            port_model_states['observation_present'] += 1
            facts = observation.get('port_observations')
            if isinstance(facts, dict):
                port_model_states['port.' + facts['status']] += 1

receipt = {'schema': 'agent-new-internal-module-holdout-receipt-v1' , 'created_at_utc': datetime.now(timezone.utc).isoformat(),
           'source_revision': revision, 'registered_tasks': 108, 'defect_tasks_per_strategy': 12, 'correct_tasks_per_strategy': 6,
           'distinct_registered_defects': 4, 'repeats': 3, 'independent_holdout': registration.get('independent_holdout', False), 'external_independent_holdout': False, 'human_trial': False, 'H02_human_review': False,
           'requests': report['requests_attempted'], 'tokens': totals, 'round_token_cap': budget['limit'],
           'executed_tasks': sum(bool(r['rounds']) for r in rows), 'audited_rounds': sum(len(r['rounds']) for r in rows),
           'pipeline_sides': 2 * sum(len(r['rounds']) for r in rows), 'evidence_verified_tasks': sum(r['evidence_verified'] for r in summary['rows']),
           'unexecuted_tasks': [{'row_index': i, 'case': r['case'], 'variant': r['variant'], 'strategy': r['strategy'], 'seed': r['seed'],
                                'status': r['status']} for i, r in enumerate(rows) if not r['rounds']],
           'frozen_inputs': len(manifest['files']), 'snapshot_verified': True, 'changed_inputs_at_finish': [],
           'strict_comparison_eligible': summary['eligible_for_frozen_comparison'], 'schema_counts': dict(schema_counts),
           'format_rejections': sum(r['kind']=='decision_format' for r in rejections),
           'plan_budget_rejections': sum(r['kind']=='plan_budget' for r in rejections),
           'plan_preflight_rejections': sum(r['kind']=='plan_preflight' for r in rejections),
           'charged_reproposal_opportunities': len(rejections), 'recoveries': len(recoveries),
           'recovered_rejection_requests': sum(r.get('recovered_to_schema', False) for r in rejections),
           'executed_recovery_episodes': sum(r['executed_after_recovery'] for r in recoveries),
           'retained_rejection_artifacts': sum(r['response_status'] == 'saved' for r in rejections),
           'retained_response_artifacts': len(response_records), 'malformed_retained_response_artifacts': sum(r['parse_status'] == 'json_invalid' for r in response_records),
           'cohorts':cohorts, 'cohort_summaries':cohort_summaries,
           'source_byte_binding_counts':dict(Counter(b['binding'] for b in byte_bindings)),
           'strategies': summary['strategies'], 'correct_controls': controls, 'defect_matrix': matrix,
           'first_detection_rounds': {strategy: dict(Counter(r['first_detection_round'] for r in rows if r['strategy'] == strategy and r['detected']))
                                      for strategy in ('single', 'feedback', 'no_feedback')},
           'started_at_utc': report['started_at'], 'finished_at_utc': report['finished_at'],
           'wall_seconds': (datetime.fromisoformat(report['finished_at']) - datetime.fromisoformat(report['started_at'])).total_seconds(),
           'source_results_sha256': digest((raw_root / 'results.json').read_bytes()), 'source_summary_sha256': digest((raw_root / 'strict_summary.json').read_bytes()),
           'complete_raw_evidence': '.iverilog-ai/agent-new-holdout-study-live-20261005/',
           'public_copy_contains_all_execution_side_logs': True, 'public_copy_contains_api_trajectories_and_saved_responses': True,
           'cost_currency': None, 'artifacts': artifacts}
receipt['all_modules_previously_agent_exposed'] = False
receipt['new_holdout_modules'] = ['valid_data_pipeline', 'event_accumulator']
receipt['internal_controlled_module_set_holdout'] = True
receipt['independent_holdout_meaning'] = 'new module membership disjoint from five earlier controlled API batches; same-team synthetic designs and mutations, not external blindness'
receipt['training_data_unseen_claim'] = False
receipt['agent_frozen_from'] = 'a96933786c17986a739fc2da515db3294d6e8044'
receipt['new_oracle_adapters_are_not_agent_tuning'] = True
receipt['port_observation_episodes'] = dict(port_facts)
receipt['paid_model_observation_states'] = dict(port_model_states)
receipt['no_feedback_states_all_hidden'] = no_feedback_states
receipt['pre_execution_previous_accounting'] = registration.get('pre_execution_previous_accounting', [])
write(public / 'receipt.json', receipt)
ledger = {'schema': 'agent-per-round-budget-receipt-v1', 'round_name': registration['study']['name'],
          'round_scope': 'one complete preregistered evaluation batch; all API groups share the same 1M limit',
          'round_limit': 1_000_000, 'round_totals': totals, 'requests': report['requests_attempted'],
          'reported_prompt_tokens': sum(d['usage']['prompt_tokens'] for d in sent if d.get('usage')),
          'reported_completion_tokens': sum(d['usage']['completion_tokens'] for d in sent if d.get('usage')),
          'requests_with_usage': totals['requests_known_usage'], 'requests_without_usage': totals['requests_unknown_usage'],
          'theoretical_request_cap': 126, 'output_cap_per_request': 4096, 'thinking': 'disabled', 'stream': False,
          'automatic_transport_retries': 0, 'ordinary_format_reproposal_is_a_charged_new_request': True,
          'budget_reproposal_is_a_charged_new_request': True,
          'historical_tokens_deducted_from_round': False, 'historical_360_request_limit_is_current': False,
          'remaining_tokens_is_not_authorization_to_start_another_batch': True, 'actual_currency': None,
          'provider_billing_receipt_supplied': False, 'raw_journal_sha256': digest((raw_root / 'token_budget.json').read_bytes()),
          'public_journal': 'agent-new-holdout-study-live-2026-10-05/token_budget.json'}
write(root / 'docs/experiment/agent_new_holdout_study_budget_2026-10-05.json', ledger)
print(json.dumps({key: receipt[key] for key in ('requests', 'tokens', 'executed_tasks', 'audited_rounds', 'schema_counts',
    'format_rejections', 'plan_budget_rejections', 'recoveries', 'executed_recovery_episodes', 'strict_comparison_eligible')}, ensure_ascii=False))
