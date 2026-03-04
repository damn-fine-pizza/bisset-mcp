#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import express from 'express';
import fs from 'fs/promises';
import path from 'path';

const ORCHESTRATOR_URL = process.env.ORCHESTRATOR_URL ?? 'http://localhost:8080';
const PROMPT_API_PORT = Number(process.env.MCP_PROMPT_PORT || 3000);

const server = new McpServer({
  name: 'bisset-mcp',
  version: '1.0.0',
});

// in-memory sprint context (visible to Copilot CLI via get_context)
let sprintContext = [];

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

const transport = new StdioServerTransport();
await server.connect(transport);
