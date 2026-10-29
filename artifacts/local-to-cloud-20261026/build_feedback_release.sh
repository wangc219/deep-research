#!/usr/bin/env bash
# 仅替换源码并原生构建镜像；不恢复数据库或触碰业务数据目录。
set -euo pipefail
umask 077
cd /opt/deep-research
python3 - <<'PY'
import hashlib, json, tarfile
from pathlib import Path
root=Path('/opt/deep-research')
archive=Path('/tmp/deepquest-feedback-source-20261026.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='092ca96ad13d88d86f22302791167cc3a40f1e66c4aeec71e73dc2b27f03f009'
old=json.loads((root/'acceptance-source-manifest.json').read_text())
with tarfile.open(archive) as source:
    new=json.load(source.extractfile('acceptance-source-manifest.json'))
    for member in source:
        assert member.name in new or member.name=='acceptance-source-manifest.json'
        assert (root/member.name).resolve().is_relative_to(root)
    source.extractall(root, filter='data')
for name in set(old)-set(new):
    path=root/name
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==old[name]
    path.unlink()
assert all((root/name).is_file() and hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in new.items())
result={'source_files':len(new), 'changed':[name for name in new if name in old and new[name]!=old[name]], 'added':sorted(set(new)-set(old)), 'removed':sorted(set(old)-set(new))}
Path('/var/lib/deepquest-migration/evidence-20261026/feedback-source-update.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
PY
DEEP_RESEARCH_VERSION=optimized-local-20261026-feedback bash scripts/cloud.sh build api web sandbox-provisioner
echo feedback_native_build_complete
