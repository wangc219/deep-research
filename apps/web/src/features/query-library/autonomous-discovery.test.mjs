import test from 'node:test';
import assert from 'node:assert/strict';

import {
  AUTONOMOUS_DISCOVERY_ANGLES,
  autonomousDiscoveryTopic,
  buildGenerationContext,
  defaultGenerationProfile,
  resolveAutonomousDiscoveryAngle,
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

test('autonomous mode defaults to the efficient generation profile', () => {
  assert.equal(defaultGenerationProfile('autonomous'), 'efficient');
  assert.equal(defaultGenerationProfile('guided'), 'balanced');
});

test('manual situation angle takes priority over smart rotation', () => {
  const manual = AUTONOMOUS_DISCOVERY_ANGLES[3];
  const generations = [{topic: autonomousDiscoveryTopic(manual)}];

  assert.equal(resolveAutonomousDiscoveryAngle(manual.id, generations), manual);
  assert.notEqual(resolveAutonomousDiscoveryAngle('auto', generations), manual);
});

test('autonomous context carries China subject, focus and efficient markers', () => {
  const context = buildGenerationContext({
    mode: 'autonomous',
    profileId: 'efficient',
    autonomousAngle: AUTONOMOUS_DISCOVERY_ANGLES[0],
    autonomousFocuses: ['低空反制', '保障韧性'],
    supplement: '关注未来三至五年',
  });

  assert.match(context, /生成策略：高效/);
  assert.match(context, /研究主体：中国/);
  assert.match(context, /国外动态仅作威胁、约束、对手行动与技术基线/);
  assert.match(context, /重点方向：低空反制、保障韧性/);
  assert.match(context, /未来三至五年/);
});
