# 消融实验报告：ablation-20260729-124053

## 1. 实验配置

- 数据集：`tactical-strike-frontiers-50-v1`
- Query 数量：2
- 控制组来源：existing
- 运行模式：real
- 结论级别：探索性

| 实验组 | 基线 | 制胜机理 | L1-L4 |
|---|---|---|---|
| 完整方法 | 多角色、多通道 | S1-S6 | 启用 |
| 去多源基线 | 单通用 Agent、单通道 | 单次 S1-S6 | 关闭 |
| 去制胜机理 | 完整多源基线 | 跳过 | 关闭 |

## 2. 有效性检查

- 去多源基线：通过
- 去制胜机理：通过

## 3. Judge 结果

### 完整方法 vs 去多源基线

- 完整方法：1胜 / 0平 / 1负，得分率 50.0%
- 消融方法：1胜 / 0平 / 1负，得分率 50.0%
- 配对得分差：0.0%
- 配对 Bootstrap 95% 区间：[-1.0, 1.0]
- 结论：**当前数据不支持**

| 维度 | 完整方法 | 平 | 消融组 |
|---|---:|---:|---:|
| capability_mapping_and_demand_quality | 6 | 0 | 2 |
| causal_and_mechanism_depth | 4 | 0 | 4 |
| evidence_and_factuality | 0 | 0 | 8 |
| military_operational_value | 4 | 1 | 3 |
| novelty_and_foresight | 4 | 0 | 4 |
| route_task_fulfillment | 4 | 0 | 4 |
| system_and_cross_scenario_robustness | 4 | 0 | 4 |
| uncertainty_and_validation | 0 | 0 | 8 |

| 实验组 | 完成率 | 平均耗时(秒) | 平均模型调用量 | 平均估算成本 |
|---|---:|---:|---:|---:|
| 完整方法 | 100.0% | 1622.162 | 0.000 | 0.000000 |
| 去多源基线 | 100.0% | 1046.849 | 0.000 | 0.000000 |

### 完整方法 vs 去制胜机理

- 完整方法：2胜 / 0平 / 0负，得分率 100.0%
- 消融方法：0胜 / 0平 / 2负，得分率 0.0%
- 配对得分差：100.0%
- 配对 Bootstrap 95% 区间：[1.0, 1.0]
- 结论：**设计贡献得到支持**

| 维度 | 完整方法 | 平 | 消融组 |
|---|---:|---:|---:|
| capability_mapping_and_demand_quality | 8 | 0 | 0 |
| causal_and_mechanism_depth | 8 | 0 | 0 |
| evidence_and_factuality | 6 | 0 | 2 |
| military_operational_value | 8 | 0 | 0 |
| novelty_and_foresight | 8 | 0 | 0 |
| route_task_fulfillment | 8 | 0 | 0 |
| system_and_cross_scenario_robustness | 8 | 0 | 0 |
| uncertainty_and_validation | 8 | 0 | 0 |

| 实验组 | 完成率 | 平均耗时(秒) | 平均模型调用量 | 平均估算成本 |
|---|---:|---:|---:|---:|
| 完整方法 | 100.0% | 1622.162 | 0.000 | 0.000000 |
| 去制胜机理 | 100.0% | 747.763 | 0.000 | 0.000000 |

## 4. 解释边界

- 置信区间跨越 0 时，只能报告方向性证据，不能宣称核心设计已被统计证明。
- 绑定历史项目报告且模型、时点或执行配置不完全一致时，本次结果自动降级为探索性。
- 任一消融运行出现被禁止的 L1-L4、Recall 或被移除阶段事件时，该比较不进入有效结论。
