import sys,json,uuid,time,urllib.request,urllib.error,http.cookiejar
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));import server
class Client:
 def __init__(self):self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
 def req(self,path,b=None):
  r=urllib.request.Request('http://localhost:8080/api/'+path,data=json.dumps(b).encode() if b is not None else None,headers={'Content-Type':'application/json'})
  try:
   with self.opener.open(r,timeout=5) as x:return x.status,json.load(x)
  except urllib.error.HTTPError as e:return e.code,json.load(e)
 def login(self,name,pw='test12345'):return self.req('login',{'username':name,'password':pw})
admin=Client();assert admin.login('demo','demo12345')[0]==200
suffix=uuid.uuid4().hex[:8];names=['multi_a_'+suffix,'multi_b_'+suffix];ids=[]
for n in names:
 status,u=admin.req('admin/users',{'username':n,'password':'test12345','initialCoins':1000});assert status==201;ids.append(u['id'])
assert admin.req('admin/users',{'username':names[0],'password':'test12345','initialCoins':1000})[0]==409
assert admin.req('admin/users',{'username':'bad name','password':'test12345','initialCoins':1000})[0]==400
assert admin.req('admin/users/update',{'id':'demo','enabled':False})[0]==409
_,listing=admin.req('admin/users');assert not any('password' in u for u in listing['users'])
a,b=Client(),Client();assert a.login(names[0])[0]==200 and b.login(names[1])[0]==200
assert a.req('admin/users')[0]==403 and a.req('admin/users/update',{'id':ids[1],'enabled':False})[0]==403
key=uuid.uuid4().hex
_,ao=a.req('exchanges',{'coins':100,'requestId':key,'mode':'timeout_success'})
_,bo=b.req('exchanges',{'coins':100,'requestId':key,'mode':'success'})
assert ao['id']!=bo['id']
time.sleep(3)
assert a.req('me')[1]['frozen']==100
assert b.req('me')[1]['orders'][0]['status']=='SUCCESS'
assert a.req('me')[1]['todayCount']==1 and b.req('me')[1]['todayCount']==1
assert len(a.req('me')[1]['orders'])==1 and len(b.req('me')[1]['orders'])==1
assert all(l['exchange_id']==ao['id'] for l in a.req('debug/ledger')[1]['ledger'])
# A cannot mutate B's pending operation or create/administer users.
assert a.req('admin/users',{'username':'forbidden','password':'test12345','initialCoins':1})[0]==403
assert admin.req('admin/users/update',{'id':ids[0],'enabled':False})[0]==200
assert a.req('me')[0]==401 and a.login(names[0])[0]==403
print('PASS admin creation/validation/permissions, account/order/ledger/quota/idempotency isolation, disable invalidates sessions',flush=True)
end=time.monotonic()+40
while time.monotonic()<end:
 row=next(u for u in admin.req('admin/users')[1]['users'] if u['id']==ids[0])
 if row['frozen']==0:break
 time.sleep(.5)
assert row['available']==900 and row['frozen']==0
assert admin.req('admin/users/update',{'id':ids[0],'enabled':True})[0]==200
assert a.login(names[0])[0]==200 and a.req('me')[1]['orders'][0]['status']=='SUCCESS'
assert admin.req('admin/users/update',{'id':ids[0],'password':'newpass123'})[0]==200
assert a.req('me')[0]==401 and a.login(names[0])[0]==401 and a.login(names[0],'newpass123')[0]==200
with server.conn() as c:
 events=c.execute('SELECT action,detail FROM user_events WHERE user_id=?',(ids[0],)).fetchall()
 assert {r['action'] for r in events}=={'CREATE','DISABLE','ENABLE','RESET_PASSWORD'}
 assert not any('newpass123' in r['detail'] or 'test12345' in r['detail'] for r in events)
print('PASS disabled account pending settlement, re-enable, password reset revocation and non-secret audit',flush=True)
print('ALL MULTIUSER CHECKS PASSED',flush=True)
