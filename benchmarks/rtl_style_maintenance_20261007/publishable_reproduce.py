"""Reproduce the published RTL maintenance package without changing its inputs."""
import argparse
import ast
import contextlib
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import traceback


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inside(path, root):
    return path == root or root in path.parents


def input_path(root, relative):
    relative_path = PurePosixPath(relative)
    require(not relative_path.is_absolute() and '..' not in relative_path.parts, ('unsafe input path', relative))
    result = (root / relative).resolve()
    require(inside(result, root), ('input escaped its root', relative))
    return result


def find_project(package, explicit):
    if explicit:
        candidates = [Path(explicit).resolve()]
    else:
        candidates = [package, *package.parents]
    for candidate in candidates:
        if (candidate / 'pyproject.toml').is_file() and (candidate / 'src/iverilog_ai').is_dir():
            return candidate
    raise AssertionError('Cannot infer the project root; pass --project-root containing pyproject.toml and src/iverilog_ai.')


def verify_inputs(package, project):
    manifest_path = package / 'publishable_inputs.json'
    manifest = load_json(manifest_path)
    require(manifest['schema'] == 'rtl-style-maintenance-publishable-inputs-v1', 'unexpected input manifest schema')
    require(len(manifest['required_inputs']) == 35, 'expected 35 RTL/spec/verification input files')
    seen = set()
    for item in manifest['required_inputs']:
        require(item['public_path'] not in seen, 'duplicate public input')
        seen.add(item['public_path'])
        path = input_path(package, item['public_path'])
        require(path.is_file() and path.stat().st_size == item['bytes'], ('missing or changed input length', item['public_path']))
        require(digest(path) == item['sha256'], ('changed input digest', item['public_path']))
    for item in manifest['project_inputs']:
        path = input_path(project, item['project_path'])
        require(path.is_file() and digest(path) == item['sha256'], ('changed project contract', item['project_path']))
    require(digest(Path(__file__).resolve()) == manifest['entrypoint']['sha256'], 'changed reproduction entrypoint')
    for variant in ('A', 'B', 'C'):
        document = load_json(package / f'verification/spec-input/{variant}.spec.json')
        require({module['name'] for module in document['modules']} == {'event_accumulator', 'valid_data_pipeline'}, 'unexpected specification modules')
        for module in document['modules']:
            name = module['name']
            require(module['rtl_path'] == f'targets/{name}/{variant}/{name}.v', 'unexpected specification RTL path')
            require(len(module['timing_diagrams']) == 1, 'expected one behavior diagram per module')
            wavejson = module['timing_diagrams'][0]['wavejson']
            final_wave = load_json(package / f'spec/targets/{name}/{variant}/waveforms/{name}_variant-behavior.json5')
            require(wavejson == final_wave, ('spec input must match final corrected hold encoding', name, variant))
            for signal in wavejson['signal']:
                wave = signal.get('wave', '')
                if wave and set(wave) <= set('01.'):
                    previous = None
                    for char in wave:
                        if char in '01':
                            require(char != previous, ('binary level must use a hold dot when repeated', name, variant, signal['name']))
                            previous = char
                        else:
                            require(previous is not None, 'unbound binary hold')
    return manifest, manifest_path


def redirect_saved_job(source, phase):
    """Assert eight path edits and preserve every other Python AST element."""
    tree = ast.parse(source)
    selected = []

    def edit(node, replacement, reason):
        selected.append((node, replacement, reason))

    def assignments(name):
        return [node for node in ast.walk(tree) if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name]

    root_assign = assignments('root')
    work_assign = assignments('work')
    require(len(root_assign) == len(work_assign) == 1, 'expected one project-root and one package-root assignment')
    root_value = root_assign[0].value
    require(isinstance(root_value, ast.Call) and isinstance(root_value.func, ast.Name) and root_value.func.id == 'Path' and len(root_value.args) == 1 and isinstance(root_value.args[0], ast.Constant) and isinstance(root_value.args[0].value, str), 'unexpected saved project-root expression')
    work_value = work_assign[0].value
    require(isinstance(work_value, ast.BinOp) and isinstance(work_value.op, ast.Div) and isinstance(work_value.left, ast.Name) and work_value.left.id == 'root' and isinstance(work_value.right, ast.Constant) and isinstance(work_value.right.value, str), 'unexpected saved package-root expression')
    edit(root_value, 'project_root', 'project root only')
    edit(work_value, 'package_root', 'package root only')

    import_paths = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and ast.unparse(node.func) == 'sys.path.insert']
    require(len(import_paths) == 1, 'expected one project import path')
    call = import_paths[0]
    require(len(call.args) == 2 and isinstance(call.args[0], ast.Constant) and call.args[0].value == 0 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str), 'unexpected saved import-path expression')
    edit(call.args[1], "str(project_root / 'src')", 'project source import location only')

    work_paths = [node for node in ast.walk(tree) if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.left, ast.Name) and node.left.id == 'work' and isinstance(node.right, ast.Constant) and isinstance(node.right.value, str)]
    gate_paths = [node for node in work_paths if node.right.value.endswith('/deliverable_gate.json')]
    require(len(gate_paths) == 1, 'expected one readiness report path')
    edit(gate_paths[0], 'gate_path', 'fresh official gate result location only')
    expected_outputs = {f'validation/{phase}', f'validation/{phase}/progress.json', f'validation/{phase}/summary.json'}
    output_paths = [node for node in work_paths if node.right.value in expected_outputs]
    require(len(output_paths) == 3 and {node.right.value for node in output_paths} == expected_outputs, 'expected exactly three output locations')
    require(len(work_paths) == 4, 'unexpected unredirected package-relative path expression')
    for node in output_paths:
        edit(node, f'output_root / {node.right.value!r}', 'result location only')

    source_assign = assignments('source')
    require(len(source_assign) == 1, 'expected one DUT source selection')
    selections = [node for node in ast.walk(source_assign[0].value) if isinstance(node, ast.IfExp)]
    require(len(selections) == 1, 'expected one original/candidate selection')
    selection = selections[0]
    require(ast.dump(selection.test, include_attributes=False) == ast.dump(ast.parse("side == 'original'", mode='eval').body, include_attributes=False), 'original/candidate condition changed')
    require(isinstance(selection.body, ast.Constant) and selection.body.value == 'originals', 'unexpected original source directory')
    require(isinstance(selection.orelse, ast.Constant) and isinstance(selection.orelse.value, str) and PurePosixPath(selection.orelse.value).parts[-1] == 'targets', 'unexpected candidate source directory')
    edit(selection.orelse, "'targets'", 'candidate source location only')
    require(len(selected) == 8, 'expected exactly eight explicit path replacements')

    encoded = source.encode('utf-8')
    lines = encoded.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    ranges = []
    for node, replacement, reason in selected:
        start = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        require(start < end, 'invalid path replacement span')
        ranges.append((start, end, replacement.encode('utf-8'), reason))
    ascending = sorted(ranges)
    require(all(left[1] <= right[0] for left, right in zip(ascending, ascending[1:])), 'overlapping path replacements')
    transformed = encoded
    for start, end, replacement, _ in sorted(ranges, reverse=True):
        transformed = transformed[:start] + replacement + transformed[end:]

    replacements = {id(node): ast.parse(replacement, mode='eval').body for node, replacement, _ in selected}
    class ExpectedPathTransformer(ast.NodeTransformer):
        def visit(self, node):
            if id(node) in replacements:
                return ast.copy_location(copy.deepcopy(replacements[id(node)]), node)
            return super().visit(node)

    expected_tree = ExpectedPathTransformer().visit(tree)
    text = transformed.decode('utf-8')
    require(ast.dump(ast.parse(text), include_attributes=False) == ast.dump(expected_tree, include_attributes=False), 'a non-path AST element changed')
    report = {'path_replacement_count': 8, 'all_non_path_AST_elements_unchanged': True, 'vectors_predicates_and_comparisons_changed': False, 'edits': [{'original_expression': encoded[start:end].decode('utf-8'), 'replacement_expression': replacement.decode('utf-8'), 'reason': reason} for start, end, replacement, reason in ascending]}
    return text, report


def run_registered(arguments, output, label, project, skill):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(skill)
    command = [sys.executable, '-B', '-X', 'utf8', *arguments]
    with (output / f'{label}.stdout.txt').open('w', encoding='utf-8') as stdout, (output / f'{label}.stderr.txt').open('w', encoding='utf-8') as stderr:
        result = subprocess.run(command, cwd=project, env=env, stdout=stdout, stderr=stderr, check=False)
    (output / f'{label}.exit.json').write_text(json.dumps({'command': command, 'cwd': str(project), 'exit_code': result.returncode}, ensure_ascii=False, indent=2), encoding='utf-8')
    require(result.returncode == 0, (label, result.returncode))


def run_semantics(phase, package, project, output, gate_path):
    phase_output = output / 'validation' / phase
    phase_output.mkdir(parents=True)
    saved_job = package / 'verification' / phase / 'job-source.txt'
    transformed, path_report = redirect_saved_job(saved_job.read_text(encoding='utf-8-sig'), phase)
    (phase_output / 'path_replacements.json').write_text(json.dumps(path_report, ensure_ascii=False, indent=2), encoding='utf-8')
    (phase_output / 'replayed-job.py').write_text(transformed, encoding='utf-8')
    exitcode = 0
    prior_cwd = Path.cwd()
    try:
        os.chdir(project)
        with (phase_output / 'stdout.txt').open('w', encoding='utf-8') as stdout, (phase_output / 'stderr.txt').open('w', encoding='utf-8') as stderr:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                try:
                    exec(compile(transformed, str(saved_job), 'exec'), {'__name__': '__main__', 'project_root': project, 'package_root': package, 'output_root': output, 'gate_path': gate_path})
                except BaseException:
                    exitcode = 1
                    traceback.print_exc()
    finally:
        os.chdir(prior_cwd)
    (phase_output / 'exit.json').write_text(json.dumps({'exit_code': exitcode, 'preserved_source': str(saved_job), 'preserved_source_sha256': digest(saved_job), 'vectors_predicates_and_comparisons_changed': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    require(exitcode == 0, (phase, exitcode))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True, help='New output directory inside the project; relative paths are relative to the project root.')
    parser.add_argument('--mode', choices=('gate', 'spec', 'semantics', 'all'), default='all', help='semantics includes the prerequisite official source gate.')
    parser.add_argument('--skill-root', required=True, help='Installed readable-verilog-generator skill root; no installation is performed.')
    parser.add_argument('--project-root', help='Optional explicit project root; otherwise inferred from package ancestors.')
    parser.add_argument('--package-root', help='Optional published package directory; otherwise this script directory.')
    args = parser.parse_args()
    package = Path(args.package_root).resolve() if args.package_root else Path(__file__).resolve().parent
    project = find_project(package, args.project_root)
    require(inside(package, project), 'published package must be inside the project')
    skill = Path(args.skill_root).resolve()
    require((skill / 'scripts/python/validation/generated_deliverable_gate.py').is_file(), 'missing official gate module')
    require((skill / 'scripts/python/workflow/cli.py').is_file(), 'missing registered workflow CLI')
    manifest, manifest_path = verify_inputs(package, project)
    output = Path(args.out_dir)
    output = (output if output.is_absolute() else project / output).resolve()
    require(inside(output, project), '--out-dir must stay inside the project')
    require(not output.exists(), '--out-dir already exists; choose a new directory')
    require(not any(inside(output, package / name) for name in ('targets', 'originals', 'spec', 'verification')), '--out-dir must not be inside published input directories')
    for phase in ('public-oracle', 'four-state'):
        source = (package / f'verification/{phase}/job-source.txt').read_text(encoding='utf-8-sig')
        redirect_saved_job(source, phase)
    output.mkdir(parents=True)
    record = {'schema': 'rtl-style-maintenance-published-replay-v1', 'mode': args.mode, 'project_root': str(project), 'package_root': str(package), 'output_directory': str(output), 'python': sys.executable, 'skill_root': str(skill), 'input_manifest_sha256': digest(manifest_path), 'API_requests': 0, 'new_DUT_executions': 0, 'is_new_API_experiment_score': False, 'validation_role': 'repeat of the same preserved vectors, not independent new samples', 'phases': []}
    gate_path = output / 'gate/deliverable_gate.json'
    try:
        if args.mode in ('gate', 'semantics', 'all'):
            gate_path.parent.mkdir()
            run_registered(['-m', 'scripts.python.validation.generated_deliverable_gate', str(package / 'targets'), '--json', str(gate_path), '--markdown', str(gate_path.with_suffix('.md'))], gate_path.parent, 'official-gate', project, skill)
            require(load_json(gate_path)['delivery_ready'], 'fresh official source gate failed')
            record['phases'].append('official-gate')
            record['official_gate_report'] = str(gate_path)
        if args.mode in ('spec', 'all'):
            logs = output / 'spec-logs'
            logs.mkdir()
            for variant in ('A', 'B', 'C'):
                sources = [package / f'targets/{name}/{variant}/{name}.v' for name in ('event_accumulator', 'valid_data_pipeline')]
                spec_input = package / f'verification/spec-input/{variant}.spec.json'
                run_registered(['-m', 'scripts.python.workflow.cli', 'write-spec', '--spec', str(spec_input), '--out-dir', str(output / 'bundle'), '--source', str(sources[0]), '--source', str(sources[1]), '--language', 'zh', '--no-state'], logs, variant, project, skill)
                for module in load_json(spec_input)['modules']:
                    name = module['name']
                    actual = load_json(output / f'bundle/spec/targets/{name}/{variant}/waveforms/{name}_variant-behavior.json5')
                    require(actual == module['timing_diagrams'][0]['wavejson'], ('actual rendered WaveJSON differs from corrected spec', name, variant))
            record['phases'].append('registered-write-spec-corrected-hold-inputs')
        if args.mode in ('semantics', 'all'):
            for phase in ('public-oracle', 'four-state'):
                run_semantics(phase, package, project, output, gate_path)
                record['phases'].append(phase)
            public = load_json(output / 'validation/public-oracle/summary.json')
            four = load_json(output / 'validation/four-state/summary.json')
            require(public['DUT_executions'] == 12 and four['DUT_executions'] == 24, 'unexpected DUT execution count')
            record['public_oracle_DUT_executions'] = 12
            record['four_state_DUT_executions'] = 24
            record['all_original_candidate_comparisons_equal'] = True
        record['status'] = 'passed'
    except BaseException:
        record['status'] = 'failed'
        raise
    finally:
        record['new_DUT_executions'] = sum(load_json(path)['DUT_executions'] for path in (output / 'validation').glob('*/progress.json'))
        (output / 'replay_receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(record, ensure_ascii=False))


if __name__ == '__main__':
    main()
