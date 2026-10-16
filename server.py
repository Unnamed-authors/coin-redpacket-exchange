"""Local exchange service. All money values are integer cents."""
import os, sqlite3, time, json, uuid, secrets, hashlib, hmac, threading, urllib.request, urllib.error, re
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).parent
DB=os.environ.get('DB_PATH',str(ROOT/'data/app.db'))
MOCK=os.environ.get('REDPACKET_URL','http://127.0.0.1:8081')
MODES={'success','failure','timeout_success','timeout_failure','unavailable','http_error','malformed'}
def conn():
    c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON'); return c

def daily_count(c,user_id,day):
    return c.execute('SELECT count(*) FROM exchanges WHERE user_id=? AND day=? AND rowid>COALESCE((SELECT last_order_rowid FROM quota_resets WHERE user_id=? AND day=?),0)',(user_id,day,user_id,day)).fetchone()[0]

def password(raw,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',raw.encode(),salt.encode(),200000).hex()

def init():
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with conn() as c:
        c.executescript((ROOT/'schema.sql').read_text())
        c.execute('INSERT OR IGNORE INTO users VALUES(?,?,?,?,?)',('demo','demo',password('demo12345'),2000000,0))
        c.execute("INSERT OR IGNORE INTO user_settings VALUES('demo','ADMIN',1,?)",(int(time.time()),))

def remote(path,body=None,base=None):
    req=urllib.request.Request((base or MOCK)+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=2) as r: return json.load(r)

def settle(oid,result):
    # Only authoritative, validated terminal outcomes can move frozen funds.
    if type(result.get('code')) is not int: raise ValueError('invalid result code')
    with conn() as c:
        c.execute('BEGIN IMMEDIATE')
        o=c.execute('SELECT * FROM exchanges WHERE id=?',(oid,)).fetchone()
        if not o or o['status']!='PENDING': return
        if result.get('code')==0:
            d=result.get('data',{})
            if not isinstance(d.get('redpacketId'),str) or not d['redpacketId'] or type(d.get('issuedAt')) is not int: raise ValueError('invalid success receipt')
            c.execute('UPDATE users SET frozen=frozen-? WHERE id=?',(o['coins'],o['user_id']))
            c.execute("UPDATE exchanges SET status='SUCCESS',packet_id=?,expires=?,updated=?,error=NULL WHERE id=?",(d['redpacketId'],d['issuedAt']+7*86400,int(time.time()),oid))
            kind='DEBIT'
        elif result.get('code')==1001:
            c.execute('UPDATE users SET frozen=frozen-?,available=available+? WHERE id=?',(o['coins'],o['coins'],o['user_id']))
            c.execute("UPDATE exchanges SET status='FAILED',updated=?,error='红包服务确认拒绝发放' WHERE id=?",(int(time.time()),oid)); kind='RELEASE'
        else: return
        c.execute('INSERT INTO ledger(exchange_id,kind,coins,created) VALUES(?,?,?,?)',(oid,kind,o['coins'],int(time.time())))

def process(o):
    base='http://127.0.0.1:1' if o['mode']=='unavailable' and not o['recovered'] else MOCK
    try:
        result=remote('/api/v1/redpacket/query?requestId='+o['id'],base=base)
        if result.get('code')==404:
            result=remote('/api/v1/redpacket/send',{'userId':o['user_id'],'amount':o['amount'],'requestId':o['id'],'mode':'success' if o['recovered'] else o['mode']},base)
        settle(o['id'],result)
        error='等待下游确认，金币保持冻结' if result.get('code') not in (0,1001) else None
    except Exception as e:
        error='下游结果未知：'+type(e).__name__
    with conn() as c:
        c.execute('UPDATE exchanges SET attempts=attempts+1 WHERE id=?',(o['id'],))
        c.execute("UPDATE exchanges SET next_attempt=?,error=? WHERE id=? AND status='PENDING'",(int(time.time())+3,error,o['id']))

def worker():
    while True:
        try:
            with conn() as c: orders=c.execute("SELECT * FROM exchanges WHERE status='PENDING' AND next_attempt<=? ORDER BY created LIMIT 20",(int(time.time()),)).fetchall()
            for o in orders: process(o)
        except Exception as e: print('worker:',repr(e),flush=True)
        time.sleep(.5)

class Handler(BaseHTTPRequestHandler):
    def reply(self,code,data,cookie=None):
        raw=json.dumps(data,ensure_ascii=False).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Cache-Control','no-store')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def user(self):
        cookie=SimpleCookie(self.headers.get('Cookie','')); token=cookie.get('session')
        with conn() as c: return c.execute("SELECT u.*,COALESCE(p.role,'USER') AS role FROM users u JOIN sessions s ON u.id=s.user_id LEFT JOIN user_settings p ON p.user_id=u.id WHERE s.token=? AND s.expires>? AND COALESCE(p.enabled,1)=1",(token.value if token else '',int(time.time()))).fetchone()
    def do_GET(self):
        if self.path=='/docs/api':
            raw=(ROOT/'API.md').read_bytes(); self.send_response(200)
            self.send_header('Content-Type','text/plain; charset=utf-8'); self.send_header('Content-Length',str(len(raw)))
            self.end_headers(); self.wfile.write(raw); return
        if self.path=='/api/health': return self.reply(200,{'ok':True})
        if self.path.startswith('/api/'):
            if self.path not in ('/api/me','/api/debug/ledger','/api/admin/users'): return self.reply(404,{'error':'接口不存在'})
            u=self.user()
            if not u: return self.reply(401,{'error':'请先登录'})
            if self.path=='/api/admin/users':
                if u['role']!='ADMIN': return self.reply(403,{'error':'需要管理员权限'})
                with conn() as c:
                    rows=[dict(r) for r in c.execute("SELECT u.id,u.username,u.available,u.frozen,COALESCE(p.role,'USER') AS role,COALESCE(p.enabled,1) AS enabled,COALESCE(p.created,0) AS created,(SELECT count(*) FROM exchanges e WHERE e.user_id=u.id) AS orderCount FROM users u LEFT JOIN user_settings p ON p.user_id=u.id ORDER BY COALESCE(p.created,0) DESC,u.username")]
                return self.reply(200,{'users':rows})
            if self.path=='/api/debug/ledger':
                with conn() as c:
                    rows=[dict(r) for r in c.execute('SELECT l.* FROM ledger l JOIN exchanges e ON e.id=l.exchange_id WHERE e.user_id=? ORDER BY l.id DESC LIMIT 100',(u['id'],))]
                return self.reply(200,{'ledger':rows})
            day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
            with conn() as c:
                c.execute('BEGIN')
                u=c.execute("SELECT u.*,COALESCE(p.role,'USER') AS role FROM users u LEFT JOIN user_settings p ON p.user_id=u.id WHERE u.id=?",(u['id'],)).fetchone()
                orders=[dict(r) for r in c.execute('SELECT * FROM exchanges WHERE user_id=? ORDER BY created DESC,rowid DESC',(u['id'],))]
                count=daily_count(c,u['id'],day)
            now=int(time.time()); day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
            return self.reply(200,{'serverTime':now,'username':u['username'],'role':u['role'],'available':u['available'],'frozen':u['frozen'],'redpacketBalance':sum(o['amount'] for o in orders if o['status']=='SUCCESS' and o['expires']>now),'todayCount':count,'orders':orders})
        file=(ROOT/'frontend/dist'/self.path.split('?')[0].lstrip('/')).resolve()
        if not file.is_relative_to((ROOT/'frontend/dist').resolve()): return self.reply(404,{'error':'文件不存在'})
        if not file.is_file(): file=ROOT/'frontend/dist/index.html'
        if not file.exists(): return self.reply(503,{'error':'请先构建前端'})
        import mimetypes
        raw=file.read_bytes(); self.send_response(200); self.send_header('Content-Type',mimetypes.guess_type(file)[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if origin and origin not in ('http://localhost:8080','http://127.0.0.1:8080'): return self.reply(403,{'error':'来源不允许'})
            if self.headers.get('Content-Type','').split(';')[0]!='application/json': return self.reply(415,{'error':'需要 JSON'})
            n=int(self.headers.get('Content-Length','0'))
            if n>4096: return self.reply(413,{'error':'请求过大'})
            b=json.loads(self.rfile.read(n))
            if not isinstance(b,dict): return self.reply(400,{'error':'请求体必须为 JSON 对象'})
            if self.path=='/api/login':
                with conn() as c:
                    u=c.execute('SELECT * FROM users WHERE username=?',(b.get('username'),)).fetchone()
                    if not u or not hmac.compare_digest(password(str(b.get('password','')),u['password'].split(':')[0]),u['password']): return self.reply(401,{'error':'用户名或密码错误'})
                    settings=c.execute('SELECT enabled FROM user_settings WHERE user_id=?',(u['id'],)).fetchone()
                    if settings and not settings['enabled']: return self.reply(403,{'error':'账户已停用，请联系管理员'})
                    token=secrets.token_urlsafe(32); c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,u['id'],int(time.time())+86400))
                return self.reply(200,{'ok':True},f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400')
            u=self.user()
            if not u: return self.reply(401,{'error':'请先登录'})
            if self.path.startswith('/api/admin/'):
                if u['role']!='ADMIN': return self.reply(403,{'error':'需要管理员权限'})
                now=int(time.time())
                if self.path=='/api/admin/users':
                    username=b.get('username'); raw=b.get('password'); initial=b.get('initialCoins',0)
                    if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_]{3,32}',username) or not isinstance(raw,str) or not 8<=len(raw)<=128 or type(initial) is not int or not 0<=initial<=100000000:
                        return self.reply(400,{'error':'用户名须为 3～32 位字母、数字、下划线；密码 8～128 位；初始金币为 0～100000000 的整数'})
                    hashed=password(raw); uid=uuid.uuid4().hex
                    with conn() as c:
                        c.execute('BEGIN IMMEDIATE')
                        if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone(): return self.reply(409,{'error':'用户名已存在'})
                        c.execute('INSERT INTO users VALUES(?,?,?,?,0)',(uid,username,hashed,initial))
                        c.execute("INSERT INTO user_settings VALUES(?,'USER',1,?)",(uid,now))
                        c.execute('INSERT INTO user_events(actor_id,user_id,action,detail,created) VALUES(?,?,?,?,?)',(u['id'],uid,'CREATE',json.dumps({'initialCoins':initial}),now))
                    return self.reply(201,{'id':uid,'username':username,'role':'USER','enabled':1,'available':initial,'frozen':0})
                if self.path=='/api/admin/users/update':
                    uid=b.get('id'); enabled=b.get('enabled'); raw=b.get('password')
                    if not isinstance(uid,str) or ('enabled' not in b and 'password' not in b) or ('enabled' in b and type(enabled) is not bool) or ('password' in b and (not isinstance(raw,str) or not 8<=len(raw)<=128)):
                        return self.reply(400,{'error':'需要用户 id、布尔 enabled 或 8～128 位新密码'})
                    if uid==u['id'] and enabled is False: return self.reply(409,{'error':'不能停用当前管理员'})
                    hashed=password(raw) if raw is not None else None
                    with conn() as c:
                        c.execute('BEGIN IMMEDIATE')
                        if not c.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone(): return self.reply(404,{'error':'用户不存在'})
                        c.execute("INSERT OR IGNORE INTO user_settings VALUES(?,'USER',1,?)",(uid,now))
                        if 'enabled' in b:
                            c.execute('UPDATE user_settings SET enabled=? WHERE user_id=?',(int(enabled),uid))
                            c.execute('INSERT INTO user_events(actor_id,user_id,action,detail,created) VALUES(?,?,?,?,?)',(u['id'],uid,'ENABLE' if enabled else 'DISABLE','{}',now))
                        if hashed:
                            c.execute('UPDATE users SET password=? WHERE id=?',(hashed,uid))
                            c.execute('INSERT INTO user_events(actor_id,user_id,action,detail,created) VALUES(?,?,?,?,?)',(u['id'],uid,'RESET_PASSWORD','{}',now))
                        if enabled is False or hashed: c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
                    return self.reply(200,{'ok':True})
                return self.reply(404,{'error':'接口不存在'})
            if self.path=='/api/debug/downstream':
                operation=b.get('operation'); key=b.get('requestId'); mode=b.get('mode','success'); amount=b.get('amount',1)
                if operation not in ('send','query') or not isinstance(key,str) or not 8<=len(key)<=100 or mode not in MODES or type(amount) is not int or not 1<=amount<=10000:
                    return self.reply(400,{'error':'operation、requestId、amount 或 mode 无效'})
                # Debug calls cannot collide with real exchange IDs or another user's calls.
                downstream_id='debug-'+u['id']+'-'+hashlib.sha256(key.encode()).hexdigest()
                base='http://127.0.0.1:1' if mode=='unavailable' else MOCK
                started=time.monotonic()
                try:
                    result=remote('/api/v1/redpacket/query?requestId='+downstream_id,base=base) if operation=='query' else remote('/api/v1/redpacket/send',{'userId':u['id'],'amount':amount,'requestId':downstream_id,'mode':mode},base)
                    return self.reply(200,{'requestId':downstream_id,'elapsedMs':round((time.monotonic()-started)*1000),'result':result,'isolated':True})
                except urllib.error.HTTPError as e:
                    return self.reply(502,{'requestId':downstream_id,'elapsedMs':round((time.monotonic()-started)*1000),'error':'下游 HTTP '+str(e.code),'outcome':'UNKNOWN','isolated':True})
                except Exception as e:
                    return self.reply(504 if isinstance(e,TimeoutError) else 502,{'requestId':downstream_id,'elapsedMs':round((time.monotonic()-started)*1000),'error':type(e).__name__,'outcome':'UNKNOWN','isolated':True})
            if self.path=='/api/logout':
                cookie=SimpleCookie(self.headers.get('Cookie',''))
                with conn() as c: c.execute('DELETE FROM sessions WHERE token=?',(cookie['session'].value,))
                return self.reply(200,{'ok':True},'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if self.path=='/api/recover':
                with conn() as c:
                    c.execute("UPDATE exchanges SET recovered=1,next_attempt=0 WHERE id=? AND user_id=? AND status='PENDING' AND mode IN ('unavailable','http_error','malformed')",(b.get('id'),u['id']))
                return self.reply(200,{'ok':True})
            if self.path!='/api/exchanges': return self.reply(404,{'error':'接口不存在'})
            coins=b.get('coins'); key=b.get('requestId'); mode=b.get('mode','success')
            if type(coins) is not int or coins<100 or coins>1000000 or coins%100: return self.reply(400,{'error':'请输入 100～1,000,000 之间的 100 整数倍金币'})
            if not isinstance(key,str) or not 8<=len(key)<=100 or mode not in MODES: return self.reply(400,{'error':'请求编号或模拟场景无效'})
            now=int(time.time()); day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
            with conn() as c:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT * FROM exchanges WHERE user_id=? AND idem=?',(u['id'],key)).fetchone()
                if old:
                    if old['coins']!=coins or old['mode']!=mode: return self.reply(409,{'error':'同一请求编号的参数不可更改'})
                    return self.reply(200,dict(old))
                count=daily_count(c,u['id'],day)
                if count>=10: return self.reply(400,{'error':'今日兑换次数已达 10 次（含失败与处理中）'})
                if c.execute('UPDATE users SET available=available-?,frozen=frozen+? WHERE id=? AND available>=?',(coins,coins,u['id'],coins)).rowcount!=1: return self.reply(400,{'error':'可用金币不足'})
                oid=uuid.uuid4().hex
                c.execute('INSERT INTO exchanges(id,user_id,idem,coins,amount,status,mode,day,created,updated) VALUES(?,?,?,?,?,?,?,?,?,?)',(oid,u['id'],key,coins,coins//100,'PENDING',mode,day,now,now))
                c.execute('INSERT INTO ledger(exchange_id,kind,coins,created) VALUES(?,?,?,?)',(oid,'FREEZE',coins,now))
            return self.reply(202,{'id':oid,'status':'PENDING'})
        except (ValueError,TypeError,KeyError): self.reply(400,{'error':'请求格式错误'})
        except Exception as e:
            print(repr(e),flush=True); self.reply(500,{'error':'服务异常，请使用原请求编号重试'})

if __name__=='__main__':
    init(); threading.Thread(target=worker,daemon=True).start()
    print('Exchange: http://localhost:8080',flush=True)
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
