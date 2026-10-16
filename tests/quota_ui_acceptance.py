import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome');ctx=browser.new_context(viewport={'width':1440,'height':1050});base='http://localhost:8080'
 assert ctx.request.post(base+'/api/login',data={'username':'demo','password':'demo12345'}).status==200
 username='fresh_'+uuid.uuid4().hex[:8]
 assert ctx.request.post(base+'/api/admin/users',data={'username':username,'password':'test12345','initialCoins':2000000}).status==201
 full=ctx.request.get(base+'/api/me').json()['todayCount']
 page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto(base);page.get_by_role('heading',name='兑换消费红包',exact=True).wait_for()
 assert page.locator('.quota strong').inner_text().startswith(str(full))
 assert page.locator('.exchange select').count()==0
 # Hold an old account's periodic refresh until after logging in as a different user.
 held=[]
 def intercept(route):
  if not held:
   response=route.fetch();held.append((route,response))
  else:route.continue_()
 page.route('**/api/me',intercept)
 page.wait_for_timeout(2500);assert held
 page.get_by_role('button',name='退出',exact=True).click();page.get_by_label('用户名',exact=True).fill(username);page.get_by_label('密码',exact=True).fill('test12345');page.get_by_role('button',name='登录账户').click();page.get_by_role('heading',name='兑换消费红包',exact=True).wait_for()
 assert page.locator('.quota strong').inner_text().startswith('0')
 held[0][0].fulfill(response=held[0][1]);page.wait_for_timeout(300)
 assert page.locator('.quota strong').inner_text().startswith('0') and page.locator('.quota-user').inner_text()==username
 page.get_by_label('兑换金币数量').fill('100');page.get_by_role('button',name='确认兑换').click();page.get_by_text('兑换成功',exact=True).first.wait_for(timeout=15000)
 assert page.locator('.quota strong').inner_text().startswith('1')
 data=ctx.request.get(base+'/api/me').json();assert data['todayCount']==1 and data['orders'][0]['mode']=='success'
 page.get_by_role('button',name='Debug 接口测试').click();assert page.get_by_label('Debug 模拟场景').is_visible();page.get_by_role('button',name='关闭 Debug',exact=True).click()
 page.screenshot(path=str(ROOT/'artifacts/quota-normal-exchange.png'),full_page=True)
 assert not errors,errors
 browser.close();print('PASS per-user quota, delayed old-account response discarded, normal form excludes simulation, normal success and Debug-only fault controls')
