from .base import AgentDesignSpec

DESIGN = AgentDesignSpec(
    "combat_scenario",
    "把上游背景转换为任务阶段、约束、失败条件和能力压力点不同的场景。",
    specialization="消费上游结构化背景；每个背景默认生成2个、允许1至3个候选场景，全局默认不超过8个；至少包含最可能与最危险分支。",
    optimized_specialization="消费上游结构化背景；每个背景形成2个实质不同场景，总计6个；每项保留任务、阶段、约束、失败条件、军事压力点和证据ID。",
    discovery="你是作战场景公开资料检索Agent。只为关键场景断点寻找公开依据，覆盖战例、演训概念、无人智能、电磁网络太空、地形气象和持续保障；不得给出具体攻击步骤或实时定位。",
)
