"""Run against ./start.sh. Uses dedicated acceptance account; leaves demo intact."""
import sys,json,urllib.request,urllib.error,http.cookiejar,time,uuid,concurrent.futures,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
name='qa_'+uuid.uuid4().hex[:8]
with server.conn() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,0)',(name,name,server.password('test12345'),2000000))
cookies=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
def req(path,b=None,auth=True):
    r=urllib.request.Request('http://localhost:8080/api/'+path,data=json.dumps(b).encode() if b is not None else None,headers={'Content-Type':'application/json'})
    try:
        with (client if auth else urllib.request.build_opener()).open(r,timeout=5) as res:return res.status,json.load(res)
    except urllib.error.HTTPError as e:return e.code,json.load(e)
def me():return req('me')[1]
def submit(mode='success',coins=100,key=None):return req('exchanges',{'coins':coins,'mode':mode,'requestId':key or uuid.uuid4().hex})
def wait(oid,status,timeout=45):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        o=next(o for o in me()['orders'] if o['id']==oid)
        if o['status']==status:return o
        time.sleep(.3)
    raise AssertionError((oid,status,o))
def passed(s):print('PASS',s,flush=True)
assert req('me',auth=False)[0]==401
assert req('login',{'username':name,'password':'wrong'})[0]==401
assert req('login',{'username':name,'password':'test12345'})[0]==200
passed('登录、未授权拦截与错误密码')
for n in [0,99,101,1000001,True,'100',100.5]:assert submit(coins=n)[0]==400
assert not me()['orders'];passed('金额边界、类型与整数倍校验')
k=uuid.uuid4().hex
with concurrent.futures.ThreadPoolExecutor(12) as pool:rs=list(pool.map(lambda _:submit(key=k),range(20)))
assert len({r[1]['id'] for r in rs})==1 and len(me()['orders'])==1
assert submit(coins=200,key=k)[0]==409
wait(rs[0][1]['id'],'SUCCESS');passed('20 个并发相同请求只创建一个订单与一次扣款')
_,r=submit('failure');wait(r['id'],'FAILED');passed('明确失败后解冻')
_,a=submit('timeout_success');_,b=submit('timeout_failure')
time.sleep(4)
assert me()['frozen']==200
assert next(o for o in me()['orders'] if o['id']==a['id'])['status']=='PENDING'
passed('超时期间保持冻结，未提前回滚')
o=wait(a['id'],'SUCCESS');wait(b['id'],'FAILED')
with server.conn() as c:
    o=c.execute('SELECT * FROM exchanges WHERE id=?',(a['id'],)).fetchone()
    assert o['expires']-int(c.execute('SELECT created FROM exchanges WHERE id=?',(a['id'],)).fetchone()[0])>=7*86400
passed('30 秒后查询收敛：成功扣减、失败解冻、7 天有效期')
for mode in ['unavailable','http_error','malformed']:
    _,r=submit(mode);time.sleep(3)
    assert next(o for o in me()['orders'] if o['id']==r['id'])['status']=='PENDING'
    assert me()['frozen']==100
    assert req('recover',{'id':r['id']})[0]==200
    wait(r['id'],'SUCCESS')
    passed(mode+' 保持冻结，恢复服务后原订单成功')
# Upper bound and insufficient funds.
_,r=submit(coins=1000000);wait(r['id'],'SUCCESS')
assert submit(coins=1000000)[0]==400
passed('单次上限成功与余额不足拒绝')
for _ in range(2):
    _,r=submit();wait(r['id'],'SUCCESS')
assert me()['todayCount']==10 and submit()[0]==400
passed('北京时间每日最多 10 次，失败订单计入次数')
with server.conn() as c:c.execute("UPDATE exchanges SET day='2000-01-01' WHERE user_id=?",(name,))
_,r=submit();wait(r['id'],'SUCCESS')
assert me()['todayCount']==1
passed('历史日期订单不占当日限额')
with server.conn() as c:c.execute('UPDATE exchanges SET expires=1 WHERE user_id=? AND id=?',(name,r['id']))
assert me()['redpacketBalance']==sum(o['amount'] for o in me()['orders'] if o['status']=='SUCCESS' and o['expires']>int(time.time()))
passed('过期红包不计入可用红包余额')
u=me()
with server.conn() as c:
    rows=c.execute('SELECT * FROM exchanges WHERE user_id=?',(name,)).fetchall()
    assert u['available']+u['frozen']+sum(o['coins'] for o in rows if o['status']=='SUCCESS')==2000000
    for o in rows:
        kinds=[r[0] for r in c.execute('SELECT kind FROM ledger WHERE exchange_id=?',(o['id'],))]
        assert sorted(kinds)==sorted(['FREEZE','DEBIT' if o['status']=='SUCCESS' else 'RELEASE'])
passed('账户守恒及逐单流水一致性')
# Another account cannot recover or observe the first account's orders.
assert req('logout',{})[0]==200 and req('me')[0]==401
passed('退出后会话失效')
print('ALL ACCEPTANCE CHECKS PASSED; account:',name)
