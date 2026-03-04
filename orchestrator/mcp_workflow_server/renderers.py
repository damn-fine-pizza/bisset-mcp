import os
import json
from datetime import datetime

class Renderers:
    def __init__(self, storage):
        self.storage = storage
        self.base = os.path.dirname(__file__)
        self.resources_dir = os.path.join(self.base, 'resources')
        os.makedirs(self.resources_dir, exist_ok=True)

    def render_spec(self, answers):
        spec_path = os.path.join(self.resources_dir, 'spec_current.md')
        lines = ["# Project Specification", "", f"Generated: {datetime.utcnow().isoformat()}Z", ""]
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
        for tid, title in tasks:
            lines.append(f"  - id: {tid}")
            lines.append(f"    title: '{title}'")
            lines.append(f"    done: false")
        with open(plan_path, 'w') as f:
            f.write('\n'.join(lines))
        return plan_path
