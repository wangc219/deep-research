from .base import AgentDesignSpec

DESIGN = AgentDesignSpec(
    "operational_employment",
    "按任务链、备选运用、协同保障、失败模式和装备功能需求形成闭环。",
    discovery="你是作战运用公开资料检索Agent。覆盖公开条令、演训复盘、联合协同、保障韧性、多类COA及失败模式；只提取任务级事实和适用边界。",
)
