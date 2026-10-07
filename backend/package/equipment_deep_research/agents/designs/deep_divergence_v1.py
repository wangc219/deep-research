"""Design contract for the bounded deep-divergence workflow.

The deep workflow is deliberately represented as an agent design as well as
an execution profile so registry validation and prompt construction can treat
it like every other governed agent.  It does not expose hidden provider
traces; the public API only persists typed stage summaries and candidate
artifacts.
"""

from .base import AgentDesignSpec


DESIGN = AgentDesignSpec(
    "deep_divergence_v1",
    "继承父任务的 Query、结果和证据，在 S3/S4 进行受预算约束的多维发散；前瞻方向证据稀少时保留待验证边界并形成待核验 S6 能力卡。",
    specialization="深度追问、参考武器定向研究、证据缺口识别和版本化能力画像撰写",
    discovery="仅使用 canonical parent snapshot；先推演，再按证据缺口升级检索；最多三个 S3 和三个 S4 探索槽位。",
    search_mode="deep",
)
