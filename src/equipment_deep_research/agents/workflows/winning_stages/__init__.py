from .base import WinningStage
from .s1 import STAGE as S1
from .s2 import STAGE as S2
from .s3 import STAGE as S3
from .s4 import STAGE as S4
from .s5 import STAGE as S5
from .s6 import STAGE as S6

STAGES = {stage.step: stage for stage in (S1, S2, S3, S4, S5, S6)}


def stage_for(step: int) -> WinningStage:
    try:
        return STAGES[step]
    except KeyError as exc:
        raise KeyError(f"unknown winning stage: S{step}") from exc


__all__ = ["S1", "S2", "S3", "S4", "S5", "S6", "STAGES", "WinningStage", "stage_for"]
