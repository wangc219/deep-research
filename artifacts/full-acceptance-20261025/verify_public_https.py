"""从用户电脑访问正式域名，核对 TLS、静态资源、鉴权和公开 readiness。"""
import hashlib,json
from html.parser import HTMLParser
from pathlib import Path
import httpx

class Assets(HTMLParser):
    def __init__(self):super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script' and a.get('src'):self.urls.append(a['src'])
        if tag=='link' and a.get('rel')=='stylesheet' and a.get('href'):self.urls.append(a['href'])

root=Path(__file__).resolve().parent
with httpx.Client(base_url='https://www.deepquest.space',timeout=60,trust_env=False) as c:
    response=c.get('/');assert response.status_code==200 and 'id="app"' in response.text
    assert response.headers['x-content-type-options']=='nosniff'
    internal=httpx.get('http://127.0.0.1:18088',timeout=30,trust_env=False)
    assert hashlib.sha256(response.content).digest()==hashlib.sha256(internal.content).digest()
    assets=Assets();assets.feed(response.text)
    assert assets.urls
    for path in assets.urls:
        asset=c.get(path);assert asset.status_code==200 and len(asset.content)>100
        assert 'text/html' not in asset.headers.get('content-type','')
    ready=c.get('/api/system/ready');assert ready.status_code==200 and ready.json()['status']=='ready' and not ready.json()['degraded']
    private=json.loads(Path('/tmp/deepquest-browser-private-state.json').read_text())
    auth=c.post('/api/auth/token',data={'username':private['uid'],'password':private['password']})
    assert auth.status_code==200
    me=c.get('/api/auth/me',headers={'Authorization':'Bearer '+auth.json()['access_token']})
    assert me.status_code==200 and me.json()['uid']==private['uid']
    denied=c.get('/api/system/logs');assert denied.status_code in {401,403}
    redirect=httpx.get('http://www.deepquest.space/',follow_redirects=False,timeout=30,trust_env=False)
    assert redirect.status_code==301 and redirect.headers['location'].startswith('https://www.deepquest.space')
    result={'public_https':'passed','tls_verification':True,'maintenance':False,'public_internal_build_identical':True,
      'static_assets_validated':len(assets.urls),'real_password_login':'passed','public_readiness':'ready',
      'unauthenticated_admin_logs_denied':denied.status_code,'http_to_https_redirect':301}
    (root/'public-https-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result))
