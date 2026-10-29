"""以当前 API 的私有连接配置验证候选镜像，不打印环境凭据。"""
from pathlib import Path
import json
import subprocess

container = json.loads(subprocess.check_output(['docker','inspect','deepquest-api-1'],text=True))[0]
env = dict(value.split('=',1) for value in container['Config']['Env'])
path = Path('/tmp/resource-fix-test.env')
path.write_text('\n'.join(key+'='+value for key,value in env.items() if key in {'POSTGRES_URL','PYTHONPATH','JWT_SECRET_KEY','API_KEY_DERIVATION_SECRET'})+'\n')
path.chmod(0o600)
try:
    result = subprocess.run(['docker','run','--rm','--user','0','--network',next(iter(container['NetworkSettings']['Networks'])),
        '--env-file',str(path),'--entrypoint','python','deepquest-api:resource-pool-fix-candidate-20261027','-m','pytest',
        '/app/test/integration/services/test_resource_connection_reuse.py','/app/test/integration/services/test_agent_user_capacity.py',
        '/app/test/unit/services/test_run_scheduling.py','-c','/app/pyproject.toml','-q','--tb=short','-o','cache_dir=/tmp/resource-fix-cache'])
    raise SystemExit(result.returncode)
finally:
    path.unlink(missing_ok=True)
