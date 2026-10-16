import sys,uuid,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));import server
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome');admin=browser.new_context();base='http://localhost:8080'
 assert admin.request.post(base+'/api/login',data={'username':'demo','password':'demo12345'}).status==200
 name='packets_'+uuid.uuid4().hex[:8];other='empty_'+uuid.uuid4().hex[:8]
 for n in (name,other):assert admin.request.post(base+'/api/admin/users',data={'username':n,'password':'test12345','initialCoins':10000}).status==201
 ctx=browser.new_context(viewport={'width':1440,'height':1000});assert ctx.request.post(base+'/api/login',data={'username':name,'password':'test12345'}).status==200
 page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 def exchange(mode):
  r=ctx.request.post(base+'/api/exchanges',data={'coins':100,'requestId':uuid.uuid4().hex,'mode':mode});assert r.status==202;oid=r.json()['id']
  end=time.monotonic()+15
  while time.monotonic()<end:
   o=next(o for o in ctx.request.get(base+'/api/me').json()['orders'] if o['id']==oid)
   if o['status']!='PENDING':return o
   time.sleep(.3)
  raise AssertionError(o)
 expired=exchange('success');valid=exchange('success');failed=exchange('failure')
 with server.conn() as c:c.execute('UPDATE exchanges SET expires=? WHERE id=?',(int(time.time())-10,expired['id']))
 page.goto(base);page.get_by_role('heading',name='我的红包',exact=True).wait_for();section=page.get_by_role('region',name='我的红包')
 assert section.locator('.voucher').count()==1
 assert section.get_by_text('有效 1 个 · 合计 ¥0.01',exact=True).is_visible()
 section.get_by_text('查看红包与兑换编号',exact=True).click();assert valid['packet_id'] in section.inner_text()
 section.get_by_role('button',name='已过期').click();assert section.locator('.voucher-expired').count()==1
 section.get_by_role('button',name='全部').click();assert section.locator('.voucher').count()==2
 assert failed['id'] not in section.inner_text()
 section.get_by_role('button',name='有效红包').click()
 page.get_by_role('link',name='查看我的红包').click();assert page.url.endswith('#my-redpackets')
 page.screenshot(path=str(ROOT/'artifacts/my-redpackets.png'),full_page=True)
 # A newly settled packet appears from the existing 2s account polling.
 new=exchange('success');page.wait_for_function("document.querySelectorAll('#my-redpackets .voucher').length===2",timeout=10000)
 assert not errors,errors
 empty=browser.new_context();assert empty.request.post(base+'/api/login',data={'username':other,'password':'test12345'}).status==200
 ep=empty.new_page();ep.goto(base);es=ep.get_by_role('region',name='我的红包');es.get_by_text('暂无有效红包，兑换金币领取第一份消费红包。',exact=True).wait_for();assert es.locator('.voucher').count()==0
 assert ctx.request.get(base+'/api/me').json()['serverTime']>0
 assert empty.request.get(base+'/api/me').json()['orders']==[]
 browser.close();print('PASS redpacket list: active/expired/all, amount and IDs, failed exclusion, anchor, automatic refresh, empty state and cross-user isolation; zero JS errors')
