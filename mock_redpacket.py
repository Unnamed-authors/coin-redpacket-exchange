"""Durable, idempotent mock. Query NOT_FOUND is never a terminal failure."""
import sqlite3,time,json,os,threading,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
DB=os.environ.get('MOCK_DB_PATH',str(Path(__file__).parent/'data/mock.db'))
def db():
    c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row; return c

def result(r):
    if int(time.time())<r['ready']: return {'code':102,'message':'processing'}
    if r['mode'] in ('failure','timeout_failure'): return {'code':1001,'message':'rejected'}
    return {'code':0,'message':'success','data':{'redpacketId':r['packet'],'issuedAt':r['ready']}}
class Handler(BaseHTTPRequestHandler):
    def reply(self,code,data):
        raw=json.dumps(data).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        if urlparse(self.path).path!='/api/v1/redpacket/query': return self.reply(404,{})
        key=parse_qs(urlparse(self.path).query).get('requestId',[''])[0]
        with db() as c:r=c.execute('SELECT * FROM packets WHERE id=?',(key,)).fetchone()
        self.reply(200,result(r) if r else {'code':404,'message':'not found'})
    def do_POST(self):
        if self.path!='/api/v1/redpacket/send':return self.reply(404,{})
        try:
            b=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            if not isinstance(b['userId'],str) or not isinstance(b['requestId'],str) or type(b['amount']) is not int or not 1<=b['amount']<=10000: return self.reply(400,{'code':400})
            mode=b.get('mode',os.environ.get('MOCK_MODE','success'))
            if mode=='http_error':return self.reply(503,{'code':503})
            if mode=='malformed':return self.reply(200,{'code':0,'data':{}})
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                r=c.execute('SELECT * FROM packets WHERE id=?',(b['requestId'],)).fetchone()
                if r and (r['user']!=b['userId'] or r['amount']!=b['amount']):return self.reply(409,{'code':409})
                if not r:
                    ready=int(time.time())+(30 if mode.startswith('timeout') else 0)
                    c.execute('INSERT INTO packets VALUES(?,?,?,?,?,?)',(b['requestId'],b['userId'],b['amount'],mode,ready,uuid.uuid4().hex))
                    r=c.execute('SELECT * FROM packets WHERE id=?',(b['requestId'],)).fetchone()
            if mode.startswith('timeout'):time.sleep(30)
            self.reply(200,result(r))
        except (ValueError,KeyError,TypeError):self.reply(400,{'code':400})
if __name__=='__main__':
    Path(DB).parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS packets(id TEXT PRIMARY KEY,user TEXT NOT NULL,amount INTEGER NOT NULL,mode TEXT NOT NULL,ready INTEGER NOT NULL,packet TEXT NOT NULL UNIQUE)')
    print('Mock: http://127.0.0.1:8081',flush=True)
    ThreadingHTTPServer(('127.0.0.1',int(os.environ.get('MOCK_PORT','8081'))),Handler).serve_forever()
