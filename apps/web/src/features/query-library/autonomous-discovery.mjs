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

export function autonomousDiscoveryTopic(angle) {
  return `${angle.label}：武器装备能力与发展需求研判`;
}
