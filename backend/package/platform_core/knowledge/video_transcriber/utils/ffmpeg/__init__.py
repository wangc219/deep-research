"""使用部署环境提供的 FFmpeg。"""
import os
import shutil

def get_ffmpeg_path():
    """解析音频处理命令。"""
    return os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")

def get_ffprobe_path():
    """解析媒体探测命令。"""
    return os.getenv("FFPROBE_PATH") or shutil.which("ffprobe")
