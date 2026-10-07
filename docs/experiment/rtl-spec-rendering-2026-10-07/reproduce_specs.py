"""Rebuild the two declared specification diagrams with the installed skill."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--skill-root', type=Path,
                        default=Path.home() / '.codex/skills/readable-verilog-generator')
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    repo = package.parents[2]
    out = args.out_dir.resolve()
    skill = args.skill_root.resolve()
    if not out.is_relative_to(repo) or out == repo or out.exists():
        parser.error('--out-dir must be a fresh directory inside this repository')
    if not (skill / 'scripts/python/workflow/cli.py').is_file():
        parser.error('the installed readable-verilog-generator skill is required')
    spec = package / 'inputs/render_spec_document.json'
    if sha(spec) != '79280af213a62c1b0172658bedb930c112f4b54cffce3ede5a06a871d79c7417':
        parser.error('render specification bytes differ from the frozen rendering input')
    expected_sources = {
        'event_accumulator': '4f8137509bc2116624f8c444f5e6d0bca319f6b2993371610dd2c2432c44d071',
        'valid_data_pipeline': 'b3fc81d4fdf3a23cb38c710af7c6d278cfba9d3f52978492594263464e44d9bb',
    }
    sources = []
    for name, expected_sha in expected_sources.items():
        source = package / 'inputs/targets' / name / 'A' / (name + '.v')
        if sha(source) != expected_sha:
            parser.error('RTL input bytes differ: ' + name)
        sources.append(source)
    out.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(skill) + os.pathsep + env.get('PYTHONPATH', '')
    commands = []

    def run(label: str, argv: list[str]) -> int:
        started = time.monotonic()
        result = subprocess.run(argv, cwd=repo, env=env, capture_output=True,
                                timeout=180)
        (out / (label + '.stdout.txt')).write_bytes(result.stdout)
        (out / (label + '.stderr.txt')).write_bytes(result.stderr)
        (out / (label + '.exitcode.txt')).write_text(str(result.returncode), encoding='utf-8')
        commands.append({'label': label, 'argv': argv, 'cwd': str(repo),
                         'pythonpath': str(skill), 'returncode': result.returncode,
                         'duration_seconds': round(time.monotonic() - started, 3),
                         'stdout_sha256': hashlib.sha256(result.stdout).hexdigest(),
                         'stderr_sha256': hashlib.sha256(result.stderr).hexdigest()})
        if result.stderr:
            print(result.stderr.decode('utf-8', errors='replace'), file=sys.stderr)
        return result.returncode

    settings = skill / 'config/defaults.json'
    prefix = [sys.executable, '-B', '-X', 'utf8', '-m']
    result_code = run('renderer-check', prefix + [
        'scripts.python.toolchain.wavedrom_runtime', '--settings', str(settings), 'check'])
    if result_code == 0:
        check = json.loads((out / 'renderer-check.stdout.txt').read_text(encoding='utf-8'))
        if not (check.get('ok') and check['smoke'].get('ok')
                and check['wavedrom'].get('version') == '3.6.1'):
            result_code = 1
    if result_code == 0:
        argv = prefix + ['scripts.python.workflow.cli', 'write-spec', '--spec', str(spec),
                         '--out-dir', str(out / 'bundle')]
        for source in sources:
            argv += ['--source', str(source)]
        argv += ['--language', 'zh', '--no-state']
        result_code = run('write-spec', argv)
    comparisons = []
    if result_code == 0:
        reference = package / 'bundle'
        expected = {p.relative_to(reference).as_posix(): sha(p)
                    for p in reference.rglob('*') if p.is_file()}
        actual = {p.relative_to(out / 'bundle').as_posix(): sha(p)
                  for p in (out / 'bundle').rglob('*') if p.is_file()}
        for relative in sorted(set(expected) | set(actual)):
            comparisons.append({'path': relative, 'expected_sha256': expected.get(relative),
                                'actual_sha256': actual.get(relative),
                                'matches': expected.get(relative) == actual.get(relative)})
        if len(expected) != 6 or actual != expected:
            result_code = 1
    receipt = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
               'status': 'passed' if result_code == 0 else 'failed',
               'commands': commands, 'comparisons': comparisons,
               'new_model_api_requests': 0, 'new_dut_executions': 0,
               'scope': 'local declared-spec rendering; not a new simulation or model study',
               'installation_performed': False}
    (out / 'reproduction_receipt.json').write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'files_compared': len(comparisons),
                      'out_dir': str(out)}, ensure_ascii=False))
    return result_code


if __name__ == '__main__':
    raise SystemExit(main())
