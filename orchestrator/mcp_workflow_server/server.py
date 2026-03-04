import sys
import json
import logging
from .engine import WorkflowEngine
from .storage import Storage
from .catalog import Catalog
from .renderers import Renderers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('mcp-server')

DB_PATH = 'orchestrator/mcp_workflow_server/workflow.db'

engine = None

METHODS = {}

def init_engine():
    global engine
    if engine is None:
        storage = Storage(DB_PATH)
        catalog = Catalog()
        renderers = Renderers(storage)
        engine = WorkflowEngine(storage, catalog, renderers)

def handle_request(req):
    try:
        method = req.get('method')
        params = req.get('params', {})
        if method not in METHODS:
            return {'error': f'unknown method {method}'}
        init_engine()
        result = METHODS[method](**params)
        return {'result': result}
    except Exception as e:
        logger.exception('request failed')
        return {'error': str(e)}

# Register methods

def register(name, fn):
    METHODS[name] = fn

# map engine methods after lazy init

def _map_methods():
    register('workflow.start', lambda project_meta={}: engine.start(project_meta))
    register('workflow.get_state', lambda: engine.get_state())
    register('workflow.next_question', lambda: engine.next_question())
    register('workflow.record_answer', lambda question_id, answer_text: engine.record_answer(question_id, answer_text))
    register('workflow.freeze_spec', lambda: engine.freeze_spec())
    register('workflow.next_task', lambda: engine.next_task())
    register('workflow.accept_task_result', lambda task_id, summary, artifacts_changed=None, tests_run=None, test_results=None: engine.accept_task_result(task_id, summary, artifacts_changed or [], tests_run or [], test_results or {}))
    register('workflow.report', lambda: engine.report())
    register('workflow.is_done', lambda: engine.is_done())


def main():
    init_engine()
    _map_methods()
    # simple JSON-RPC over stdin/stdout lines
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            resp = {'error': 'invalid json'}
            print(json.dumps(resp), flush=True)
            continue
        resp = handle_request(req)
        print(json.dumps(resp), flush=True)

