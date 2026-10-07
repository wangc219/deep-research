"""将旧研究运行时的计量事件映射到平台账本，不改变领域编排。"""

from typing import Any

from platform_core.models.providers.cache import model_cache
from platform_core.repositories import model_call_repository
from platform_core.utils import get_docker_safe_url


def create_equipment_call_observer(*, provider_id, model, base_url, api_key, isolation_key):
    """绑定真实模型身份；只持久化计量字段，不保存凭据、地址或正文。"""
    from equipment_deep_research.providers.openai_compatible import normalize_chat_completions_url

    endpoint = normalize_chat_completions_url(base_url)
    specs = [
        item.spec
        for item in model_cache.get_all_specs("chat")
        if item.model_id == model
        and item.api_key == api_key
        and endpoint
        in {
            normalize_chat_completions_url(item.base_url),
            normalize_chat_completions_url(str(get_docker_safe_url(item.base_url) or item.base_url)),
        }
    ]
    # 多个配置完全同址同密钥同模型时不能凭空认定某个别名。
    model_spec = specs[0] if len(specs) == 1 else f"unattributed:{provider_id}:{model}"

    def observe(event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "")
        if isolation_key.startswith("query-gen-"):
            surface = "Query 生成"
            run_id = str(
                event.get("run_id")
                or isolation_key.removeprefix("query-gen-")
            )
        elif isolation_key == "prompt-evolution":
            surface = "反馈自进化"
            run_id = str(event.get("run_id") or "")
        elif isolation_key.startswith("deep-") or phase.startswith("deep_"):
            surface = "深研对话"
            run_id = str(
                event.get("run_id")
                or isolation_key.removeprefix("deep-")
            )
        else:
            surface = "研究任务"
            run_id = str(event.get("run_id") or isolation_key)
        usage = event.get("usage") or {}

        def count(*keys):
            for key in keys:
                value = usage.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    return value
            return None

        inputs, outputs = count("prompt_tokens", "input_tokens"), count("completion_tokens", "output_tokens")
        total = count("total_tokens")
        if total is None and inputs is not None and outputs is not None:
            total = inputs + outputs
        row = {
            "id": event["id"],
            "model_spec": model_spec[:512],
            "surface": surface,
            "run_id": run_id[:256],
            "phase": phase[:256],
            "status": event["status"],
            "duration_ms": event["duration_ms"],
            "input_tokens": inputs,
            "output_tokens": outputs,
            "total_tokens": total,
            "error_type": str(event.get("error_type") or "")[:128],
        }
        model_call_repository.record_model_call(row)

    return observe
