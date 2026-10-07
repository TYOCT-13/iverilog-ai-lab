import hashlib
import itertools
import json
import sys
from pathlib import Path
sys.path.insert(0, str(project_root / 'src'))
from iverilog_ai.ai.schema import TestPlan
from iverilog_ai.core.contracts import DutContract
from iverilog_ai.core.pipeline import VerificationPipeline
from iverilog_ai.core.toolchain import locate_tools
root=project_root
work=package_root
assert json.loads((gate_path).read_text(encoding='utf-8'))['delivery_ready']
tools=locate_tools()
assert tools.can_simulate
logic=(0,1,"1'bx","1'bz")
plans=[]
combos=list(itertools.product(logic,repeat=3))
for part in range(2):
 vectors=[]
 for index,(clear,enable,event) in enumerate(combos[part*32:(part+1)*32],start=part*32):
  seed=1 if index%2==0 else 15
  prefix=f'case_{index}'
  vectors.extend([
   {'name':prefix+'_reset','inputs':{'i_rstn':0,'i_clear':0,'i_enable':0,'i_event':0},'sample_phase':'before'},
   {'name':prefix+'_seed','inputs':{'i_rstn':1,'i_clear':0,'i_enable':1,'i_event':1},'cycles':seed},
   {'name':prefix+'_pre_edge','inputs':{'i_rstn':1,'i_clear':clear,'i_enable':enable,'i_event':event},'sample_phase':'before'},
   {'name':prefix+'_after_edge','inputs':{},'cycles':1},
  ])
 if part==0:
  reset_unknowns=list(itertools.product(("1'bx","1'bz"),((0,1,1),(1,0,1),("1'bx",1,1),(0,"1'bz",1))))
  for index,(reset_value,(clear,enable,event)) in enumerate(reset_unknowns):
   prefix=f'unknown_reset_{index}'
   vectors.extend([
    {'name':prefix+'_clear','inputs':{'i_rstn':0,'i_clear':0,'i_enable':0,'i_event':0},'sample_phase':'before'},
    {'name':prefix+'_seed','inputs':{'i_rstn':1,'i_enable':1,'i_event':1},'cycles':3},
    {'name':prefix+'_off_edge','inputs':{'i_rstn':reset_value,'i_clear':clear,'i_enable':enable,'i_event':event},'sample_phase':'before'},
    {'name':prefix+'_after_edge','inputs':{}},
   ])
 plans.append(('event_accumulator',f'controls_part_{part}',vectors))
data_values=(0,1,165,255,"8'bx10z0x1z","8'bzzzzzzzz")
for part in range(2):
 vectors=[]
 for index,(reset_value,flush,valid) in enumerate(combos[part*32:(part+1)*32],start=part*32):
  prefix=f'case_{index}'
  history_valid=logic[(index//4)%4]
  data=data_values[index%len(data_values)]
  vectors.extend([
   {'name':prefix+'_reset','inputs':{'i_rstn':0,'i_flush':0,'i_valid':0,'i_data':0},'sample_phase':'before'},
   {'name':prefix+'_first_capture','inputs':{'i_rstn':1,'i_valid':1,'i_data':165}},
   {'name':prefix+'_history_capture','inputs':{'i_valid':history_valid,'i_data':60}},
   {'name':prefix+'_off_edge','inputs':{'i_rstn':reset_value,'i_flush':flush,'i_valid':valid,'i_data':data},'sample_phase':'before'},
   {'name':prefix+'_after_edge','inputs':{}},
   {'name':prefix+'_drain','inputs':{'i_rstn':1,'i_flush':0,'i_valid':0,'i_data':0},'cycles':2},
  ])
 plans.append(('valid_data_pipeline',f'controls_part_{part}',vectors))
records=[]
pairs=[]
coverage={}
for case,label,vectors in plans:
 contract=DutContract.from_json((root / f'benchmarks/agent_new_holdout_20261005/contracts/{case}_contract.json').read_bytes())
 plan=TestPlan.model_validate({'design':case,'clock_period_ns':10,'objective':'Four-state differential maintenance evidence; executor checks are disabled; equality is checked by the outer comparison','vectors':vectors})
 coverage[(case,label)]={'vectors':len(vectors),'sampled_cycles_per_side':sum(vector.cycles for vector in plan.vectors),'before_phase_samples_per_side':sum(vector.cycles for vector in plan.vectors if vector.sample_phase=='before')}
 observations={}
 for variant in ('A','B','C'):
  for side in ('original','candidate'):
   source=work / ('originals' if side=='original' else 'targets') / case / variant / f'{case}.v'
   out=output_root / 'validation/four-state' / case / label / variant / side
   result=VerificationPipeline(reference_policy='disabled').run(plan,contract,source,out,capture_observations=True,emit_vcd=False,iverilog_path=tools.iverilog,vvp_path=tools.vvp,max_output_chars=4_000_000,timeout_seconds=30)
   assert result.simulation is not None
   packet=json.loads(Path(result.artifacts['observed_samples']).read_text(encoding='utf-8'))
   actual=packet['samples']
   record={'case':case,'label':label,'variant':variant,'side':side,'directory':str(out),'source':str(source),'compile_exitcode':result.simulation.compile.returncode,'run_exitcode':result.simulation.run.returncode,'executor_verdict':result.simulation.verdict,'executor_check_count':result.simulation.check_count,'observed_cycles':packet['observed_cycles'],'DUT_executions':int(result.simulation.run.returncode is not None),'samples_sha256':hashlib.sha256(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
   records.append(record)
   (output_root / 'validation/four-state/progress.json').write_text(json.dumps({'DUT_executions':sum(item['DUT_executions'] for item in records),'records':records},ensure_ascii=False,indent=2),encoding='utf-8')
   assert record['compile_exitcode']==0 and record['run_exitcode']==0,record
   assert packet['status']=='complete',packet['status']
   assert record['executor_check_count']==0,record
   assert len(actual)==coverage[(case,label)]['sampled_cycles_per_side'],record
   observations[(variant,side)]=actual
  left=observations[(variant,'original')]
  right=observations[(variant,'candidate')]
  different=[{'row':index,'original':original,'candidate':candidate} for index,(original,candidate) in enumerate(zip(left,right)) if original!=candidate]
  compare={'case':case,'label':label,'variant':variant,'equal_samples':not different,'sampled_rows_per_side':len(left),'binary_four_state_output_comparisons':len(left)*len(contract.outputs),'differences':different[:20]}
  pairs.append(compare)
  assert compare['equal_samples'],compare
summary={'schema':'icarus-four-state-style-equivalence-v1','status':'passed','tools':tools.to_dict(),'DUT_executions':sum(item['DUT_executions'] for item in records),'API_requests':0,'is_new_API_experiment_score':False,'pairs':pairs,'records':records,'coverage':[{'case':case,'label':label,**value} for (case,label),value in coverage.items()],'limitations':['Simulation equality on these samples is not formal equivalence or synthesis/timing evidence.','Each project-generated observation driver has zero built-in assertion checks; the reported pass comes from the explicit outer row-by-row original/candidate equality comparison.','Before-phase observations are used only for maintenance/reset evidence and do not change the frozen public API contract or trials.','Counter checks all 64 clear/enable/event four-state control combinations at alternating count seeds 1 and 15, plus 8 unknown-reset scenarios.','Pipeline checks all 64 reset/flush/valid four-state combinations, all four captured-valid history states, and known plus mixed-X/Z payload patterns.']}
(output_root / 'validation/four-state/summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':summary['status'],'DUT_executions':summary['DUT_executions'],'pairs':[{key:value for key,value in pair.items() if key!='differences'} for pair in pairs],'coverage':summary['coverage']},ensure_ascii=False))