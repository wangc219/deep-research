"""收集脱敏验收输出，不包含部署凭据、数据库和业务对象备份。"""

from pathlib import Path
import tarfile
import shutil
import os

root=Path('/var/lib/deepquest-migration/evidence-20261026')
for path in Path('/var/log').glob('deepquest-*20261026.log'):
    if path.is_file():shutil.copy2(path,root/path.name)
destination=Path('/tmp/deepquest-final-evidence-20261026.tar.gz')
os.umask(0o077)
destination.unlink(missing_ok=True)
with tarfile.open(destination,'w:gz') as archive:
    for path in sorted(root.iterdir()):
        if path.is_file():archive.add(path,arcname='cloud-evidence/'+path.name,recursive=False)
    for path in sorted(Path('/opt/deep-research/outputs').glob('migration-20261026-*')):
        if path.is_file() and path.suffix in {'.json','.xml','.md'}:archive.add(path,arcname='cloud-evidence/runtime-outputs/'+path.name,recursive=False)
destination.chmod(0o600)
import pwd
account=pwd.getpwnam('ubuntu')
os.chown(destination,account.pw_uid,account.pw_gid)
print('acceptance_evidence_archive_ready')
