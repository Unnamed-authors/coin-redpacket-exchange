from playwright.sync_api import sync_playwright
from pathlib import Path
import sys,uuid,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));import server
username='browser_'+uuid.uuid4().hex[:8]
with server.conn() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,0)',(username,username,server.password('test12345'),2000000))
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel="chrome")
    page=browser.new_page(viewport={'width':1440,'height':1200},device_scale_factor=1)
    errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://localhost:8080');page.wait_for_load_state('networkidle')
    page.screenshot(path=str(ROOT/'artifacts/login.png'),full_page=True)
    assert page.get_by_role('heading',name='登录我的金币账户').is_visible()
    page.get_by_label('用户名',exact=True).fill(username)
    page.get_by_label('密码',exact=True).fill('test12345')
    page.get_by_role('button',name='登录账户').click()
    page.get_by_role('heading',name='兑换消费红包',exact=True).wait_for()
    baseline=page.locator('.records .SUCCESS').count()
    page.get_by_label('兑换金币数量').fill('10000')
    page.get_by_role('button',name='确认兑换').click()
    page.wait_for_function('(n) => document.querySelectorAll(".records .SUCCESS").length === n',arg=baseline+1,timeout=15000)
    page.get_by_label('兑换金币数量').fill('100')
    page.get_by_role('button',name='Debug 接口测试').click()
    page.get_by_label('请求 JSON').fill(json.dumps({'coins':100,'mode':'unavailable','requestId':uuid.uuid4().hex}))
    page.get_by_role('button',name='发送请求',exact=True).click()
    page.get_by_role('button',name='恢复模拟服务').wait_for(timeout=10000)
    page.screenshot(path=str(ROOT/'artifacts/pending.png'),full_page=True)
    page.get_by_role('button',name='恢复模拟服务').click()
    page.wait_for_function('(n) => document.querySelectorAll(".records .SUCCESS").length === n',arg=baseline+2,timeout=15000)
    assert page.get_by_role('button',name='关闭 Debug',exact=True).count()==1
    page.get_by_role('button',name='关闭 Debug',exact=True).click()
    page.screenshot(path=str(ROOT/'artifacts/dashboard.png'),full_page=True)
    page.reload();page.get_by_role('heading',name='兑换消费红包',exact=True).wait_for()
    assert page.locator('.records .SUCCESS').count()==baseline+2
    assert not errors,errors
    page.get_by_role('button',name='退出',exact=True).click()
    page.get_by_role('heading',name='登录我的金币账户').wait_for()
    browser.close()
    print('PASS browser: login, exchange, pending, recovery, refresh persistence, logout; zero JS errors')
