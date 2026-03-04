from flask import Flask, request, jsonify
import requests
import os
import subprocess
import json
import pathlib

app = Flask(__name__)

SCRUM_PIPELINE = [
    'senior-product-manager',
    'product-owner',
    'ux-designer-senior',
    'senior-database-engineer',
    'sw-architect',
    'senior-developer',
    'senior-frontend-developer',
    'senior-qa-engineer',
]

PYTHON = os.environ.get('BISSET_PYTHON', 'python3')
MAX_ITERATIONS = int(os.environ.get('MAX_LOOP_ITERATIONS', 10))
COVERAGE_THRESHOLD = int(os.environ.get('COVERAGE_THRESHOLD', 80))


def _agent_url(agent):
    key = f"AGENT_{agent.upper().replace('-', '_')}_URL"
    return os.environ.get(key, f"http://agent-{agent}:8000/webhook")


def _write_gherkin_files(project_dir: str, gherkin: dict) -> list:
    base = pathlib.Path(project_dir) / 'features'
    base.mkdir(parents=True, exist_ok=True)
    (base / 'steps').mkdir(exist_ok=True)
    written = []
    for f in gherkin.get('features', []):
        p = base / f['filename']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f['content'])
        written.append(str(p))
    for s in gherkin.get('steps', []):
        p = base / s['filename']
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(s['content'])
        written.append(str(p))
    return written


def _run_behave_coverage(project_dir: str) -> dict:
    env = {**os.environ, 'PYTHONPATH': project_dir}
    cov_run = subprocess.run(
        [PYTHON, '-m', 'coverage', 'run', '--source', project_dir,
         '-m', 'behave', '--no-capture', '--format', 'json', '-o', '/tmp/behave_out.json'],
        cwd=project_dir, capture_output=True, text=True, env=env, timeout=120
    )
    subprocess.run(
        [PYTHON, '-m', 'coverage', 'json', '-o', '/tmp/cov_report.json'],
        cwd=project_dir, capture_output=True, text=True, env=env, timeout=30
    )
    coverage_pct = 0
    missing_lines = []
    try:
        cov_data = json.loads(pathlib.Path('/tmp/cov_report.json').read_text())
        coverage_pct = int(cov_data.get('totals', {}).get('percent_covered', 0))
        for fname, fdata in cov_data.get('files', {}).items():
            if fdata.get('missing_lines'):
                missing_lines.append({'file': fname, 'lines': fdata['missing_lines']})
    except Exception:
        pass
    passing_scenarios, failing_scenarios = [], []
    try:
        behave_data = json.loads(pathlib.Path('/tmp/behave_out.json').read_text())
        for feature in behave_data:
            for scenario in feature.get('elements', []):
                failed_steps = [s for s in scenario.get('steps', []) if s.get('result', {}).get('status') == 'failed']
                info = {'feature': feature.get('name'), 'scenario': scenario.get('name')}
                if failed_steps:
                    info['error'] = failed_steps[0].get('result', {}).get('error_message', '')
                    failing_scenarios.append(info)
                else:
                    passing_scenarios.append(info)
    except Exception:
        failing_scenarios = [{'scenario': 'parse error', 'error': cov_run.stderr[:500]}]
    return {
        'coverage_pct': coverage_pct,
        'passing_scenarios': passing_scenarios,
        'failing_scenarios': failing_scenarios,
        'missing_lines': missing_lines,
    }

@app.route('/run_coverage', methods=['POST'])
def run_coverage():
    data = request.json or {}
    project_dir = data.get('project_dir', '').strip()
    if not project_dir:
        return jsonify({'error': 'project_dir required'}), 400
    if not pathlib.Path(project_dir).is_dir():
        return jsonify({'error': f'directory not found: {project_dir}'}), 400
    try:
        result = _run_behave_coverage(project_dir)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/sprint_with_loop', methods=['POST'])
def sprint_with_loop():
    data = request.json or {}
    project = data.get('project', '').strip()
    project_dir = data.get('project_dir', '').strip()
    if not project:
        return jsonify({'error': 'project description required'}), 400
    if not project_dir:
        return jsonify({'error': 'project_dir required'}), 400
    if not pathlib.Path(project_dir).is_dir():
        return jsonify({'error': f'directory not found: {project_dir}'}), 400

    port = int(os.environ.get('PORT', 8080))
    # 1. Run full sprint to get initial code + gherkin
    try:
        sprint_resp = requests.post(f'http://localhost:{port}/sprint', json={'project': project}, timeout=300)
        sprint_data = sprint_resp.json()
    except Exception as e:
        return jsonify({'error': f'sprint failed: {e}'}), 500

    context = sprint_data.get('final_context', [])

    # 2. Extract gherkin from QA agent output
    gherkin_output = None
    for entry in context:
        if 'qa' in entry.get('by', '').lower():
            try:
                gherkin_output = json.loads(entry['output']) if isinstance(entry['output'], str) else entry['output']
            except Exception:
                pass

    if gherkin_output:
        _write_gherkin_files(project_dir, gherkin_output)

    # 3. Loop: run coverage, fix if needed
    coverage_history = []
    iteration = 0
    passed = False

    while iteration < MAX_ITERATIONS:
        iteration += 1
        cov = _run_behave_coverage(project_dir)
        coverage_history.append({'iteration': iteration, **cov})

        if cov['coverage_pct'] >= COVERAGE_THRESHOLD and not cov['failing_scenarios']:
            passed = True
            break

        if not cov['failing_scenarios']:
            # No failures but coverage < threshold — no targeted fix possible
            break

        # Call senior-developer in fix mode
        fix_payload = {
            'mode': 'fix',
            'failing_tests': cov['failing_scenarios'],
            'coverage_pct': cov['coverage_pct'],
            'missing_lines': cov['missing_lines'],
            'context': context,
        }
        url = _agent_url('senior-developer')
        try:
            r = requests.post(url, json=fix_payload, timeout=120)
            fix_body = r.json()
            context.append({'by': 'senior-developer (fix)', 'output': fix_body.get('output', '')})
        except Exception as e:
            coverage_history[-1]['fix_error'] = str(e)
            break

    return jsonify({
        'sprint_results': sprint_data.get('sprint_results', []),
        'coverage_history': coverage_history,
        'final_coverage': coverage_history[-1]['coverage_pct'] if coverage_history else 0,
        'iterations': iteration,
        'passed': passed,
    })


@app.route('/dispatch', methods=['POST'])
def dispatch():
    data = request.json or {}
    agent = data.get('agent')
    task = data.get('task', {})
    context = data.get('context', [])
    if not agent:
        return jsonify({'error': 'agent required'}), 400
    url = _agent_url(agent)
    try:
        r = requests.post(url, json={**task, 'context': context}, timeout=120)
        return jsonify({'dispatched_to': agent, 'status_code': r.status_code, 'response': r.json()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/sprint', methods=['POST'])
def sprint():
    data = request.json or {}
    project = data.get('project', '').strip()
    if not project:
        return jsonify({'error': 'project description required'}), 400

    context = []
    results = []
    for agent_name in SCRUM_PIPELINE:
        url = _agent_url(agent_name)
        print(f"[sprint] calling {agent_name} ({url})")
        try:
            r = requests.post(url, json={'project': project, 'context': context}, timeout=120)
            body = r.json()
            output = body.get('output', '')
            role = body.get('role', agent_name)
            context.append({'by': role, 'output': output})
            results.append({'agent': agent_name, 'status_code': r.status_code, 'output': output})
        except Exception as e:
            results.append({'agent': agent_name, 'error': str(e)})

    return jsonify({'sprint_results': results, 'final_context': context})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
