#!/usr/bin/env bash
set -euo pipefail
umask 077
cd /opt/deep-research
backup="/opt/backups/deepquest-interaction-api-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup/candidate" "$backup/tests"
cp /tmp/cloud-service-before.py /tmp/cloud-service-after.py "$backup/"
cp /tmp/test_research_interaction_loading.py /tmp/test_equipment_research_service.py "$backup/tests/"
python3 - "$backup" <<'PY'
from pathlib import Path
import json,sys,subprocess,hashlib
b=Path(sys.argv[1]);r=Path('/opt/deep-research');f=r/'backend/package/platform_core/services/equipment_research_service.py'
assert f.read_bytes()==(b/'cloud-service-before.py').read_bytes(),'宿主源码与运行版本不一致'
actual=subprocess.check_output(['docker','exec','deepquest-api-1','cat','/app/package/platform_core/services/equipment_research_service.py'])
assert actual==f.read_bytes(),'运行文件已发生变化'
info=json.loads(subprocess.check_output(['docker','inspect','deepquest-api-1']))[0]
(b/'api-before.json').write_text(json.dumps(info,indent=2))
(b/'image-before').write_text(info['Image']);(b/'config-image').write_text(info['Config']['Image'])
assert not any('\n' in value for value in info['Config']['Env'])
(b/'api-env').write_text('\n'.join(info['Config']['Env'])+'\n')
(b/'network').write_text(next(n for n in info['NetworkSettings']['Networks'] if 'app-network' in n))
(b/'manifest-before.json').write_bytes((r/'acceptance-source-manifest.json').read_bytes())
(b/'containers-before.json').write_text(subprocess.check_output(['docker','ps','--no-trunc','--format','{{json .}}'],text=True))
PY
base_tag="deepquest-api:interaction-base-$(date +%Y%m%d-%H%M%S)"
docker tag "$(cat "$backup/image-before")" "$base_tag"
cp "$backup/cloud-service-after.py" "$backup/candidate/equipment_research_service.py"
cat > "$backup/candidate/Dockerfile" <<DOCKER
FROM $base_tag
COPY --chown=1000:1000 equipment_research_service.py /app/package/platform_core/services/equipment_research_service.py
DOCKER
docker build -t deepquest-api:interaction-candidate-20261029 "$backup/candidate"
docker image inspect deepquest-api:interaction-candidate-20261029 --format '{{.Id}}' > "$backup/image-candidate"
printf '%s\n' "$backup" > /tmp/deepquest-interaction-api-backup-path

docker run --rm --user 0 --network "$(cat "$backup/network")" --env-file "$backup/api-env" \
  -v "$backup/tests:/tmp/interaction-tests:ro" \
  deepquest-api:interaction-candidate-20261029 python -m pytest \
  /tmp/interaction-tests/test_research_interaction_loading.py \
  /tmp/interaction-tests/test_equipment_research_service.py \
  -k 'compact_interactions_keep or compact_event_count or run_projection_endpoints or run_interactions_fall_back or run_artifact_endpoints' \
  -q -p no:cacheprovider
printf 'candidate_prepared=%s\n' "$backup"
