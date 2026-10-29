"""使用已验收的新源码准备空部署，按用户要求永久移除原云端备份。"""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

root = Path('/opt/deep-research')
old = Path('/var/backups/deepquest/offline-before-local-optimization-20261025/deployment-and-persistent-data')
archive = Path('/tmp/deepquest-source-20261026.tar.gz')
assert hashlib.sha256(archive.read_bytes()).hexdigest() == 'e5074e087f8392b1c7950d9d18ff2037a92b724c8eb217c626540581620eef9c'
assert not subprocess.check_output(['docker', 'ps', '-aq'], text=True).strip()
assert not root.exists()
root.mkdir(mode=0o755)
with tarfile.open(archive) as package:
    for member in package.getmembers():
        assert not member.issym() and not member.islnk()
        assert (root / member.name).resolve().is_relative_to(root)
    package.extractall(root, filter='data')
manifest = json.loads((root / 'acceptance-source-manifest.json').read_text())
assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in manifest.items())
# 只保留生产基础设施配置；不复制旧业务数据或账号。
for relative in ('.env.prod', 'docker/sandbox_provisioner/sandbox.env'):
    source = old / relative
    target = root / relative
    assert source.is_file()
    shutil.copyfile(source, target)
    target.chmod(0o600)
env = root / '.env.prod'
lines = [line for line in env.read_text().splitlines() if not line.startswith('DEEP_RESEARCH_VERSION=')]
env.write_text('\n'.join(lines) + '\nDEEP_RESEARCH_VERSION=optimized-local-20261026\n')
env.chmod(0o600)
# 原云端所有业务快照、历史数据库导出及持久化备份均在这一专用目录。
backup_root = Path('/var/backups/deepquest')
assert backup_root.is_dir() and not backup_root.is_symlink()
shutil.rmtree(backup_root)
volumes = subprocess.check_output(['docker', 'volume', 'ls', '--format', '{{.Name}}'], text=True).splitlines()
assert volumes == ['deepquest_document-research-data'], volumes
subprocess.run(['docker', 'volume', 'rm', 'deepquest_document-research-data'], check=True)
assert not backup_root.exists()
assert not subprocess.check_output(['docker', 'volume', 'ls', '--format', '{{.Name}}'], text=True).strip()
result = {'old_cloud_business_backups_permanently_removed': True,
          'old_document_volume_removed': True, 'new_source_files_verified': len(manifest),
          'new_data_source': 'local', 'old_business_data_restored': False,
          'infrastructure_configuration_only_retained': True}
Path('/var/lib/deepquest-migration').mkdir(mode=0o700, exist_ok=True)
Path('/var/lib/deepquest-migration/old-cloud-data-removal-20261026.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
