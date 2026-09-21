export const S6_COLUMNS = [
  ['overview', '概述'],
  ['technology_implementation', '装备与技术实现'],
  ['operational_process', '关键作战流程'],
  ['capability_effects', '能力与作战效果'],
  ['winning_logic', '制胜逻辑机理'],
];

export function s6PortraitCompleteness(modules = []) {
  const labels = new Set(
    (Array.isArray(modules) ? modules : [])
      .map(item => String(item?.label || '').trim())
      .filter(Boolean),
  );
  const missing = S6_COLUMNS
    .filter(([, label]) => !labels.has(label))
    .map(([, label]) => label);
  const total = S6_COLUMNS.length;
  const completed = total - missing.length;
  return {completed, total, missing, complete: completed === total};
}

// Identity, not arrival order or a global progress counter, lights a column.
export function projectS6Columns(events = [], {sending = false} = {}) {
  const rows = S6_COLUMNS.map(([key, label]) => ({
    key, label, status: sending ? 'running' : 'pending', text: '', preview: '',
  }));
  for (const event of events) {
    const delta = event?.delta || event || {};
    const roleIndex = /第\s*(\d+)\s*栏/.exec(delta.role || event?.role || '');
    const key = delta.column_key || event?.column_key
      || (roleIndex ? S6_COLUMNS[Number(roleIndex[1]) - 1]?.[0] : '');
    const row = rows.find(item => item.key === key);
    if (!row) continue;
    const kind = delta.kind || event?.kind;
    const status = event?.status || delta.status;
    const columnContent = String(delta.column_content || '').trim();
    if (kind === 'answer' && columnContent) {
      row.status = 'completed';
      row.text = columnContent;
      row.preview = columnContent;
    } else if (row.status !== 'completed') {
      row.status = ['partial', 'failed', 'error', 'blocked'].includes(status)
        ? 'failed' : sending ? 'running' : 'pending';
    }
  }
  return rows;
}
