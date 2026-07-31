# 消融实验报告：ablation-20260729-142922

## 1. 实验配置

- 数据集：`tactical-strike-frontiers-50-v1`
- Query 数量：8
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

- 完整方法：5胜 / 0平 / 3负，得分率 62.5%
- 消融方法：3胜 / 0平 / 5负，得分率 37.5%
- 配对得分差：25.0%
- 配对 Bootstrap 95% 区间：[-0.5, 0.75]
- 结论：**仅有方向性证据**

| 维度 | 完整方法 | 平 | 消融组 |
|---|---:|---:|---:|
| capability_mapping_and_demand_quality | 21 | 0 | 11 |
| causal_and_mechanism_depth | 20 | 0 | 12 |
| evidence_and_factuality | 19 | 1 | 12 |
| military_operational_value | 22 | 1 | 9 |
| novelty_and_foresight | 22 | 1 | 9 |
| route_task_fulfillment | 22 | 1 | 9 |
| system_and_cross_scenario_robustness | 20 | 0 | 12 |
| uncertainty_and_validation | 16 | 4 | 12 |

| 实验组 | 完成率 | 平均耗时(秒) | 平均模型调用量 | 平均估算成本 |
|---|---:|---:|---:|---:|
| 完整方法 | 100.0% | 1545.133 | 0.000 | 0.000000 |
| 去多源基线 | 100.0% | 1274.267 | 0.000 | 0.000000 |

### 完整方法 vs 去制胜机理

- 完整方法：7胜 / 1平 / 0负，得分率 93.8%
- 消融方法：0胜 / 1平 / 7负，得分率 6.2%
- 配对得分差：87.5%
- 配对 Bootstrap 95% 区间：[0.625, 1.0]
- 结论：**设计贡献得到支持**

| 维度 | 完整方法 | 平 | 消融组 |
|---|---:|---:|---:|
| capability_mapping_and_demand_quality | 30 | 0 | 2 |
| causal_and_mechanism_depth | 27 | 0 | 5 |
| evidence_and_factuality | 19 | 1 | 12 |
| military_operational_value | 31 | 0 | 1 |
| novelty_and_foresight | 32 | 0 | 0 |
| route_task_fulfillment | 29 | 0 | 3 |
| system_and_cross_scenario_robustness | 25 | 2 | 5 |
| uncertainty_and_validation | 25 | 3 | 4 |

| 实验组 | 完成率 | 平均耗时(秒) | 平均模型调用量 | 平均估算成本 |
|---|---:|---:|---:|---:|
| 完整方法 | 100.0% | 1545.133 | 0.000 | 0.000000 |
| 去制胜机理 | 100.0% | 803.952 | 0.000 | 0.000000 |

## 4. 解释边界

- 置信区间跨越 0 时，只能报告方向性证据，不能宣称核心设计已被统计证明。
- 绑定历史项目报告且模型、时点或执行配置不完全一致时，本次结果自动降级为探索性。
- 任一消融运行出现被禁止的 L1-L4、Recall 或被移除阶段事件时，该比较不进入有效结论。
