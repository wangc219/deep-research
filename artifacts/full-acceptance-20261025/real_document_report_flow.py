"""独立文档报告、追问、编辑冲突、下载和证据撤销的真实验收。"""

import io
import json
from pathlib import Path
import time
from uuid import uuid4
import zipfile

import httpx

config = json.loads(Path('/var/lib/document-research/config.json').read_text())
owner = config.get('settings_admins', ['local'])[0]
headers = {'Authorization': 'Bearer ' + config['tokens'][owner]}
base = 'http://127.0.0.1:4198/document-research-api'

with httpx.Client(base_url=base, headers=headers, timeout=120) as client:
    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def run_task(body):
        task = request('POST', '/tasks', json=body).json()
        assert task['status'] == 'ready', task
        request('POST', f"/tasks/{task['id']}/run")
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            result = request('GET', f"/tasks/{task['id']}").json()
            if result['status'] in {'completed', 'failed', 'cancelled'}:
                break
            time.sleep(1)
        assert result['status'] == 'completed', result
        return result

    library = request('POST', '/libraries', json={'name': '报告实测_' + uuid4().hex[:8]}).json()
    library_id = library['id']
    deleted = False
    try:
        text = '测试资料关注跨页表头。跨页表格解析应保留原始行列关系。此资料仅用于软件引用验收，未测量任何解析器性能。扫描表格需要人工真值标注。'
        request('POST', f'/libraries/{library_id}/documents',
                files={'file': ('report-acceptance.txt', text.encode(), 'text/plain')})
        common = {'library_ids': [library_id], 'allow_external_model': True}
        report = run_task(common | {
            'mode': 'research', 'problem': '根据测试资料设计跨页表格解析的验证实验，不推测任何解析器已有性能。',
            'parser_version': '候选版本尚未冻结，实验第一步冻结版本和样本。',
            'expected_result': '输出可复现的结构正确率与单元格文本正确率评估计划。',
            'constraints': '只有TXT案例说明，尚无实际表格样本；不运行解析器，不报告测量结果。',
        })
        body = report['report']
        assert body['measurement_status'] == 'not_measured'
        assert body['experiments'] and body['recommendation']['source_ids']
        for edge in body['graph']:
            assert edge['quote'] and edge['quote'] in text, edge

        task_id = report['id']
        files = request('GET', f'/tasks/{task_id}/artifacts').json()['items']
        assert any(item['name'] == 'report.md' and item['editable'] for item in files)
        artifact_path = f'/tasks/{task_id}/artifacts/report.md'
        original = request('GET', artifact_path).json()
        marker = '\n\n真实验收编辑标记：仅为交付副本补充备注。\n'
        edited = request('PUT', artifact_path, json={
            'content': original['content'] + marker, 'expected_sha256': original['sha256']}).json()
        assert edited['sha256'] != original['sha256']
        conflict = client.put(artifact_path, json={
            'content': 'stale write', 'expected_sha256': original['sha256']})
        assert conflict.status_code == 409
        downloaded = request('GET', artifact_path + '/download')
        assert downloaded.text.endswith(marker)
        archive = request('GET', f'/tasks/{task_id}/delivery.zip')
        with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
            assert package.read('report.md').decode().endswith(marker), package.namelist()

        followup = run_task(common | {
            'mode': 'answer', 'parent_task_id': task_id,
            'problem': '根据同一测试资料，扫描表格还需要什么标注？',
        })
        assert followup['report']['answer']
        for claim in followup['report']['answer']:
            assert claim['quote'] and claim['quote'] in text, claim
        assert any('真值' in item['text'] for item in followup['report']['answer'])

        request('DELETE', f'/libraries/{library_id}')
        deleted = True
        for path in (f'/tasks/{task_id}/delivery.zip', f"/tasks/{followup['id']}"):
            assert client.get(path).status_code == 403, path
        print(json.dumps({
            'report_task': task_id, 'followup_task': followup['id'],
            'real_research_report': 'passed', 'followup': 'passed',
            'artifact_edit_and_conflict': 'passed', 'download_and_zip': 'passed',
            'evidence_revocation': 'passed', 'experiments': len(body['experiments']),
        }, ensure_ascii=False), flush=True)
    finally:
        if not deleted:
            request('DELETE', f'/libraries/{library_id}')
