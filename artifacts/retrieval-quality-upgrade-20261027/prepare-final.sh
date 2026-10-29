#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup=/var/backups/deepquest/retrieval-quality-20261027
stage=/var/tmp/deepquest-retrieval-quality
mkdir -p "$backup" "$stage/candidate"
chmod 700 "$backup"
python3 - <<'PY'
from pathlib import Path
import hashlib,json,tarfile,subprocess
root=Path('/opt/deep-research');backup=Path('/var/backups/deepquest/retrieval-quality-20261027')
new=json.loads(Path('/tmp/deepquest-retrieval-source-manifest.json').read_text());old=json.loads((root/'acceptance-source-manifest.json').read_text())
with tarfile.open(backup/'source-final-before.tar.gz','w:gz') as archive:
 for name in new:
  path=root/name
  if not path.exists():continue
  if name in old:assert hashlib.sha256(path.read_bytes()).hexdigest()==old[name],name
  archive.add(path,arcname=name)
with tarfile.open('/tmp/deepquest-retrieval-source.tar.gz') as archive:archive.extractall('/var/tmp/deepquest-retrieval-quality/candidate',filter='data')
for name,digest in new.items():assert hashlib.sha256((Path('/var/tmp/deepquest-retrieval-quality/candidate')/name).read_bytes()).hexdigest()==digest
lines=['FROM deepquest-api:before-retrieval-api-20261027']
for name in new:lines.append('COPY '+name+' /app/'+name.removeprefix('backend/'))
Path('/var/tmp/deepquest-retrieval-quality/candidate/Dockerfile').write_text('\n'.join(lines)+'\n')
print(json.dumps({'verified_source_files':len(new),'candidate':'final'}))
PY
docker build -q -t deepquest-api:retrieval-candidate-20261027 "$stage/candidate"
network=$(cat "$backup/network")
docker run --rm --name deepquest-retrieval-qa --cpus 1.5 --memory 3g --network "$network" --env-file "$backup/runtime.env" -e TEST_USERNAME= -e TEST_PASSWORD= -e PYTHONPATH=/app/package:/app deepquest-api:retrieval-candidate-20261027 uv run --no-sync --group test pytest -o cache_dir=/tmp/retrieval-qa-cache test/unit/agents/test_retrieval_long_tail.py test/unit/agents/test_search_resilience.py test/unit/agents/test_web_search_provider.py test/unit/services/test_aminer.py test/unit/services/test_aminer_mcp.py test/unit/middlewares/test_academic_evidence.py test/unit/services/test_web_search_coordinator.py test/integration/services/test_academic_retrieval.py test/integration/services/test_web_search_coordinator_redis.py -q --disable-warnings --tb=short
