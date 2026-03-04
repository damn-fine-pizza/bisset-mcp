from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

SCRUM_PIPELINE = [
    'senior-product-manager',
    'product-owner',
    'ux-designer-senior',
    'senior-database-engineer',
    'sw-architect',
    'senior-developer',
    'senior-frontend-developer',
]

def _agent_url(agent):
    key = f"AGENT_{agent.upper().replace('-', '_')}_URL"
    return os.environ.get(key, f"http://agent-{agent}:8000/webhook")

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
    app.run(host='0.0.0.0', port=8080)
