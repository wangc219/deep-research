import test from 'node:test';
import assert from 'node:assert/strict';
import {projectS6Columns, s6PortraitCompleteness} from './s6-progress.js';

test('portrait completeness requires all five named columns', () => {
  const incomplete = s6PortraitCompleteness([
    {label: '概述', text: 'one'},
    {label: '关键作战流程', text: 'three'},
    {label: '能力与作战效果', text: 'four'},
    {label: '制胜逻辑机理', text: 'five'},
  ]);
  assert.deepEqual(incomplete, {
    completed: 4,
    total: 5,
    missing: ['装备与技术实现'],
    complete: false,
  });

  assert.equal(s6PortraitCompleteness([
    {label: '概述'},
    {label: '装备与技术实现'},
    {label: '关键作战流程'},
    {label: '能力与作战效果'},
    {label: '制胜逻辑机理'},
  ]).complete, true);
});

test('fifth column arriving first only lights its own fixed slot', () => {
  const rows = projectS6Columns([
    {delta: {kind: 'answer', role: '其他阶段', completed_count: 5}},
    {delta: {kind: 'answer', column_key: 'winning_logic', column_content: 'Section five', completed_count: 1}},
  ], {sending: true});
  assert.deepEqual(rows.map(row => row.status), ['running', 'running', 'running', 'running', 'completed']);
  assert.equal(rows[4].text, 'Section five');
});

test('replayed events do not duplicate completion or erase completed text', () => {
  const answer = {delta: {kind: 'answer', column_key: 'overview', column_content: 'Section one'}};
  const rows = projectS6Columns([answer, answer, {status: 'partial', delta: {column_key: 'overview'}}]);
  assert.equal(rows.filter(row => row.status === 'completed').length, 1);
  assert.equal(rows[0].text, 'Section one');
});

test('a failed column and a completed column remain distinct after termination', () => {
  const rows = projectS6Columns([
    {status: 'partial', delta: {column_key: 'technology_implementation'}},
    {delta: {kind: 'answer', role: 'S6 第3栏主笔', column_content: 'Section three'}},
  ]);
  assert.equal(rows[1].status, 'failed');
  assert.equal(rows[2].status, 'completed');
  assert.equal(rows[0].status, 'pending');
});

test('ordinary answer text cannot mark an unfinished column as completed', () => {
  const rows = projectS6Columns([
    {
      delta: {
        kind: 'answer',
        column_key: 'technology_implementation',
        text: '装备与技术实现正在生成中',
      },
    },
  ]);
  assert.equal(rows[1].status, 'pending');
  assert.equal(rows[1].text, '');
});
