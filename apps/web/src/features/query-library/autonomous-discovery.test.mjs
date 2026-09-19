import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTONOMOUS_DISCOVERY_ANGLES,
  autonomousDiscoveryTopic,
  selectAutonomousDiscoveryAngle,
} from './autonomous-discovery.mjs';

test('autonomous discovery rotates to an unused China situation angle', () => {
  const first = selectAutonomousDiscoveryAngle([]);
  const second = selectAutonomousDiscoveryAngle([{topic: autonomousDiscoveryTopic(first)}]);

  assert.equal(first, AUTONOMOUS_DISCOVERY_ANGLES[0]);
  assert.equal(second, AUTONOMOUS_DISCOVERY_ANGLES[1]);
});

test('autonomous discovery reuses the least recent angle after a complete cycle', () => {
  const generations = AUTONOMOUS_DISCOVERY_ANGLES
    .map(angle => ({topic: autonomousDiscoveryTopic(angle)}))
    .reverse();

  assert.equal(selectAutonomousDiscoveryAngle(generations), AUTONOMOUS_DISCOVERY_ANGLES[0]);
});

test('autonomous task title states the equipment-demand objective', () => {
  const topic = autonomousDiscoveryTopic(AUTONOMOUS_DISCOVERY_ANGLES[0]);

  assert.match(topic, /武器装备能力与发展需求/);
});
