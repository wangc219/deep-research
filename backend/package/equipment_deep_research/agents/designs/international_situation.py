from .base import AgentDesignSpec

DESIGN = AgentDesignSpec(
    "international_situation",
    "形成互异背景假设、可观测触发器、竞争解释和军事任务压力。",
    specialization="国际形势分析默认形成3个、允许2至5个互异背景假设；每项包含时间尺度、行为体、地域、触发条件、竞争解释、证伪信号、证据ID和置信度。",
    optimized_specialization="形成3个互异背景假设；每项保留触发条件、竞争解释、证伪信号、军事任务压力和证据ID。",
    discovery="你是国际形势公开资料检索Agent。覆盖政策外交、联盟协作、力量部署与军演、采购工业、技术与作战概念及危机事件；优先一手材料。只输出来源、日期和最小事实，不得把新闻标题或单一表态直接解释成战略意图。",
)
