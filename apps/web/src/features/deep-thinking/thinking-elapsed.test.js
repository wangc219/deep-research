import test from 'node:test';
import assert from 'node:assert/strict';
import {deepThinkingElapsedSeconds, resolveDeepThinkingStartedAt} from './thinking-elapsed.js';

test('server job creation time survives a refresh or conversation switch', () => {
  const startedAt = resolveDeepThinkingStartedAt(
    {job_id: 'job-1', created_at: '2026-09-20T08:00:00.000Z'},
    [{job_id: 'job-1', created_at: '2026-09-20T08:00:04.000Z'}],
  );
  assert.equal(startedAt, Date.parse('2026-09-20T08:00:00.000Z'));
  assert.equal(deepThinkingElapsedSeconds(startedAt, Date.parse('2026-09-20T08:00:15.900Z')), 15);
});

test('the earliest current-job event is a durable fallback for legacy jobs', () => {
  const startedAt = resolveDeepThinkingStartedAt(
    {job_id: 'job-2'},
    [
      {job_id: 'other-job', created_at: '2026-09-20T07:30:00.000Z'},
      {job_id: 'job-2', created_at: '2026-09-20T08:00:05.000Z'},
      {job_id: 'job-2', created_at: '2026-09-20T08:00:02.000Z'},
    ],
  );
  assert.equal(startedAt, Date.parse('2026-09-20T08:00:02.000Z'));
});
