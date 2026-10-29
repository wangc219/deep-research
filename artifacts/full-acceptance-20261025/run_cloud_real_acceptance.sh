#!/usr/bin/env bash
set -euo pipefail
umask 077
TASK_LOGS=/var/backups/deepquest/full-acceptance-20261025/cloud-acceptance
docker exec -e PYTHONPATH=/app/package:/app -e TEST_BASE_URL=http://web -e EQUIPMENT_TEST_LIVE_MODELS=1 -e RUN_FULL_REAL_ACCEPTANCE=1 -e RUN_VIDEO_LIVE=1 deepquest-api-1 python /tmp/run_live_tests.py test/e2e/test_agent_async_e2e.py test/e2e/test_agent_call_entrypoints_e2e.py test/e2e/test_agent_steer_e2e.py test/e2e/test_attachment_and_agent_state.py test/e2e/test_mcp_lazy.py test/e2e/test_mcp_stdio_security.py test/e2e/test_ocr_config_center_e2e.py test/e2e/test_parallel_subagents.py test/e2e/test_personal_skill_agent_e2e.py test/e2e/test_subagent_stream_e2e.py test/e2e/test_real_external_retrieval.py test/integration/api/test_native_deep_models_live.py test/integration/api/test_sandbox_workspace_delivery.py test/integration/api/test_full_real_knowledge_acceptance.py test/integration/api/test_wxchannels_live.py -s -q --tb=short -o cache_dir=/tmp/cloud-acceptance-real --junitxml=/app/outputs/full-acceptance-20261025-cloud-real.xml > "$TASK_LOGS/real.log" 2>&1
docker exec -e PYTHONPATH=/app/package:/app -e TEST_BASE_URL=http://web deepquest-api-1 python /tmp/run_multimodal_acceptance.py > "$TASK_LOGS/multimodal.log" 2>&1
printf 'cloud_backend_acceptance=passed\n'
