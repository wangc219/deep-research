const text = value => String(value ?? '').trim();
const rows = value => (Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : []);
const strings = (value, limit = 32) => (
  Array.isArray(value) ? [...new Set(value.map(text).filter(Boolean))].slice(0, limit) : []
);

export function normalizeDeepCapabilityCatalog(payload) {
  const source = payload?.catalog && typeof payload.catalog === 'object' ? payload.catalog : (payload || {});
  const skills = rows(source.skills).map(skill => ({
    ...skill,
    skill_id: text(skill.skill_id || skill.id),
    description: text(skill.description),
    source: text(skill.source) || 'builtin',
    plugin_id: text(skill.plugin_id),
    triggers: strings(skill.triggers),
    allowed_tools: strings(skill.allowed_tools),
    steps: strings(skill.steps, 16),
    required_artifacts: strings(skill.required_artifacts, 16),
    quality_gates: strings(skill.quality_gates, 16),
    stop_conditions: strings(skill.stop_conditions, 12),
    recommended: Boolean(skill.recommended),
  })).filter(skill => skill.skill_id);
  const plugins = rows(source.plugins).map(plugin => ({
    ...plugin,
    plugin_id: text(plugin.plugin_id || plugin.id),
    display_name: text(plugin.display_name || plugin.name || plugin.plugin_id),
    description: text(plugin.description),
    category: text(plugin.category),
    permissions: strings(plugin.permissions, 16),
    skill_ids: strings(plugin.skill_ids),
    mcp_servers: rows(plugin.mcp_servers).map(server => ({
      server_id: text(server.server_id || server.id),
      transport: text(server.transport),
      plugin_id: text(server.plugin_id || plugin.plugin_id),
      execution_status: text(server.execution_status),
    })).filter(server => server.server_id),
    enabled: Boolean(plugin.enabled),
  })).filter(plugin => plugin.plugin_id);
  const mcpServers = rows(source.mcp_servers).map(server => ({
    server_id: text(server.server_id || server.id),
    transport: text(server.transport),
    plugin_id: text(server.plugin_id),
    execution_status: text(server.execution_status),
  })).filter(server => server.server_id);
  const hostSource = source.mcp_host && typeof source.mcp_host === 'object' ? source.mcp_host : {};
  const mcpHost = {
    status: text(hostSource.status) || 'not_configured',
    reload: text(hostSource.reload),
    generation: text(hostSource.generation),
    servers: rows(hostSource.servers).map(server => ({
      server_id: text(server.server_id || server.id),
      transport: text(server.transport),
      allowed_tools: strings(server.allowed_tools, 64),
      execution_status: text(server.execution_status) || 'host_configured',
      source: 'deployment_host',
    })).filter(server => server.server_id),
  };
  const maxActiveSkills = Math.max(1, Number(source.limits?.max_active_skills) || 6);
  const modelProfileSource = source.model_profiles && typeof source.model_profiles === 'object'
    ? source.model_profiles
    : {};
  const modelProfiles = rows(modelProfileSource.profiles).map(profile => ({
    id: text(profile.id),
    label: text(profile.label || profile.id),
    provider: text(profile.provider),
    protocol: text(profile.protocol),
    model: text(profile.model),
    endpoint_host: text(profile.endpoint_host),
    credential_configured: Boolean(profile.credential_configured),
    deprecated: Boolean(profile.deprecated),
  })).filter(profile => profile.id && !profile.deprecated);
  return {
    schema_version: text(source.schema_version) || 'deep-capabilities-v1',
    skills,
    plugins,
    mcp_servers: mcpServers,
    mcp_host: mcpHost,
    model_profiles: {
      default_profile: text(modelProfileSource.default_profile),
      active_profile: text(modelProfileSource.active_profile),
      profiles: modelProfiles,
    },
    limits: {max_active_skills: maxActiveSkills},
  };
}

export function reconcileActiveSkillIds(selected, catalog) {
  const allowed = new Set(rows(catalog?.skills).map(skill => text(skill.skill_id)).filter(Boolean));
  const limit = Math.max(1, Number(catalog?.limits?.max_active_skills) || 6);
  return strings(selected).filter(skillId => allowed.has(skillId)).slice(0, limit);
}

export function toggleActiveSkillId(selected, skillId, enabled, catalog) {
  const id = text(skillId);
  const current = reconcileActiveSkillIds(selected, catalog);
  if (!id) return {selected: current, limited: false};
  if (!enabled) return {selected: current.filter(item => item !== id), limited: false};
  const allowed = new Set(rows(catalog?.skills).map(skill => text(skill.skill_id)).filter(Boolean));
  if (!allowed.has(id) || current.includes(id)) return {selected: current, limited: false};
  const limit = Math.max(1, Number(catalog?.limits?.max_active_skills) || 6);
  if (current.length >= limit) return {selected: current, limited: true};
  return {selected: [...current, id], limited: false};
}

export function normalizeDeepWorkspaceResources(payload) {
  const source = payload && typeof payload === 'object' ? payload : {};
  const resourceMap = source.resources && typeof source.resources === 'object' ? source.resources : {};
  const normalizeNames = value => (
    Array.isArray(value)
      ? [...new Set(value.map(text).filter(Boolean))].sort()
      : []
  );
  const resources = {
    config: normalizeNames(resourceMap.config),
    skill: normalizeNames(resourceMap.skill || resourceMap.skills),
    plugin: normalizeNames(resourceMap.plugin || resourceMap.plugins),
  };
  return {
    schema_version: text(source.schema_version) || 'deep-workspace-resources-v1',
    workspace: source.workspace && typeof source.workspace === 'object'
      ? {
          workspace_id: text(source.workspace.workspace_id),
          identity_fingerprint: text(source.workspace.identity_fingerprint),
        }
      : {workspace_id: '', identity_fingerprint: ''},
    resources,
    limits: {
      max_resource_bytes: Math.max(1024, Number(source.limits?.max_resource_bytes) || 2 * 1024 * 1024),
      editable_kinds: strings(source.limits?.editable_kinds, 8),
    },
  };
}
