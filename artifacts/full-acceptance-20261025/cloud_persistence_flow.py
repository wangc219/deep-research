"""在云宿主上通过真实 HTTP 验证重启前后的 PG、对象文件、向量和认证持久性。"""

import json
import os
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen
from uuid import uuid4

state_file = Path('/var/backups/deepquest/full-acceptance-20261025/persistence-private-state.json')
operation = sys.argv[1]
state = json.load(sys.stdin) if operation == 'prepare' else json.loads(state_file.read_text())


def request(method, path, body=None, content_type='application/json'):
    """请求本机云 API，不将令牌或请求头写入日志。"""
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    req = Request('http://127.0.0.1:6050' + path, data=body, method=method, headers={
        'Authorization': 'Bearer ' + state['token'], 'Content-Type': content_type})
    with urlopen(req, timeout=120) as response:
        return json.loads(response.read())


def finish(task_id):
    """等待实际 Worker 完成持久任务。"""
    for _ in range(180):
        task = request('GET', '/api/tasks/' + task_id)['task']
        if task['status'] in {'success', 'failed', 'cancelled'}:
            assert task['status'] == 'success', task
            return
        time.sleep(1)
    raise RuntimeError('持久化测试任务超时')


if operation == 'prepare':
    os.umask(0o077)
    state['marker'] = 'PERSISTENCE_' + uuid4().hex
    kb = request('POST', '/api/knowledge/databases', {
        'database_name': 'pytest_persistence_' + uuid4().hex[:8], 'kb_type': 'milvus',
        'description': '仅用于容器重启持久化验收', 'embedding_model_spec': 'siliconflow-cn:Pro/BAAI/bge-m3',
        'additional_params': {}, 'share_config': {'version': 2, 'read_scope': {
            'access_level': 'user', 'user_uids': [state['uid']]}, 'manage_scope': None}})
    state['kb_id'] = kb['kb_id']
    state_file.write_text(json.dumps(state))
    state_file.chmod(0o600)
    boundary = 'acceptance_' + uuid4().hex
    content = (state['marker'] + '。该测试记录用于确认数据库、原文对象和向量在重启后仍可读取。').encode()
    multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="persistence.txt"\r\n'
                 'Content-Type: text/plain\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
    upload = request('POST', f"/api/knowledge/files/upload?kb_id={state['kb_id']}", multipart,
                     'multipart/form-data; boundary=' + boundary)
    prefix = '/api/knowledge/databases/' + state['kb_id']
    added = request('POST', prefix + '/documents/add', {
        'items': [upload['file_path']], 'params': {'content_hashes': {upload['file_path']: upload['content_hash']},
                                                'file_sizes': {upload['file_path']: upload['size']}}})
    state['file_id'] = added['items'][0]['file_id']
    parsed = request('POST', prefix + '/documents/parse', {'file_ids': [state['file_id']], 'params': {}})
    finish(parsed['task_id'])
    indexed = request('POST', prefix + '/documents/index', {'file_ids': [state['file_id']]})
    finish(indexed['task_id'])
    state['index_task_id'] = indexed['task_id']
    state_file.write_text(json.dumps(state))
    print(json.dumps({'persistence_prepared': True, 'kb_id': state['kb_id']}))
else:
    prefix = '/api/knowledge/databases/' + state['kb_id']
    assert request('GET', '/api/auth/me')['uid'] == state['uid']
    assert request('GET', '/api/tasks/' + state['index_task_id'])['task']['status'] == 'success'
    content = request('GET', prefix + '/documents/' + state['file_id'] + '/content')
    assert state['marker'] in json.dumps(content, ensure_ascii=False), content
    results = request('POST', prefix + '/query', {'query': state['marker'], 'meta': {
        'final_top_k': 3, 'similarity_threshold': 0}})
    assert state['marker'] in json.dumps(results, ensure_ascii=False), results
    request('DELETE', prefix)
    print(json.dumps({'restart_persistence': 'passed', 'jwt': 'passed', 'postgres_task': 'passed',
                      'minio_document': 'passed', 'milvus_retrieval': 'passed', 'retire_uid': state['uid']}))
