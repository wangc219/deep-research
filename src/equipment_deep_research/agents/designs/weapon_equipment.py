from .base import AgentDesignSpec

DESIGN = AgentDesignSpec(
    "weapon_equipment",
    "围绕具体装备案例、技术途径、公开指标和证据边界形成升级或新研需求闭环。",
    optimized_focus="按国外/中国国内装备案例→问题难点解决路径→核心技术途径→指标与证据→能力差距→现役升级/新研→验证形成闭环。foreign_equipment_cases和domestic_equipment_cases必须分别给出具体国家/单位、装备型号或项目、状态、所解决问题、技术方案、核心技术、公开指标、来源URL、证据边界和可用图片URL；每个案例独立成项。comparative_findings应分别总结国内外优势、短板和本项目差异化优势。upgrade_requirements和new_equipment_requirements中的每个候选必须分别给出项目暂定名、概念/公开项目身份、单一主装备形态、project_function、Query因果链、目标与阶段、直接军事效果、公开基线差异、关键技术路线、体系接口、失效边界、证据问题、验证与淘汰条件。project_function必须回答谁在何种约束下依靠该装备完成什么动作并产生何种任务结果。",
    discovery="你是国内外武器装备公开资料对比检索Agent。国外优先美国、俄罗斯及其他军事技术强国，国内限定中国公开资料。必须消费Codex Query语义发散简报和Query专属证据通道，围绕敌方目标、作战阶段、任务约束与直接军事效果检索能够核验候选武器构型的公开基线；不得固定套用预设装备目录或从热门型号反向拼接Query。覆盖型号别名与批次、现役/在研状态、预算采购、试验部署、体系接口、保障供应链和公开能力边界；区分事实、推断、冲突和未知。必须分别形成国外案例和中国国内案例，每个案例独立记录问题/难点解决路径、技术方案、核心技术、核心公开指标、实证来源和可用图片URL，并总结双方优势与本项目差异化空间。",
    search_mode="equipment_deep",
)
