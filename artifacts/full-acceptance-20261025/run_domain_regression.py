"""为历史领域测试提供其约定的仓库布局，不修改生产文件或跳过断言。"""
from pathlib import Path
import shutil,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='equipment-domain-') as tmp:
    mirror=Path(tmp)
    for path in root.iterdir():
        if path.name not in {'backend','.git'}: (mirror/path.name).symlink_to(path,target_is_directory=path.is_dir())
    (mirror/'package').symlink_to(root/'backend/package',target_is_directory=True)
    backend=mirror/'backend';backend.mkdir()
    for path in (root/'backend').iterdir():
        if path.name not in {'test','.venv'}: (backend/path.name).symlink_to(path,target_is_directory=path.is_dir())
    tests=backend/'test';tests.mkdir()
    shutil.copy(root/'backend/test/conftest.py',tests/'conftest.py')
    for path in (root/'backend/test/equipment_deep_research').iterdir():
        if path.is_dir() and path.name!='__pycache__':shutil.copytree(path,tests/path.name)
    targets=[str(tests/target) for target in sys.argv[1:]] or [str(tests/name) for name in ('e2e','integration','unit','query_library')]
    result=subprocess.run([sys.executable,'-m','pytest',*targets,
                '-q','--tb=short','-o','cache_dir=/tmp/domain-s5-final',
                '--junitxml='+str(root/('outputs/full-acceptance-20261025-domain-s5-resolved.xml' if sys.argv[1:] else 'outputs/full-acceptance-20261025-domain-s5-final.xml'))],
                cwd=root,env={**__import__('os').environ,'PYTHONPATH':str(root/'backend/package')+':'+str(root/'backend'),'EQUIPMENT_DR_PROJECT_ROOT':str(root)})
raise SystemExit(result.returncode)
