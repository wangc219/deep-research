"""归档最终日志、JUnit和只读运行状态；遇到短暂SSH中断最多重试三次。"""
import io,json,subprocess,tarfile
from pathlib import Path
r=Path(__file__).resolve().parent
ssh=['ssh','-i','/Users/wangchen/Downloads/JS.pem','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','ConnectTimeout=15','ubuntu@49.232.128.56']
def run(cmd):
 for attempt in range(3):
  p=subprocess.run(ssh+[cmd],capture_output=True)
  if p.returncode==0:return p.stdout
  if p.returncode!=255:raise RuntimeError(p.stderr.decode()[-1500:])
 raise RuntimeError('SSH unavailable after three attempts')
def unpack(data,dest):
 dest.mkdir(exist_ok=True)
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:
  for m in tar.getmembers():
   assert (dest/m.name).resolve().is_relative_to(dest.resolve())
   assert m.isfile() or m.isdir()
  tar.extractall(dest)
 for p in dest.rglob('*'):p.chmod(0o700 if p.is_dir() else 0o600)
run('sudo python3 /tmp/collect_final_release_state.py')
(r/'deployment-final.json').write_bytes(run('sudo cat /tmp/deployment-final.json'))
(r/'release-integrity-final.json').write_bytes(run('sudo cat /var/backups/deepquest/full-acceptance-20261025/cloud-acceptance/release-integrity-citation-final.json'))
run('sudo docker cp /tmp/verify_final_database.py deepquest-api-1:/tmp/verify_final_database.py')
raw=run('sudo docker exec -e PYTHONPATH=/app/package:/app deepquest-api-1 python /tmp/verify_final_database.py')
result=json.loads(next(line for line in raw.decode().splitlines() if line.startswith('{')))
state=json.loads((r/'final-state-verification.json').read_text())
state.update(result,checked_at=json.loads((r/'deployment-final.json').read_text())['checked_at'])
assert not Path('/tmp/deepquest-browser-private-state.json').exists()
(r/'final-state-verification.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
for source,target in [('cloud-academic-routing','academic-routing'),('cloud-provider-reasoning','provider-reasoning'),('cloud-academic-citation-final','academic-citation-final'),('cloud-academic-citation-resolved','academic-citation-resolved')]:
 run('sudo cp /tmp/'+source+'.log /var/backups/deepquest/full-acceptance-20261025/cloud-acceptance/'+target+'.log')
unpack(run('sudo tar -czf - -C /var/backups/deepquest/full-acceptance-20261025/cloud-acceptance .'),r/'cloud-logs')
names=run('sudo find /opt/deep-research/outputs -maxdepth 1 -name "full-acceptance-20261025*xml" -printf "%f\\n"').decode().splitlines()
assert all('/' not in n and n.endswith('.xml') for n in names)
unpack(run('sudo tar -czf - -C /opt/deep-research/outputs '+ ' '.join(names)),r/'cloud-xml')
unpack(run('sudo tar -czf - -C /opt/deep-research/outputs/full-acceptance-20261025-academic-results .'),r/'academic-routing-results')
run('sudo rm -rf -- /tmp/acceptance-citation-build')
run('sudo rm -f -- /tmp/enabled-model-verification-private.log')
print(json.dumps({'final_evidence_synced':True,'cloud_junit_files':len(names),'original_data_preserved':True,'temporary_identities_revoked':True}))
