#!/usr/bin/env node
/**
 * DEPRECATED — Node MCP server (mcp-server/index.js)
 *
 * The primary MCP server for Bisset is now the Python FastMCP server at:
 *   orchestrator/mcp_server/server.py
 *
 * The Python server exposes all tools, resources, and prompts including
 * the new autonomous orchestration tools:
 *   workflow_run_until_blocked, workflow_status, workflow_bootstrap_project,
 *   workflow_get_events
 *
 * This Node server is kept for backward compatibility only.
 * It will be removed in a future release.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import express from 'express';
import fs from 'fs/promises';
import path from 'path';

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL ?? 'http://localhost:8080';
const WORKFLOW_URL = process.env.WORKFLOW_URL ?? 'http://localhost:8765';
const PROMPT_API_PORT = Number(process.env.MCP_PROMPT_PORT || 3000);

const server = new McpServer({
  name: 'bisset-mcp',
  version: '1.0.0',
});

// in-memory sprint context (visible to Copilot CLI via get_context)
let sprintContext = [];
let currentProjectDir = '';
let lastVerificationHistory = [];

// --- Prompt storage (in-memory with simple audit trail)
const AGENTS = [
  'senior-product-manager',
  'product-owner',
  'ux-designer-senior',
  'senior-database-engineer',
  'sw-architect',
  'senior-developer',
  'senior-frontend-developer',
  'senior-qa-engineer',
];

const promptsStore = {}; // name -> { prompt, meta: {version, author, timestamp}, audit: [] }

async function loadLocalPrompts() {
  // Attempt to import existing templates from orchestrator agents prompts/ folders
  const agentsDir = path.resolve(process.cwd(), '../orchestrator/agents');
  try {
    const agentDirs = await fs.readdir(agentsDir, { withFileTypes: true });
    for (const d of agentDirs) {
      if (!d.isDirectory()) continue;
      const promptsDir = path.join(agentsDir, d.name, 'prompts');
      try {
        const files = await fs.readdir(promptsDir);
        const md = files.find(f => f.toLowerCase().endsWith('.md'));
        if (md) {
          const content = await fs.readFile(path.join(promptsDir, md), 'utf8');
          // normalize agent name (folder is agent-<name>)
          const agentKey = d.name.replace(/^agent-/, '');
          promptsStore[agentKey] = {
            prompt: content,
            meta: { version: 1, author: 'import', timestamp: new Date().toISOString() },
            audit: [{ action: 'import', author: 'import', timestamp: new Date().toISOString() }],
          };
        }
      } catch (e) {
        // ignore missing prompts dir
      }
    }
  } catch (e) {
    // ignore if orchestrator not present
  }
}

// initialize store from local templates (best-effort)
await loadLocalPrompts();

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// --- Expose HTTP API for managing agent prompts
const api = express();
api.use(express.json());

api.get('/agents', (req, res) => {
  return res.json({ agents: AGENTS });
});

api.get('/agents/:name/prompt', (req, res) => {
  const name = req.params.name;
  const entry = promptsStore[name];
  if (!entry) return res.status(404).json({ error: 'prompt not found' });
  return res.json({ name, prompt: entry.prompt, meta: entry.meta });
});

api.put('/agents/:name/prompt', (req, res) => {
  const name = req.params.name;
  const { prompt, author } = req.body || {};
  if (!prompt) return res.status(400).json({ error: 'prompt required' });
  const prev = promptsStore[name];
  const nextVersion = prev ? (prev.meta.version + 1) : 1;
  const meta = { version: nextVersion, author: author || 'unknown', timestamp: new Date().toISOString() };
  promptsStore[name] = { prompt, meta, audit: [ ...(prev?.audit || []), { action: 'put', author: meta.author, timestamp: meta.timestamp } ] };
  return res.json({ name, meta });
});

api.delete('/agents/:name/prompt', (req, res) => {
  const name = req.params.name;
  if (!promptsStore[name]) return res.status(404).json({ error: 'prompt not found' });
  promptsStore[name].audit.push({ action: 'delete', author: req.body?.author || 'unknown', timestamp: new Date().toISOString() });
  delete promptsStore[name];
  return res.json({ ok: true });
});

api.get('/agents/:name/audit', (req, res) => {
  const name = req.params.name;
  const entry = promptsStore[name];
  if (!entry) return res.status(404).json({ error: 'prompt not found' });
  return res.json({ name, audit: entry.audit });
});

api.listen(PROMPT_API_PORT, () => console.log(`[mcp-prompts] listening on :${PROMPT_API_PORT}`));

server.tool(
  'dispatch_agent',
  'Dispatch a task to a specific Scrum agent (sw-architect, product-owner, senior-developer, senior-frontend-developer, senior-database-engineer, senior-qa-engineer, ux-designer-senior, senior-product-manager)',
  {
    agent:   z.string().describe('Agent name, e.g. "sw-architect"'),
    task:    z.record(z.unknown()).describe('Task payload object'),
    context: z.array(z.object({ by: z.string(), output: z.string() })).optional().describe('Accumulated context to pass to the agent'),
  },
  async ({ agent, task, context }) => {
    const data = await postJSON(`${ORCHESTRATOR_URL}/dispatch`, { agent, task, context: context ?? sprintContext });
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'run_sprint',
  'Run the full Scrum multi-agent pipeline for a project description. Calls all 7 agents in sequence and accumulates context.',
  {
    project: z.string().describe('Natural language description of the project to build'),
  },
  async ({ project }) => {
    sprintContext = [];
    const data = await postJSON(`${ORCHESTRATOR_URL}/sprint`, { project });
    sprintContext = data.final_context ?? [];
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'get_context',
  'Get the accumulated context from the last sprint run',
  {},
  async () => {
    return { content: [{ type: 'text', text: JSON.stringify(sprintContext, null, 2) }] };
  },
);

server.tool(
  'reset_context',
  'Reset the accumulated sprint context',
  {},
  async () => {
    sprintContext = [];
    return { content: [{ type: 'text', text: 'Context reset.' }] };
  },
);

// ── Bisset Workflow Session Management ────────────────────────────────────────

async function wf(endpoint, args = {}) {
  return postJSON(`${WORKFLOW_URL}/tools/${endpoint}`, { arguments: args });
}

server.tool(
  'workflow_new_session',
  'Create a new Bisset project session. Returns a session_id you can use to resume later.',
  {
    name: z.string().optional().describe('Human-readable name for this session, e.g. "Calculator app"'),
  },
  async ({ name }) => {
    const data = await wf('workflow_new_session', { name: name ?? '' });
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'workflow_list_sessions',
  'List all Bisset project sessions (id, name, created_at, updated_at). Use workflow_switch_session to resume one.',
  {},
  async () => {
    const data = await wf('workflow_list_sessions');
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'workflow_switch_session',
  'Switch to an existing Bisset session by its session_id. All subsequent workflow calls will use this session.',
  {
    session_id: z.string().describe('The session ID returned by workflow_new_session or workflow_list_sessions'),
  },
  async ({ session_id }) => {
    const data = await wf('workflow_switch_session', { session_id });
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

// ── Sprint + Gherkin loop tools ───────────────────────────────────────────────

server.tool(
  'set_project_dir',
  'Set the local project directory that Bisset will use for writing Gherkin feature files and running coverage checks.',
  {
    path: z.string().describe('Absolute path to the project directory'),
  },
  async ({ path: p }) => {
    currentProjectDir = p;
    return { content: [{ type: 'text', text: `Project dir set to: ${currentProjectDir}` }] };
  },
);

server.tool(
  'run_verification',
  'Run behave + coverage against the current project directory. Returns coverage %, passing/failing scenarios.',
  {},
  async () => {
    if (!currentProjectDir) {
      return { content: [{ type: 'text', text: 'Error: call set_project_dir first.' }] };
    }
    const data = await postJSON(`${ORCHESTRATOR_URL}/run_coverage`, { project_dir: currentProjectDir });
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'sprint_with_loop',
  'Run the full Scrum pipeline for a project, write Gherkin tests, then loop fixing failures until coverage ≥ 80% or max 10 iterations.',
  {
    project:     z.string().describe('Natural language description of the project to build'),
    project_dir: z.string().optional().describe('Absolute path to project directory (uses set_project_dir value if omitted)'),
  },
  async ({ project, project_dir }) => {
    const dir = project_dir || currentProjectDir;
    if (!dir) {
      return { content: [{ type: 'text', text: 'Error: provide project_dir or call set_project_dir first.' }] };
    }
    currentProjectDir = dir;
    const data = await postJSON(`${ORCHESTRATOR_URL}/sprint_with_loop`, { project, project_dir: dir });
    lastVerificationHistory = data.coverage_history ?? [];
    sprintContext = data.final_context ?? [];
    return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
  },
);

server.tool(
  'get_verification_history',
  'Return the coverage history from the last sprint_with_loop run (one entry per iteration).',
  {},
  async () => {
    return { content: [{ type: 'text', text: JSON.stringify(lastVerificationHistory, null, 2) }] };
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);
