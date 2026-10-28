"""降低独立语音进程加载本地权重时的内存峰值。"""

from pathlib import Path

import torch


def install_low_memory_loader():
    """为当前独立进程安装内存映射加载器，避免 FunASR 深复制整份权重。"""
    import funasr.auto.auto_model as runtime

    original = runtime.load_pretrained_model

    def load_pretrained_model(
        path,
        model,
        ignore_init_mismatch=True,
        map_location="cpu",
        oss_bucket=None,
        scope_map=None,
        excludes=None,
        **kwargs,
    ):
        """沿用名称、形状与加载回调规则，以只读映射替代多份权重副本。"""
        if oss_bucket is not None or map_location != "cpu":
            return original(
                path,
                model,
                ignore_init_mismatch=ignore_init_mismatch,
                map_location=map_location,
                oss_bucket=oss_bucket,
                scope_map=scope_map or [],
                excludes=excludes,
                **kwargs,
            )
        checkpoint = torch.load(Path(path), map_location="cpu", mmap=True, weights_only=True)
        source = checkpoint
        for key in ("state_dict", "model_state_dict", "model"):
            if key in source:
                source = source[key]
        prefixes = scope_map.split(",") if isinstance(scope_map, str) else list(scope_map or [])
        prefixes += ["module.", "None"]
        excluded = excludes.split(",") if isinstance(excludes, str) else list(excludes or [])
        destination = model.state_dict()
        loaded = set()
        for key, current in destination.items():
            if any(key.startswith(prefix) for prefix in excluded):
                continue
            source_key = key
            for index in range(0, len(prefixes), 2):
                src = "" if prefixes[index].lower() == "none" else prefixes[index]
                dst = "" if prefixes[index + 1].lower() == "none" else prefixes[index + 1]
                candidate = src + key if not dst else key.replace(dst, src, 1)
                if (not dst or key.startswith(dst)) and candidate in source:
                    source_key = candidate
            if source_key not in source:
                continue
            value = source[source_key]
            if ignore_init_mismatch and current.shape != value.shape:
                continue
            destination[key] = value
            loaded.add(key)
        model.load_state_dict(destination, strict=True, assign=True)
        callback = getattr(model, "on_pretrained_model_loaded", None)
        if callable(callback):
            callback(frozenset(loaded))

    runtime.load_pretrained_model = load_pretrained_model
