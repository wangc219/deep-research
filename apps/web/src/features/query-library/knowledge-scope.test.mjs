import test from 'node:test';
import assert from 'node:assert/strict';

import {
  accessibleKnowledgeUrl,
  createKnowledgeScope,
  inheritKnowledgeScope,
  knowledgeScopeSummary,
  normalizeAccessibleKnowledgeBases,
  normalizeKnowledgeIds,
} from './knowledge-scope.mjs';

test('knowledge ids are stable, trimmed and deduplicated', () => {
  assert.deepEqual(normalizeKnowledgeIds([' kb-a ', '', 'kb-a', null, 'kb-b']), ['kb-a', 'kb-b']);
});

test('new Query scope distinguishes default visibility, restriction and disabled capability', () => {
  assert.deepEqual(createKnowledgeScope(), {
    knowledge_enabled: true,
    knowledge_ids: null,
  });
  assert.deepEqual(createKnowledgeScope({selectedIds: [' kb-b ', 'kb-a', 'kb-b']}), {
    knowledge_enabled: true,
    knowledge_ids: ['kb-b', 'kb-a'],
  });
  assert.deepEqual(createKnowledgeScope({enabled: false, selectedIds: ['kb-a']}), {
    knowledge_enabled: false,
    knowledge_ids: [],
  });
});

test('research Run inherits persisted Query scope without widening it', () => {
  assert.deepEqual(inheritKnowledgeScope({}), {
    knowledge_enabled: true,
    knowledge_ids: null,
  });
  assert.deepEqual(inheritKnowledgeScope({knowledge_ids: ['kb-a', ' kb-a ', 'kb-b']}), {
    knowledge_enabled: true,
    knowledge_ids: ['kb-a', 'kb-b'],
  });
  assert.deepEqual(inheritKnowledgeScope({knowledge_enabled: false, knowledge_ids: ['kb-a']}), {
    knowledge_enabled: false,
    knowledge_ids: [],
  });
  assert.deepEqual(inheritKnowledgeScope({knowledge_enabled: true, knowledge_ids: []}), {
    knowledge_enabled: true,
    knowledge_ids: [],
  });
  assert.deepEqual(inheritKnowledgeScope(null), {});
});

test('accessible knowledge response keeps only safe stable metadata', () => {
  assert.deepEqual(normalizeAccessibleKnowledgeBases({databases: [
    {kb_id: ' kb-a ', name: 'A', description: 'desc', secret: 'discard'},
    {kb_id: 'kb-a', name: 'duplicate'},
    {kb_id: 'kb-b', name: '', supports_documents: false},
    {name: 'missing id'},
  ]}), [
    {kb_id: 'kb-a', name: 'A', description: 'desc', supports_documents: true},
    {kb_id: 'kb-b', name: '未命名知识库', description: '', supports_documents: false},
  ]);
});

test('knowledge endpoint follows the configured API origin without using the legacy v1 prefix', () => {
  assert.equal(
    accessibleKnowledgeUrl('/api/v1', 'https://work.example/equipment/runs'),
    'https://work.example/api/knowledge/databases/accessible',
  );
  assert.equal(
    accessibleKnowledgeUrl('https://api.example/platform/api/v1/'),
    'https://api.example/platform/api/knowledge/databases/accessible',
  );
});

test('scope summaries expose only capability state and counts', () => {
  assert.equal(knowledgeScopeSummary({knowledge_ids: null}), '全部可见知识库按需可用');
  assert.equal(knowledgeScopeSummary({knowledge_ids: ['kb-secret-a', 'kb-secret-b']}), '2 个知识库按需可用');
  assert.equal(knowledgeScopeSummary({knowledge_enabled: false}), '知识库能力已关闭');
});
