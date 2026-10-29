"""使用公开微信视频验证 HTTPS 连接包、个人采集、云端识别与文件交付。"""
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import zipfile
from uuid import uuid4

import httpx
from docx import Document

PRIVATE = Path('/tmp/wechat-cloud-qa-20261026')
OUT = Path(__file__).resolve().parent
BASE = '/api/knowledge/wxchannels'
ORIGIN = 'https://www.deepquest.space'
identity = json.loads((PRIVATE / 'identity.json').read_text())
summary = {'site': ORIGIN}
devices = []
collector = None
success = False
os.umask(0o077)


def progress(phase, **facts):
    print(json.dumps({'phase': phase, **facts}, ensure_ascii=False), flush=True)


with httpx.Client(base_url=ORIGIN, headers={'Authorization': 'Bearer ' + identity['token']}, timeout=180, trust_env=False) as client:
    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        response.raise_for_status()
        return response

    def wait_task(task_id):
        deadline = time.monotonic() + 900
        last = None
        while time.monotonic() < deadline:
            task = request('GET', BASE + '/tasks/' + task_id).json()
            state = (task['status'], task.get('message'))
            if state != last:
                progress('task_progress', status=task['status'], message=task.get('message'))
                last = state
            if task['status'] in {'success', 'failed', 'cancelled'}:
                assert task['status'] == 'success', 'Cloud task did not complete successfully'
                return task
            time.sleep(2)
        raise RuntimeError('Cloud video task timed out')

    try:
        ready = request('GET', '/api/system/ready').json()
        assert ready['status'] == 'ready' and not ready['degraded']
        state = request('GET', BASE + '/status').json()
        assert state['ffmpeg_available'] and state['asr_available']
        summary['server_audio_and_asr'] = 'passed'
        progress('server_ready')
        for platform in ['macos', 'windows']:
            device = 'wxd_' + uuid4().hex
            config = {'device_id': device, 'token': secrets.token_hex(32), 'name': '微信云端验收 ' + platform,
                      'platform': platform, 'platform_url': ORIGIN}
            response = request('POST', BASE + '/collector/package', json=config)
            devices.append(device)
            assert 'no-store' in response.headers.get('cache-control', '')
            with zipfile.ZipFile(io.BytesIO(response.content)) as package:
                assert json.loads(package.read('video-collector.json')) == config
                binaries = [name for name in package.namelist() if name.startswith('bin/')]
                assert len(binaries) == 2
                assert all(package.getinfo(name).file_size > 1_000_000 for name in binaries)
                if platform == 'macos':
                    folder = PRIVATE / 'mac-package'
                    folder.mkdir(exist_ok=True)
                    package.extractall(folder)
                    assert package.getinfo('连接我的微信.command').external_attr >> 16 & 0o100
                    mac_device = device
            summary[platform + '_connection_package'] = 'passed'
            progress('connection_package_verified', platform=platform)
        log = (PRIVATE / 'collector.log').open('w')
        collector = subprocess.Popen([sys.executable, 'bootstrap.py'], cwd=PRIVATE / 'mac-package',
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (PRIVATE / 'collector.pid').write_text(str(collector.pid))
        (PRIVATE / 'devices.json').write_text(json.dumps(devices))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            assert collector.poll() is None, 'Downloaded connection program exited; see private collector log'
            listed = request('GET', BASE + '/collector/devices').json()['items']
            selected = next((device for device in listed if device['device_id'] == mac_device), None)
            if selected and selected.get('online') and selected.get('state', {}).get('channels_ready'):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Downloaded connection package did not connect to the cloud website')
        summary['downloaded_package_real_wechat_connection'] = 'passed'
        progress('wechat_connected_over_public_https')
        source = {'account': '央视新闻', 'max_pages': 1, 'collection_mode': 'personal', 'device_id': mac_device}
        task = wait_task(request('POST', BASE + '/videos', json=source).json()['task_id'])
        videos = task['result']['videos']
        assert videos
        chosen = next((item for item in videos if '四季食单' in item.get('title', '') or '腊' in item.get('title', '')), videos[0])
        summary['real_video_discovery'] = len(videos)
        progress('real_video_discovered', videos=len(videos), title=chosen['title'][:120])
        submitted = request('POST', BASE + '/transcribe', json={**source, 'video_oids': [chosen['oid']], 'max_videos': 1, 'timeout_seconds': 600}).json()
        assert submitted['submitted']
        task = wait_task(submitted['task_id'])
        assert task['result']['completed_count'] == 1 and not task['result'].get('failed_count')
        item = task['result']['items'][0]
        word = request('GET', BASE + f"/tasks/{task['id']}/items/{item['index']}/docx")
        text = '\n'.join(paragraph.text for paragraph in Document(io.BytesIO(word.content)).paragraphs)
        assert len(item.get('text', '')) > 30 and item['text'][:30] in text
        (OUT / 'cloud-video.docx').write_bytes(word.content)
        archive = request('GET', BASE + f"/tasks/{task['id']}/archive")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert len(bundle.namelist()) == 1
        markdown_path = item['workspace_path'].removesuffix('.docx') + '.md'
        markdown = request('GET', '/api/workspace/file', params={'path': markdown_path})
        assert item['text'][:30] in markdown.text
        listed = request('GET', '/api/knowledge/collection-artifacts/wxchannels').json()['items']
        assert any(record['primary_path'] == item['workspace_path'] and record['available'] and record['import_available'] for record in listed)
        summary.update({'real_cloud_asr': 'passed', 'word_download': 'passed', 'word_archive': 'passed', 'markdown_preview': 'passed',
                        'workspace_artifact': 'passed', 'recognized_characters': len(item['text']), 'task_id': task['id']})
        (OUT / 'cloud-validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
        progress('cloud_video_delivery_passed', recognized_characters=len(item['text']))
        success = True
    finally:
        if not success:
            if collector and collector.poll() is None:
                collector.terminate()
                collector.wait(timeout=20)
            for device in devices:
                request('DELETE', BASE + '/collector/devices/' + device)
