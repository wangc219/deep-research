import assert from 'node:assert/strict';
import test from 'node:test';

import {isGlobalBusinessRole} from './platform-role.js';

test('admin and superadmin share global business presentation semantics', () => {
  assert.equal(isGlobalBusinessRole('admin'), true);
  assert.equal(isGlobalBusinessRole('superadmin'), true);
  assert.equal(isGlobalBusinessRole('user'), false);
});
