# 知识包访问规则

知识包是检索与上下文投影边界，不是无需证据即可引用的事实库。

- `public_evidence_index`：正式事实引用唯一入口，只按精确 Evidence ID 使用。
- `military_knowledge_base`：术语、任务链和体系框架，仅提供分析结构。
- `equipment_ontology`：型号、批次、参数、接口和保障属性归一化；冲突不得覆盖。
- `doctrine_library`：公开条令、作战概念和演习复盘，必须标明版本与适用场景。
- `case_library`：战例时间线、因果链和争议事实，必须保留迁移边界。
- `frontier_technology_library`：技术信号、TRL 和工程节点；潜力不等于已形成能力。
- `short_term_memory`：本次运行的蓝图、Packet、检查点和开放问题，不含原始会话。
- `long_term_memory`：经审计接受且带版本/来源的历史规律；过期内容必须重新验证。

若知识包只提供框架而没有 EvidenceCard，输出必须标为模型推断或待验证假设。

