"""Read-only v3 fact-source audit over previously sealed receipts.

This is a material consistency check, not new API/DUT/source validation.
Every attempt retains its own snapshot, JSON, logs and receipt.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[5]
OWN=Path(__file__).resolve().parent
SOURCE=ROOT/'docs/competition/ic/v3/material_data.json'
CHECKS=[]
BOUND={}

def guard(event,args):
    if event.startswith('socket.') or event=='subprocess.Popen':
        raise RuntimeError('Network and process execution are prohibited in fact-source audit')
sys.addaudithook(guard)

def binding(path):
    data=path.read_bytes()
    item={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    BOUND[item['path']]=item
    return item

def read(path):
    binding(path)
    return json.loads(path.read_text(encoding='utf-8'))

def save(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')

def check(name,actual,expected,basis):
    assert name not in {item['id'] for item in CHECKS}
    status='passed' if actual==expected else 'failed'
    CHECKS.append({'id':name,'status':status,'actual':actual,'expected':expected,'basis':basis})

def verify_hash(name,item):
    measured=binding(ROOT/item['path'])
    check('source_sha:'+name,measured['sha256'],item['sha256'],item['path'])
    check('source_bytes:'+name,measured['bytes'],item['bytes'],item['path'])
    return read(ROOT/item['path'])

def compact_batch(name,material,receipt):
    for key,value in material.items():
        if key=='strategies':
            for strategy in value:
                original=receipt['strategies'][strategy['id']]
                for field,item in strategy.items():
                    if field in {'id','label'}: continue
                    expected=[row['detected'] for row in original['per_repeat']] if field=='repeat_detections' else original[field]
                    check(f'{name}/{strategy["id"]}/{field}',item,expected,name+' receipt.strategies')
        elif key=='unexecuted_task_count':
            check(name+'/'+key,value,len(receipt['unexecuted_tasks']),name+' receipt.unexecuted_tasks')
        else:
            check(name+'/'+key,value,receipt[key],name+' sealed receipt')
    strategies=material['strategies']
    check(name+'/strategy_order',[s['id'] for s in strategies],['fixed','random','protocol_random','single','feedback','no_feedback'],'registered strategy order')
    check(name+'/requests_sum',sum(s['requests'] for s in strategies),material['requests'],'sum retained strategies')
    check(name+'/correct_registered',sum(v['registered'] for v in material['correct_controls'].values()),material['correct_tasks_per_strategy']*6,'correct controls kept outside defect denominator')
    check(name+'/all_registered_rows_geometry',(material['defect_tasks_per_strategy']+material['correct_tasks_per_strategy'])*6,material['registered_tasks'],'six strategies including retained failures')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',required=True)
    args=parser.parse_args()
    assert re.fullmatch(r'facts-r[1-9][0-9]*',args.attempt)
    attempt=OWN/args.attempt
    attempt.mkdir(exist_ok=False)
    source_original=SOURCE.read_bytes()
    with (attempt/'material_data.original.json').open('xb') as stream:stream.write(source_original)
    material=read(SOURCE)
    origins={name:verify_hash(name,item) for name,item in material['sources'].items()}
    new,old,core,trace,budget,review=(origins[k] for k in ('new108_receipt','old432_receipt','core_audit','trace_audit','new108_budget','new108_review'))
    compact_batch('new108',material['latest_new108'],new)
    compact_batch('old432',material['historical_v8_432'],old)
    for key,value in material['new108_budget'].items():check('budget/'+key,value,budget[key],'sealed current batch budget receipt')
    counters=trace['counters']
    paid=trace['paid_model_state_port_facts']
    archive=next(a for a in core['archive']['archives'] if a['path'].endswith('/full_raw_evidence.zip'))
    raw_manifest=read(ROOT/'docs/experiment/agent-new-holdout-study-live-2026-10-05/full_raw_manifest.json')
    audit_expected={
        'non_feature_author_core_checks':core['unique_non_dut_check_units'],
        'core_check_parts':[core['audit_attempts'][1]['unique_non_dut_check_units'],core['final_command_and_observation_bindings']['unique_non_dut_check_units']],
        'trace_reviewer_is_entry_code_author':review['trace_reviewer_is_entry_code_author'],
        'trace_trajectories':trace['audited_agent_traces'],
        'output_values_recomputed':core['reference_output_values_recomputed'],
        'vcd_port_values_checked':core['wave_port_values_strictly_before_samples'],
        'raw_files':core['archive']['full_raw_files'],
        'raw_archive_bytes':archive['bytes'],
        'uncompressed_raw_file_bytes':sum(item['size_bytes'] for item in raw_manifest['files']),
        'raw_response_files':counters['raw_artifacts_verified'],
        'json_parseable_responses':sum(item['count'] for item in trace['response_distribution'] if item['reason']=='json_valid'),
        'raw_response_missing':sum(item['count'] for item in trace['response_distribution'] if item['status']!='saved'),
        'port_documents':counters['port_feedback_documents'],
        'port_raw_finite_samples':counters['port_feedback_total_samples'],
        'port_returned_samples':counters['port_feedback_returned_samples'],
        'port_omitted_samples':counters['port_feedback_omitted_samples'],
        'actual_feedback_states_with_ports':paid['by_strategy']['feedback']['port_facts_present'],
        'actual_sent_feedback_returned_samples':paid['by_strategy']['feedback']['port_returned_samples'],
        'actual_sent_feedback_omitted_samples':paid['by_strategy']['feedback']['port_omitted_samples'],
        'no_feedback_states':paid['by_strategy']['no_feedback']['all_three_diagnostics_none'],
        'format_rejected_paid_tokens':counters['format_rejected_paid_total_tokens'],
        'budget_rejected_paid_tokens':counters['budget_rejected_paid_total_tokens'],
        'human_or_H02':False,'new_API_requests':review['new_API_requests'],'new_DUT_runs':review['new_DUT_runs']}
    for kind,prefix in [('decision_format','format'),('plan_budget','budget')]:
        events=[event for event in trace['all_paid_rejection_events'] if event['kind']==kind]
        audit_expected[prefix+'_post_reject_executed_tasks']=len({event['sample'] for event in events if event['later_actual_episodes']})
        audit_expected[prefix+'_post_reject_detected_tasks']=len({event['sample'] for event in events if event['later_detection']})
        if prefix=='format':
            audit_expected['format_post_reject_executed_episodes']=len({(event['sample'],episode['round']) for event in events for episode in event['later_actual_episodes']})
    terminal=core['terminal_format_failures_retained']
    assert len(terminal)==1
    audit_expected.update({'terminal_format_failure_task_index_zero_based':terminal[0]['row_index'],
                          'terminal_format_failure_prior_episodes':terminal[0]['rounds'],
                          'terminal_format_failure_prior_stimulus_cycles':terminal[0]['cycles']})
    check('audit/field_set',sorted(material['new108_audit']),sorted(audit_expected),'precise fact source fields; ZIP size differs from uncompressed raw size')
    for key,value in audit_expected.items():check('audit/'+key,material['new108_audit'].get(key),value,'sealed core/trace/review originals')
    for key,value in material['historical_support'].items():check('historical_support/'+key,value,origins['historical_v2_material_data'][key],'unchanged historical v2 material_data; no new result substitution')
    validation_root=ROOT/'docs/experiment/agent-new-holdout-validation-2026-10-05/r2'
    engineering=read(validation_root/'receipt.json')
    for item in engineering['artifacts']:
        path=validation_root/item['path']
        measured=binding(path)
        check('engineering_original_sha/'+item['path'],measured['sha256'],item['sha256'],'previous r2 source validation; not rerun here')
    mypy=(validation_root/'mypy.log').read_text(encoding='utf-8')
    match=re.search(r'Success: no issues found in (\d+) source files',mypy)
    style=read(ROOT/'benchmarks/agent_new_holdout_20261005/validation/style/r3/deliverable_gate.json')
    engine_expected={'pytest_passed':engineering['passed'],'pytest_skipped':engineering['pytest']['skipped'],
                     'pytest_failed':engineering['pytest']['failures'],'mypy_files':int(match[1]) if match else None,
                     'mypy_errors':0 if match else None,'frozen_fingerprinted_files':engineering['fingerprinted_files'],
                     'changed_fingerprints':len(engineering['changed_inputs']),
                     'strict_rtl_style_issues_pending':12,'wavedrom_3_6_1_available':False}
    for key,value in material['latest_engineering'].items():check('engineering/'+key,value,engine_expected[key],'sealed full-source r2 receipt/mypy log and retained style/renderer caveat')
    interpretation_expected={'new_modules_same_team_synthetic':True,'agent_frozen_before_new_modules':core['frozen_agent_revision'],
        'externally_blind_or_pretraining_unseen_claim':False,'independent_timestamp_selection_before_old_v8_scores':False,
        'new_functional_coverage':'unsupported/unknown','finite_named_bins_scope':'24 named bins on four historical development configurations only',
        'no_feedback_preserves_own_budget_plan_and_executor_early_stop':True,'strict_complete_is_not_all_actions_successful':True,
        'significant_or_causal_or_industrial_gain_proven':False,'historical_v2_materials_unchanged':True,
        'new_API_calls_for_materials':0,'new_DUT_runs_for_materials':0}
    for key,value in material['interpretation'].items():check('interpretation/'+key,value,interpretation_expected[key],'sealed original evidence limits, not capability expansion')
    api_expected={'provider':'DeepSeek','model_reported':core['requests']['transport']['model'],'user_model_request':'4.1f',
                  'thinking':core['requests']['transport']['thinking'],'stream':core['requests']['transport']['stream'],
                  'store':core['requests']['transport']['store'],'timeout_seconds':core['requests']['transport']['timeout_seconds'],
                  'max_output_tokens':core['requests']['transport']['output_cap'],'transport_retries':core['requests']['transport']['automatic_retries']}
    for key,value in material['api'].items():check('api/'+key,value,api_expected[key],'actual recorded transport; user name not asserted as provider model version proof')
    check('new_control_execution',sum(v['executed'] for v in new['correct_controls'].values()),36,'new six correct tasks per strategy')
    check('old_control_execution',sum(v['executed'] for v in old['correct_controls'].values()),143,'historical one correct task unexecuted; no 144/144 claim')
    check('old_control_registered',sum(v['registered'] for v in old['correct_controls'].values()),144,'old registered correct denominator')
    check('new_defect_repeat_geometry',new['distinct_registered_defects']*new['repeats'],new['defect_tasks_per_strategy'],'4 distinct defects repeated 3 times; not 12 independent mutations')
    check('input_output_tokens',budget['reported_prompt_tokens']+budget['reported_completion_tokens'],budget['round_totals']['reported_tokens'],'input plus output; no currency assertion')
    check('rule_score_sum',sum(material['rules']['scoring'].values()),100,'root-read official scoring 30/30/30/10')
    check('rule_outline_count',len(material['rules']['seven_sections']),7,'root-read official seven-section outline')
    check('project_name_character_limit',len(material['project_name'])<=material['rules']['name_max_chinese_characters'],True,'conservative full Unicode character count')
    check('no_human_originals',material['human_trial_originals_provided'] or material['independent_human_review_originals_provided'],False,'machine review does not supply human evidence')
    check('source_unchanged_during_fact_audit',SOURCE.read_bytes()==source_original,True,'material snapshot at start versus finish')
    failed=[item for item in CHECKS if item['status']=='failed']
    result={'schema':'ic-v3-material-facts-readonly-review-v1','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'scope':'Only material_data fact source and copied/projection values against sealed evidence. Final Markdown/PPTX/PDF review is pending and is not approved by this result.',
            'reviewer':'AI machine reviewer; not formal human H02; no implementation edits in this material phase',
            'fact_consistency_passed':not failed,'unique_material_check_units':len(CHECKS),'passed':len(CHECKS)-len(failed),'failed':len(failed),
            'checks':CHECKS,'artifacts':list(BOUND.values()),'source_snapshot':binding(attempt/'material_data.original.json'),
            'source_style_gate_status':style.get('delivery_ready'),
            'rules_boundary':'Official URLs/date/format facts are supplied by root 2026-10-05 read; this tool does not refetch the web.',
            'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0,'new_source_tests':0,'reperformed_core_2192_checks':False,
            'final_materials_complete_review':False}
    save(attempt/'result.json',result)
    log={'fact_consistency_passed':result['fact_consistency_passed'],'unique_material_check_units':len(CHECKS),'failed':failed,'result':binding(attempt/'result.json')}
    save(attempt/'log.json',log)
    save(attempt/'receipt.json',{'schema':'ic-v3-material-fact-attempt-receipt-v1','result':binding(attempt/'result.json'),
                             'log':binding(attempt/'log.json'),'tool':binding(Path(__file__).resolve()),'source_snapshot':binding(attempt/'material_data.original.json'),
                             'new_API_requests':0,'credentials_read':0,'new_DUT_runs':0})
    print(json.dumps(log,ensure_ascii=False))
    return 0 if not failed else 1

if __name__=='__main__':raise SystemExit(main())
