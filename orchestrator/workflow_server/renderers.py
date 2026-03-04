import os
import json
from datetime import datetime, timezone

class Renderers:
    def __init__(self, storage):
        self.storage = storage
        self.base = os.path.dirname(__file__)
        self.resources_dir = os.path.join(self.base, 'resources')
        os.makedirs(self.resources_dir, exist_ok=True)

    def render_spec(self, answers):
        spec_path = os.path.join(self.resources_dir, 'spec_current.md')
        lines = ["# Project Specification", "", f"Generated: {datetime.now(timezone.utc).isoformat()}", ""]
        for qid, text, answer in answers:
            lines.append(f"## {qid} - {text}")
            lines.append(answer or "_UNANSWERED_")
            lines.append("")
        with open(spec_path, 'w') as f:
            f.write('\n'.join(lines))
        return spec_path

    def write_adr_stub(self, title, adr_id='adr-0001'):
        adr_dir = os.path.join(self.resources_dir, 'decisions')
        os.makedirs(adr_dir, exist_ok=True)
        adr_path = os.path.join(adr_dir, f"{adr_id}.md")
        content = f"# {adr_id}: {title}\n\nStatus: Proposed\n\nContext:\n\nDecision:\n\nConsequences:\n"
        with open(adr_path, 'w') as f:
            f.write(content)
        return adr_path

    def write_plan(self, tasks):
        plan_dir = os.path.join(self.resources_dir, 'plan')
        os.makedirs(plan_dir, exist_ok=True)
        plan_path = os.path.join(plan_dir, 'workbreakdown.yaml')
        lines = ["tasks:"]
        for task in tasks:
            # support both (id, title) tuples and (id, title, description, acceptance_criteria) tuples
            tid, title = task[0], task[1]
            description = task[2] if len(task) > 2 else ''
            acceptance_criteria = task[3] if len(task) > 3 else ''
            lines.append(f"  - id: {tid}")
            lines.append(f"    title: '{title}'")
            if description:
                lines.append(f"    description: '{description}'")
            if acceptance_criteria:
                lines.append(f"    acceptance_criteria: |")
                for ac_line in acceptance_criteria.splitlines():
                    lines.append(f"      {ac_line}")
            lines.append(f"    done: false")
        with open(plan_path, 'w') as f:
            f.write('\n'.join(lines))
        return plan_path
