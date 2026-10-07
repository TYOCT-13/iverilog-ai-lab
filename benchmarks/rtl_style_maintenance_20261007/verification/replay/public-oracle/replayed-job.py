import json
import sys
from pathlib import Path
sys.path.insert(0, str(project_root / 'src'))
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools
root = project_root
work = package_root
assert json.loads((gate_path).read_text(encoding='utf-8'))['delivery_ready']
tools = locate_tools()
assert tools.can_simulate, tools.to_dict()
plans = {
 'event_accumulator': [
  {'name':'fill_and_wrap','inputs':{'i_rstn':1,'i_enable':1,'i_event':1,'i_clear':0},'cycles':17},
  {'name':'disabled_event','inputs':{'i_enable':0},'cycles':1},
  {'name':'clear_disabled','inputs':{'i_event':0,'i_clear':1},'cycles':1},
  {'name':'clear_priority','inputs':{'i_enable':1,'i_event':1},'cycles':1},
  {'name':'resume','inputs':{'i_clear':0},'cycles':2},
  {'name':'idle','inputs':{'i_event':0},'cycles':1},
  {'name':'explicit_reset','inputs':{'i_rstn':0,'i_event':1},'cycles':2},
  {'name':'release_reset','inputs':{'i_rstn':1},'cycles':2},
 ],
 'valid_data_pipeline': [
  {'name':'accept','inputs':{'i_rstn':1,'i_flush':0,'i_valid':1,'i_data':165}},
  {'name':'flush_pending','inputs':{'i_flush':1,'i_valid':0,'i_data':0}},
  {'name':'release_empty','inputs':{'i_flush':0}},
  {'name':'restart','inputs':{'i_valid':1,'i_data':129}},
  {'name':'continuous','inputs':{'i_data':60}},
  {'name':'bubble','inputs':{'i_valid':0},'cycles':2},
  {'name':'flush_valid_conflict','inputs':{'i_flush':1,'i_valid':1,'i_data':126}},
  {'name':'drain_flushed','inputs':{'i_flush':0,'i_valid':0},'cycles':2},
  {'name':'explicit_reset','inputs':{'i_rstn':0},'cycles':2},
  {'name':'release_reset','inputs':{'i_rstn':1,'i_valid':1,'i_data':255}},
  {'name':'drain','inputs':{'i_valid':0},'cycles':2},
 ]
}
records=[]
pairs=[]
for case, vectors in plans.items():
 contract=DutContract.from_json((root / f'benchmarks/agent_new_holdout_20261005/contracts/{case}_contract.json').read_bytes())
 plan=TestPlan.model_validate({'design':case,'clock_period_ns':10,'objective':'Local maintenance semantics comparison; not an API experiment or score','vectors':vectors})
 observations={}
 results={}
 for variant in ('A','B','C'):
  for side in ('original','candidate'):
   source=work / ('originals' if side=='original' else 'targets') / case / variant / f'{case}.v'
   out=output_root / 'validation/public-oracle' / case / variant / side
   result=VerificationPipeline().run(plan,contract,source,out,reference_sampling='per_cycle',capture_observations=True,emit_vcd=False,iverilog_path=tools.iverilog,vvp_path=tools.vvp)
   assert result.simulation is not None
   packet=json.loads(Path(result.artifacts['observed_samples']).read_text(encoding='utf-8'))
   record={'case':case,'variant':variant,'side':side,'source':str(source),'directory':str(out),'compile_exitcode':result.simulation.compile.returncode,'run_exitcode':result.simulation.run.returncode,'verdict':result.simulation.verdict,'check_count':result.simulation.check_count,'failures':result.simulation.summary['failures'],'observed_cycles':packet['observed_cycles'],'DUT_executions':int(result.simulation.run.returncode is not None)}
   records.append(record)
   (output_root / 'validation/public-oracle/progress.json').write_text(json.dumps({'DUT_executions':sum(item['DUT_executions'] for item in records),'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
   assert record['compile_exitcode']==0 and record['run_exitcode']==0, record
   assert packet['status']=='complete'
   expected='passed' if variant=='A' else 'failed_checks'
   assert result.simulation.verdict==expected, record
   observations[(variant,side)]=packet['samples']
   results[(variant,side)]=record
  left=results[(variant,'original')]
  right=results[(variant,'candidate')]
  assert observations[(variant,'original')]==observations[(variant,'candidate')], (case,variant,'observations differ')
  assert left['failures']==right['failures'] and left['verdict']==right['verdict'], (case,variant,'oracle behavior differs')
  pairs.append({'case':case,'variant':variant,'same_actual_samples':True,'same_oracle_verdict':True,'original_and_candidate_failures':left['failures'],'cycles_per_side':left['observed_cycles'],'checks_per_side':left['check_count']})
summary={'schema':'icarus-public-oracle-style-equivalence-v1','status':'passed','tools':tools.to_dict(),'DUT_executions':sum(item['DUT_executions'] for item in records),'API_requests':0,'is_new_API_experiment_score':False,'pairs':pairs,'records':records,'limitations':['Binary public-contract observation equality is maintenance evidence, not exhaustive proof.','B/C retain known incorrect functional behavior; failed_checks is required for mutation controls.','Counter maintenance plan has 27 cycles, independently of the frozen API trial budgets.']}
(output_root / 'validation/public-oracle/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':summary['status'],'DUT_executions':summary['DUT_executions'],'pairs':pairs},ensure_ascii=False))