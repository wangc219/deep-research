import test from 'node:test';
import assert from 'node:assert/strict';

import {
  forgetDeepLaunchContexts,
  publishDeepLaunchCard,
  readDeepLaunchCard,
  recallDeepLaunchContext,
  rememberDeepLaunchContext,
} from './deep-launch-context.js';

const memoryStorage = () => {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
};

test('deep-research launch context and handoff card are isolated by signed-in user', () => {
  const previousStorage = globalThis.sessionStorage;
  const previousUser = globalThis.__EQUIPMENT_USER_ID__;
  globalThis.sessionStorage = memoryStorage();
  try {
    globalThis.__EQUIPMENT_USER_ID__ = 'user-a';
    rememberDeepLaunchContext({card_binding_id: 'card-1', title: 'A 私有上下文'});
    publishDeepLaunchCard({card_key: 'card-1', name: 'A 私有卡片'});

    globalThis.__EQUIPMENT_USER_ID__ = 'user-b';
    assert.equal(recallDeepLaunchContext({card_binding_id: 'card-1'}), null);
    assert.equal(readDeepLaunchCard('card-1'), null);

    rememberDeepLaunchContext({card_binding_id: 'card-1', title: 'B 私有上下文'});
    publishDeepLaunchCard({card_key: 'card-1', name: 'B 私有卡片'});
    assert.equal(recallDeepLaunchContext({card_binding_id: 'card-1'}).title, 'B 私有上下文');
    assert.equal(readDeepLaunchCard('card-1').name, 'B 私有卡片');

    globalThis.__EQUIPMENT_USER_ID__ = 'user-a';
    assert.equal(recallDeepLaunchContext({card_binding_id: 'card-1'}).title, 'A 私有上下文');
    assert.equal(readDeepLaunchCard('card-1').name, 'A 私有卡片');
    forgetDeepLaunchContexts();
    assert.equal(recallDeepLaunchContext({card_binding_id: 'card-1'}), null);

    globalThis.__EQUIPMENT_USER_ID__ = 'user-b';
    assert.equal(recallDeepLaunchContext({card_binding_id: 'card-1'}).title, 'B 私有上下文');
  } finally {
    globalThis.sessionStorage = previousStorage;
    globalThis.__EQUIPMENT_USER_ID__ = previousUser;
  }
});
