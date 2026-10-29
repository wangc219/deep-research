"""生成不含部署凭据或运行数据的完整源码快照及逐文件校验清单。"""

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[2]
output = Path(__file__).resolve().parent
directories = {'backend', 'web', 'document_research', 'configs', 'docker', 'scripts', 'docs',
               'vendor', 'apps', 'src', 'tests', 'evals', '.github'}
ignored = {'node_modules', '.git', '.venv', 'venv', '__pycache__', 'dist', '.pytest_cache',
           '.ruff_cache', '.mypy_cache', '.cache', 'outputs', 'output', 'volumes',
           'skill-sources', 'skill-projections', 'user-data', 'bin', '.pnpm-store', '.DS_Store'}
embedded_key = 'vendor/wx_channels_download/pkg/certificate/certs/private.key'


def allowed(path):
    """显式排除凭据，仅保留采集程序原有嵌入式证书依赖。"""
    name = path.name
    if name.startswith('._') or name == '.DS_Store' or name.endswith(('.pyc', '.pyo', '.log')):
        return False
    if name.startswith('.env') or name.endswith('.env'):
        return name.endswith('.example')
    if path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}:
        return path.relative_to(root).as_posix() == embedded_key
    return True


files = []
for directory in sorted(directories):
    base = root / directory
    if not base.exists():
        continue
    for current, children, names in os.walk(base):
        children[:] = sorted(name for name in children if name not in ignored and not name.startswith('._'))
        for name in sorted(names):
            path = Path(current) / name
            if path.is_file() and allowed(path):
                assert path.resolve().is_relative_to(root), f'源码链接越界：{path}'
                files.append(path)
for path in sorted(root.iterdir()):
    if path.is_file() and allowed(path) and (
        path.suffix in {'.md', '.toml', '.yaml', '.yml', '.json', '.lock'}
        or path.name in {'Makefile', '.dockerignore', '.gitignore', '.env.example'}
        or path.name.startswith('Dockerfile')
    ):
        files.append(path)
files = sorted(set(files))
manifest = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
assert embedded_key in manifest
assert not any(name.endswith('JS.pem') or name.endswith('sandbox.env') for name in manifest)
manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
(output / 'source-manifest-final.json').write_bytes(manifest_bytes)
archive = output / 'source-final.tar.gz'
with tarfile.open(archive, 'w:gz', dereference=True) as package:
    for path in files:
        package.add(path, arcname=path.relative_to(root), recursive=False)
    info = tarfile.TarInfo('acceptance-source-manifest.json')
    info.size = len(manifest_bytes)
    info.mode = 0o644
    package.addfile(info, io.BytesIO(manifest_bytes))
sha = hashlib.sha256(archive.read_bytes()).hexdigest()
(output / 'source-final.sha256').write_text(sha + '  source-final.tar.gz\n')
print(json.dumps({'files': len(manifest), 'archive_bytes': archive.stat().st_size, 'sha256': sha}))
