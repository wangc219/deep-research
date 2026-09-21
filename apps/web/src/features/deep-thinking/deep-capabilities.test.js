import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizeDeepCapabilityCatalog,
  normalizeDeepWorkspaceResources,
  reconcileActiveSkillIds,
  toggleActiveSkillId,
} from './deep-capabilities.js';

test('capability catalog normalizes plugin, skill and declaration-only MCP rows', () => {
  const catalog = normalizeDeepCapabilityCatalog({catalog: {
    limits: {max_active_skills: 2},
    skills: [{skill_id: 'review', steps: ['检查证据'], quality_gates: ['可追溯']}],
    plugins: [{plugin_id: 'intel', enabled: true, mcp_servers: [{server_id: 'intel:web', transport: 'stdio', execution_status: 'declaration_only'}]}],
    mcp_servers: [{server_id: 'intel:web', transport: 'stdio', plugin_id: 'intel', execution_status: 'declaration_only'}],
    mcp_host: {status: 'configured', reload: 'per_turn', generation: 'abc123', servers: [{server_id: 'host:search', transport: 'http', allowed_tools: ['search']}]},
  }});
  assert.equal(catalog.limits.max_active_skills, 2);
  assert.equal(catalog.skills[0].skill_id, 'review');
  assert.equal(catalog.plugins[0].mcp_servers[0].server_id, 'intel:web');
  assert.equal(catalog.plugins[0].mcp_servers[0].execution_status, 'declaration_only');
  assert.equal(catalog.mcp_servers[0].transport, 'stdio');
  assert.equal(catalog.mcp_servers[0].execution_status, 'declaration_only');
  assert.equal(catalog.mcp_host.status, 'configured');
  assert.equal(catalog.mcp_host.reload, 'per_turn');
  assert.deepEqual(catalog.mcp_host.servers[0], {
    server_id: 'host:search',
    transport: 'http',
    allowed_tools: ['search'],
    execution_status: 'host_configured',
    source: 'deployment_host',
  });
});

test('active skills are bounded and removed when no longer available', () => {
  const catalog = normalizeDeepCapabilityCatalog({
    limits: {max_active_skills: 2},
    skills: [{skill_id: 'a'}, {skill_id: 'b'}, {skill_id: 'c'}],
  });
  assert.deepEqual(reconcileActiveSkillIds(['missing', 'a', 'b', 'c'], catalog), ['a', 'b']);
  assert.deepEqual(toggleActiveSkillId(['a'], 'b', true, catalog), {selected: ['a', 'b'], limited: false});
  assert.deepEqual(toggleActiveSkillId(['a', 'b'], 'c', true, catalog), {selected: ['a', 'b'], limited: true});
  assert.deepEqual(toggleActiveSkillId(['a', 'b'], 'a', false, catalog), {selected: ['b'], limited: false});
});

test('workspace resources normalize editable config skill and plugin files', () => {
  const catalog = normalizeDeepWorkspaceResources({
    workspace: {workspace_id: 'run:1:equipment:abc', identity_fingerprint: 'abc'},
    resources: {
      config: ['runtime.json'],
      skill: ['frontier/SKILL.md', 'frontier/SKILL.md'],
      plugin: ['methods/plugin.json'],
    },
    limits: {max_resource_bytes: 4096, editable_kinds: ['config', 'skill', 'plugin']},
  });
  assert.equal(catalog.workspace.identity_fingerprint, 'abc');
  assert.deepEqual(catalog.resources.config, ['runtime.json']);
  assert.deepEqual(catalog.resources.skill, ['frontier/SKILL.md']);
  assert.deepEqual(catalog.resources.plugin, ['methods/plugin.json']);
  assert.equal(catalog.limits.max_resource_bytes, 4096);
});

test('deep model profiles expose ready GPT DeepSeek and Queen presets', () => {
  const catalog = normalizeDeepCapabilityCatalog({
    model_profiles: {
      default_profile: 'codex-gpt',
      active_profile: 'codex-deepseek',
      profiles: [
        {id: 'codex-gpt', label: 'GPT', model: 'gpt-5.5', credential_configured: true},
        {id: 'codex-deepseek', label: 'DeepSeek', model: 'deepseek-chat', credential_configured: true},
        {id: 'codex-queen', label: 'Queen', model: 'qwen3.8-flash', credential_configured: true},
        {id: 'old', label: 'Old', deprecated: true},
      ],
    },
  });

  assert.equal(catalog.model_profiles.default_profile, 'codex-gpt');
  assert.equal(catalog.model_profiles.active_profile, 'codex-deepseek');
  assert.deepEqual(catalog.model_profiles.profiles.map(item => item.id), [
    'codex-gpt',
    'codex-deepseek',
    'codex-queen',
  ]);
});
