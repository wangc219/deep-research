"""测量本机到云端的 HTTPS 实际传输与 HTTP/2，不保存下载内容。"""
import concurrent.futures
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.request import urlopen

origin='https://www.deepquest.space'
with urlopen(origin,timeout=30) as response:html=response.read().decode()
asset=re.search(r'src="(/assets/index-[^"]+\.js)"',html)[1]

def transfer(index,compressed):
    args=['curl','--http2','--fail','--silent','--show-error','--max-time','60','--output','/dev/null','--write-out','%{json}']
    if compressed:args+=['--compressed']
    result=subprocess.run([*args,origin+asset+'?bandwidth_probe='+str(time.time_ns())],capture_output=True,text=True,check=True)
    row=json.loads(result.stdout)
    return {'compressed':compressed,'http_version':row['http_version'],'bytes':row['size_download'],'seconds':row['time_total'],
            'ttfb_seconds':row['time_starttransfer'],'overall_mbps':round(row['size_download']*8/row['time_total']/1e6,2)}
rows=[transfer(0,False),transfer(1,True)]
start=time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:parallel=list(pool.map(lambda n:transfer(n,True),range(4)))
seconds=time.monotonic()-start
result={'asset':asset,'single_transfers':rows,'four_parallel_transfers':parallel,'parallel_seconds':round(seconds,3),
        'aggregate_mbps':round(sum(row['bytes'] for row in parallel)*8/seconds/1e6,2)}
Path(__file__).with_name('bandwidth.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
