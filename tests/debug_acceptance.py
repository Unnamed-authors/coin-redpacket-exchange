"""Browser-driven Debug acceptance, uses isolated user and real downstream waits."""
import json,sys,time,uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));import server
uid='debugqa_'+uuid.uuid4().hex[:8]
with server.conn() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,uid,server.password('test12345'),10000))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='chrome');page=browser.new_page(viewport={'width':1500,'height':1100})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://localhost:8080');page.wait_for_load_state('networkidle')
    page.get_by_label('用户名',exact=True).fill(uid);page.get_by_label('密码',exact=True).fill('test12345')
    page.get_by_role('button',name='登录账户').click();page.get_by_role('button',name='Debug 接口测试').click()
    panel=page.get_by_role('region',name='Debug 接口测试')
    assert panel.get_by_role('link',name='接口文档').get_attribute('href')=='/docs/api'
    assert page.request.get('http://localhost:8080/docs/api').status==200
    def select(key):page.get_by_label('选择测试接口').select_option(key)
    def body(data):page.get_by_label('请求 JSON').fill(json.dumps(data))
    def send():
        choice=page.get_by_label('选择测试接口').input_value()
        method='GET' if choice in ('me','ledger') else 'POST'
        path={'me':'/api/me','exchange':'/api/exchanges','ledger':'/api/debug/ledger','recover':'/api/recover','send':'/api/debug/downstream','query':'/api/debug/downstream'}[choice]
        with page.expect_response(lambda r:r.url.endswith(path) and r.request.method==method) as info:
            panel.get_by_role('button',name='发送请求',exact=True).click()
        panel.get_by_role('button',name='发送请求',exact=True).wait_for(state='visible')
        page.wait_for_function("!document.querySelector('.debug-grid .primary').disabled")
        return info.value.status,info.value.json()
    select('me');status,data=send();assert status==200 and data['available']==10000
    print('PASS Debug account API and editable request/response',flush=True)
    # Exercise business failure and same-id replay.
    select('exchange');key=uuid.uuid4().hex;body({'coins':100,'requestId':key,'mode':'failure'})
    status,order=send();assert status==202
    panel.get_by_role('cell',name='RELEASE',exact=True).wait_for(timeout=15000)
    status,replay=send();assert status==200 and replay['id']==order['id'] and replay['status']=='FAILED'
    print('PASS Debug business failure, unfreeze ledger and idempotent replay',flush=True)
    # Fault recovery through Debug API; wait for reconciliation rather than directly settling.
    body({'coins':100,'requestId':uuid.uuid4().hex,'mode':'unavailable'});status,order=send();assert status==202
    page.wait_for_function("document.querySelector('.debug-state').textContent.includes('URLError')",timeout=15000)
    select('recover');body({'id':order['id']});assert send()[0]==200
    panel.get_by_role('cell',name='DEBIT',exact=True).wait_for(timeout=15000)
    print('PASS Debug connection refusal, pending visibility and recovery',flush=True)
    select('send')
    for mode,expected in [('success',0),('failure',1001),('http_error',None),('malformed',0),('unavailable',None)]:
        body({'operation':'send','amount':1,'requestId':uuid.uuid4().hex,'mode':mode})
        status,data=send()
        if expected is None:assert status==502 and data['outcome']=='UNKNOWN'
        else:assert status==200 and data['result']['code']==expected
    print('PASS isolated downstream success, failure, HTTP 503, malformed receipt and connection refusal',flush=True)
    key=uuid.uuid4().hex;body({'operation':'send','amount':1,'requestId':key,'mode':'timeout_success'})
    status,data=send();assert status==504 and data['outcome']=='UNKNOWN';started=time.monotonic()
    select('query');assert json.loads(page.get_by_label('请求 JSON').input_value())['requestId']==key
    status,data=send();assert status==200 and data['result']['code']==102
    page.screenshot(path=str(ROOT/'artifacts/debug-pending.png'),full_page=True)
    while time.monotonic()-started<40:
        page.wait_for_timeout(1500);status,data=send()
        if data['result']['code']==0:break
    assert data['result']['code']==0
    select('me');_,u=send();assert u['available']==9900 and u['frozen']==0 and u['redpacketBalance']==1 and u['todayCount']==2
    print('PASS real 30-second timeout, same-id query converges; isolated downstream never changes account/quota',flush=True)
    select('ledger');status,data=send();assert status==200 and len(data['ledger'])==4
    # Invalid JSON stays client-side; invalid valid-JSON object gets server 400.
    select('exchange');page.get_by_label('请求 JSON').fill('{');panel.get_by_role('button',name='发送请求',exact=True).click();assert panel.get_by_role('alert').inner_text()=='请求 JSON 格式错误'
    body([]);assert send()[0]==400
    page.screenshot(path=str(ROOT/'artifacts/debug-console.png'),full_page=True)
    assert not errors,errors
    page.get_by_role('button',name='关闭 Debug').click();assert panel.count()==0
    browser.close()
    print('PASS Debug ledger, invalid JSON, request history, close entry and zero JS errors')
