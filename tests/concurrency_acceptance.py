import sys,uuid,json,urllib.request,urllib.error,http.cookiejar,concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

def scenario(balance,expected):
    uid='race_'+uuid.uuid4().hex[:10]
    with server.conn() as c:c.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,uid,server.password('test12345'),balance))
    jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    def req(path,b):
        r=urllib.request.Request('http://localhost:8080/api/'+path,data=json.dumps(b).encode(),headers={'Content-Type':'application/json'})
        try:
            with client.open(r) as x:return x.status,json.load(x)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    req('login',{'username':uid,'password':'test12345'})
    with concurrent.futures.ThreadPoolExecutor(20) as pool:
        results=list(pool.map(lambda _:req('exchanges',{'coins':100,'requestId':uuid.uuid4().hex,'mode':'unavailable'}),range(20)))
    assert sum(r[0]==202 for r in results)==expected,results
    with server.conn() as c:
        u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        assert u['available']==balance-expected*100 and u['frozen']==expected*100
        assert c.execute('SELECT count(*) FROM exchanges WHERE user_id=?',(uid,)).fetchone()[0]==expected
    # Unauthorized recovery must be a no-op.
    other=next(r[1]['id'] for r in results if r[0]==202)
    req('logout',{})
    req('login',{'username':'demo','password':'demo12345'})
    req('recover',{'id':other})
    with server.conn() as c:assert c.execute('SELECT recovered FROM exchanges WHERE id=?',(other,)).fetchone()[0]==0
    # Recover test orders to avoid leaving permanent queue work.
    with server.conn() as c:c.execute('UPDATE exchanges SET recovered=1,next_attempt=0 WHERE user_id=?',(uid,))
scenario(500,5)
print('PASS 20 concurrent distinct requests cannot overspend 500 coins; cross-user recovery denied')
scenario(2000000,10)
print('PASS 20 concurrent distinct requests cannot exceed daily quota 10')
