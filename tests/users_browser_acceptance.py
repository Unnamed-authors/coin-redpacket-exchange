import uuid,json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];name='ui_'+uuid.uuid4().hex[:8]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,channel='chrome');page=browser.new_page(viewport={'width':1500,'height':1050});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto('http://localhost:8080');page.get_by_role('button',name='登录账户').click();page.get_by_role('button',name='用户管理',exact=True).click()
 panel=page.get_by_role('region',name='用户管理');panel.get_by_label('新用户名',exact=True).fill(name);panel.get_by_label('初始密码',exact=True).fill('test12345');panel.get_by_label('初始金币',exact=True).fill('5000');panel.get_by_role('button',name='创建用户',exact=True).click()
 panel.get_by_role('button',name='维护 '+name,exact=True).wait_for();panel.get_by_label('搜索用户').fill(name);panel.get_by_role('button',name='维护 '+name,exact=True).click()
 panel.get_by_role('button',name='停用账户').click();panel.get_by_role('button',name='启用账户').wait_for();panel.get_by_role('button',name='启用账户').click();panel.get_by_role('button',name='停用账户').wait_for()
 panel.get_by_label('新密码',exact=True).fill('newpass123');panel.get_by_role('button',name='重置密码',exact=True).click();panel.get_by_text('密码已重置，该用户所有会话已失效。',exact=True).wait_for()
 page.screenshot(path=str(ROOT/'artifacts/users-management.png'),full_page=True)
 page.get_by_role('button',name='退出',exact=True).click();page.get_by_label('用户名',exact=True).fill(name);page.get_by_label('密码',exact=True).fill('newpass123');page.get_by_role('button',name='登录账户').click();page.get_by_role('button',name='Debug 接口测试').wait_for()
 assert page.get_by_role('button',name='用户管理',exact=True).count()==0
 page.get_by_role('button',name='Debug 接口测试').click();debug=page.get_by_role('region',name='Debug 接口测试');payload={'coins':100,'requestId':str(uuid.uuid4()),'mode':'success'};page.get_by_label('请求 JSON').fill(json.dumps(payload))
 with page.expect_response(lambda r:r.url.endswith('/api/exchanges') and r.request.method=='POST') as response:debug.get_by_role('button',name='发送请求',exact=True).click()
 assert response.value.status==202 and response.value.json()['status']=='PENDING'
 page.wait_for_function("document.querySelector('[aria-label=\"最终业务结果\"]')?.textContent.includes('SUCCESS')",timeout=15000)
 assert 'PENDING' in page.get_by_label('接口响应',exact=True).inner_text()
 page.screenshot(path=str(ROOT/'artifacts/debug-final-result.png'),full_page=True)
 assert not errors,errors
 browser.close();print('PASS browser user create/disable/enable/password reset, regular-user login & admin isolation, 202 PENDING preserved with automatic final SUCCESS')
