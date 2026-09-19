import test from 'node:test';
import assert from 'node:assert/strict';

import {readDeepThinkingLocation} from './open-deep-thinking.js';

test('deep workspace location restores session, branch and target', () => {
  assert.deepEqual(
    readDeepThinkingLocation('?view=capabilities&deep=1&session=s-1&branch=b-2&target=cap%3A9'),
    {open: true, sessionId: 's-1', branchId: 'b-2', targetIdentity: 'cap:9'},
  );
});

test('deep workspace location defaults to a closed main branch', () => {
  assert.deepEqual(
    readDeepThinkingLocation('?view=reports&deep=0'),
    {open: false, sessionId: '', branchId: 'main', targetIdentity: ''},
  );
});
