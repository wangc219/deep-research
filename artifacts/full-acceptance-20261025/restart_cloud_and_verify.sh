#!/usr/bin/env bash
# 无活动任务时在维护窗口重启全部服务，验证实际持久化数据。
set -euo pipefail
umask 077
cd /opt/deep-research
TASK_LOGS=/var/backups/deepquest/full-acceptance-20261025/cloud-acceptance
test -f /var/www/deepquest.maintenance
active="$(docker exec -i deepquest-api-1 python - < /tmp/cloud-preflight-20261018.py)"
[[ "$active" == *'tasks=0 research=0 agents=0'* ]]
bash scripts/cloud.sh stop api worker equipment-worker equipment-query-worker web document-research document-websearch open-websearch
# 没有活动 Agent 后仍要求控制器权威枚举沙盒归零。
docker exec -i deepquest-sandbox-provisioner-1 python - <<'PY'
import json,os
from urllib.request import Request,urlopen
req=Request('http://127.0.0.1:8002/api/sandboxes/quiesce',data=b'',method='POST',headers={'Authorization':'Bearer '+os.environ['SANDBOX_PROVISIONER_TOKEN']})
with urlopen(req,timeout=195) as r:assert json.load(r)['ok'] is True
PY
bash scripts/cloud.sh stop sandbox-provisioner graph milvus
bash scripts/cloud.sh stop etcd minio redis postgres
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 postgres redis minio etcd open-websearch
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 240 graph milvus
bash scripts/cloud.sh up -d --no-deps --wait --wait-timeout 300 sandbox-provisioner api worker web document-websearch document-research equipment-worker equipment-query-worker
python3 /tmp/cloud_persistence_flow.py verify > "$TASK_LOGS/persistence-verify.log"
uid="$(python3 -c 'import json;print(json.load(open("/var/backups/deepquest/full-acceptance-20261025/persistence-private-state.json"))["uid"])')"
docker exec -e "ACCEPTANCE_RETIRE_UID=$uid" deepquest-api-1 python /tmp/cloud_persistence_identity.py > "$TASK_LOGS/persistence-identity-retired.log"
rm /var/backups/deepquest/full-acceptance-20261025/persistence-private-state.json
python3 /tmp/verify_running_release.py > "$TASK_LOGS/release-integrity-final.json"
printf 'all_services_restart_and_persistence=passed\n'
