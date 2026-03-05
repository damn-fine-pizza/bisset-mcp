import os
import json
from datetime import datetime, timezone

class Renderers:
    def __init__(self, storage):
        self.storage = storage
        self.base = os.path.dirname(__file__)
        # Do not write files to disk; persist generated artifacts in the session-scoped DB via storage
        self.resources_dir = os.path.join(self.base, 'resources')

    def render_spec(self, answers):
        lines = ["# Project Specification", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", ""]
        for qid, text, answer in answers:
            lines.append(f"## {qid} - {text}")
            lines.append(answer or "_UNANSWERED_")
            lines.append("")
        content = '\n'.join(lines)
        # Persist spec content in session-scoped meta to avoid filesystem writes
        self.storage.write_meta('spec_current', {'content': content, 'generated_at': datetime.now(timezone.utc).isoformat()})
        return 'db:spec_current'

    def write_adr_stub(self, title, adr_id='adr-0001'):
        content = f"# {adr_id}: {title}\n\nStatus: Proposed\n\nContext:\n\nDecision:\n\nConsequences:\n"
        # Persist ADR stub in DB
        self.storage.write_meta(f'adr:{adr_id}', {'content': content, 'created_at': datetime.now(timezone.utc).isoformat()})
        return f'db:adr:{adr_id}'

    def write_plan(self, tasks):
        tasks_list = []
        for task in tasks:
            tid, title = task[0], task[1]
            description = task[2] if len(task) > 2 else ''
            acceptance_criteria = task[3] if len(task) > 3 else ''
            tasks_list.append({'id': tid, 'title': title, 'description': description, 'acceptance_criteria': acceptance_criteria, 'done': False})
        payload = {'tasks': tasks_list, 'generated_at': datetime.now(timezone.utc).isoformat()}
        # Persist work breakdown in DB
        self.storage.write_meta('plan_workbreakdown', payload)
        return 'db:plan_workbreakdown'
