const validTimestamp = value => {
  const timestamp = Date.parse(String(value || '').trim());
  return Number.isFinite(timestamp) && timestamp > 0 ? timestamp : 0;
};

export function resolveDeepThinkingStartedAt(activeJob = null, events = []) {
  const jobTimestamp = validTimestamp(activeJob?.created_at);
  if (jobTimestamp) return jobTimestamp;

  const jobId = String(activeJob?.job_id || activeJob?.id || '').trim();
  const timestamps = events
    .filter(event => {
      if (!jobId) return true;
      const eventJobId = String(event?.job_id || '').trim();
      return !eventJobId || eventJobId === jobId;
    })
    .map(event => validTimestamp(event?.created_at))
    .filter(Boolean);
  return timestamps.length ? Math.min(...timestamps) : 0;
}

export function deepThinkingElapsedSeconds(startedAt, now = Date.now()) {
  const start = Number(startedAt) || 0;
  const current = Number(now) || 0;
  if (!start || current <= start) return 0;
  return Math.floor((current - start) / 1000);
}
