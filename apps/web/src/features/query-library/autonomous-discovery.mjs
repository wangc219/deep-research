export const AUTONOMOUS_DISCOVERY_ANGLES = [
  {id: 'east-seas-first-chain', label: '东海、台海与第一岛链海空态势'},
  {id: 'south-sea-lanes', label: '南海岛礁、海上通道与远海保障态势'},
  {id: 'western-pacific-second-chain', label: '西太平洋第二岛链与远程机动投送态势'},
  {id: 'plateau-border', label: '中印边境、高原山地与极端环境任务态势'},
  {id: 'northeast-asia', label: '朝鲜半岛、东北亚防空反导与预警态势'},
  {id: 'western-border', label: '中亚与西部边境反无人及非传统安全态势'},
  {id: 'low-altitude-swarm', label: '周边低空无人集群与要地防护态势'},
  {id: 'long-range-fire-defense', label: '邻国远程火力、导弹防御与体系对抗态势'},
  {id: 'maritime-blockade', label: '海上封锁、岛链通道与分布式火力态势'},
  {id: 'multi-domain-support', label: '太空、网络与电磁支撑周边联合任务态势'},
];

export const AUTONOMOUS_FOCUS_OPTIONS = ['无人集群', '低空反制', '远程精打', '防空反导', '跨域协同', '保障韧性'];

export const GENERATION_PROFILES = [
  {id: 'efficient', label: '高效', description: '适合快速初筛，减少发散候选与重试'},
  {id: 'balanced', label: '均衡', description: '推荐；兼顾多维覆盖、质量和耗时'},
  {id: 'deep', label: '深度', description: '扩大候选池，适合关键方向论证'},
];

export function selectAutonomousDiscoveryAngle(generations = []) {
  const metrics = AUTONOMOUS_DISCOVERY_ANGLES.map((angle, order) => {
    const appearances = generations
      .map((item, index) => ({item, index}))
      .filter(({item}) => String(item?.topic || '').includes(angle.label));
    return {
      angle,
      order,
      count: appearances.length,
      lastSeen: appearances.length ? appearances[0].index : -1,
    };
  });
  metrics.sort((left, right) => (
    left.count - right.count
    || right.lastSeen - left.lastSeen
    || left.order - right.order
  ));
  return metrics[0].angle;
}

export function resolveAutonomousDiscoveryAngle(angleId, generations = []) {
  if (angleId && angleId !== 'auto') {
    const selected = AUTONOMOUS_DISCOVERY_ANGLES.find(angle => angle.id === angleId);
    if (selected) return selected;
  }
  return selectAutonomousDiscoveryAngle(generations);
}

export function defaultGenerationProfile(mode) {
  return mode === 'autonomous' ? 'efficient' : 'balanced';
}

export function generationProfileLabel(profileId) {
  return GENERATION_PROFILES.find(profile => profile.id === profileId)?.label || '均衡';
}

export function buildGenerationContext({
  mode,
  profileId,
  autonomousAngle,
  autonomousFocuses = [],
  supplement = '',
  expectedAngle = '',
  demandDimension = '',
  technologyDimension = '',
}) {
  if (mode !== 'autonomous') {
    return [
      `生成策略：${generationProfileLabel(profileId)}。`,
      expectedAngle.trim() && `预期角度：${expectedAngle.trim()}`,
      demandDimension.trim() && `需求牵引维度：${demandDimension.trim()}`,
      technologyDimension.trim() && `技术驱动维度：${technologyDimension.trim()}`,
      supplement.trim() && `其他发散偏好：${supplement.trim()}`,
    ].filter(Boolean).join('\n');
  }

  const angle = autonomousAngle || AUTONOMOUS_DISCOVERY_ANGLES[0];
  return [
    '自动态势发散模式。',
    `生成策略：${generationProfileLabel(profileId)}。`,
    '研究主体：中国；必须从中国面临的安全态势、未来作战任务和装备发展需要反推需求。',
    '国外动态仅作威胁、约束、对手行动与技术基线，不生成国外自身装备需求。',
    `本次轮换视角：${angle.label}。`,
    `重点方向：${autonomousFocuses.length ? autonomousFocuses.join('、') : '由智能体依据态势自主判断'}。`,
    supplement.trim()
      ? `用户补充偏好：${supplement.trim()}`
      : '优先检索该视角下最新、权威的公开态势信号。',
    '因果链：外部态势→任务压力→作战缺口→武器装备能力与发展需求。',
    '发散框架：同时覆盖需求牵引、技术驱动、体系实战、颠覆逻辑与规模建设。',
  ].join('\n');
}

export function autonomousDiscoveryTopic(angle) {
  return `${angle.label}：武器装备能力与发展需求研判`;
}
