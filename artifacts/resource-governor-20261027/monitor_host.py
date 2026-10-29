"""记录主机资源原始样本，停止信号仅用于本轮一次性验收。"""
import json
import time
from pathlib import Path

rows=[]
previous=None
for _ in range(900):
    if Path('/tmp/deepquest-governor-acceptance.stop').exists():break
    memory={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:','MemFree:','Buffers:','Cached:','SwapTotal:','SwapFree:'))}
    cpu=[int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    total=sum(cpu);idle=cpu[3]+cpu[4]
    row={'epoch_seconds':time.time(),'available_mib':round(memory['MemAvailable']/1024,1),'free_mib':round(memory['MemFree']/1024,1),
        'cache_mib':round((memory['Buffers']+memory['Cached'])/1024,1),'swap_used_mib':round((memory['SwapTotal']-memory['SwapFree'])/1024,1)}
    if previous:row['cpu_busy_percent']=round((1-(idle-previous[1])/(total-previous[0]))*100,1)
    previous=(total,idle)
    try:row['budget']=json.loads(Path('/opt/deep-research/outputs/runtime/resource-budget.json').read_text())
    except (OSError,ValueError):pass
    rows.append(row)
    time.sleep(2)
result={'samples':rows,'minimum_available_mib':min(row['available_mib'] for row in rows),
    'maximum_cpu_percent':max(row.get('cpu_busy_percent',0) for row in rows),'maximum_swap_used_mib':max(row['swap_used_mib'] for row in rows)}
Path('/tmp/resource-governor-host-metrics.json').write_text(json.dumps(result,indent=2))
print(json.dumps({key:value for key,value in result.items() if key!='samples'}))
