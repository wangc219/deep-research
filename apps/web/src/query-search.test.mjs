import test from 'node:test';
import assert from 'node:assert/strict';

import {normalizeQuerySearchText, searchQueryItems} from './query-search.js';

const queries = [
  {
    query_id: 'satellite',
    query: '卫星受扰条件下跨域自主远程精确火力研究',
    supplemental_information: '面向链路中断场景研究装备自主遂行任务能力。',
    generation_rationale: '聚焦远程精确火力。',
  },
  {
    query_id: 'search-strike',
    query: '搜索—识别—跟踪—打击一体化精打武器研究',
    supplemental_information: '缩短任务链。',
  },
  {
    query_id: 'unrelated',
    query: '高机动目标持续跟踪精确打击研究',
    supplemental_information: '状态预测与火力更新。',
  },
];

test('normalizes full-width characters, punctuation and repeated spaces', () => {
  assert.equal(normalizeQuerySearchText(' 搜索—识别， ＡＩ  '), '搜索 识别 ai');
});

test('matches separated Chinese keywords across one query', () => {
  assert.deepEqual(
    searchQueryItems(queries, '卫星 自主 精确').map(item => item.query_id),
    ['satellite'],
  );
});

test('ignores punctuation differences in a continuous phrase', () => {
  assert.equal(searchQueryItems(queries, '搜索识别跟踪打击')[0].query_id, 'search-strike');
});

test('matches keywords across title and supplemental information', () => {
  assert.deepEqual(
    searchQueryItems(queries, '卫星 链路中断').map(item => item.query_id),
    ['satellite'],
  );
});

test('requires every entered keyword to match', () => {
  assert.deepEqual(searchQueryItems(queries, '卫星 潜艇'), []);
});
