import subprocess,tempfile,os,time,json,urllib.request,http.cookiejar,uuid,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    env={**os.environ,'DB_PATH':td+'/app.db','MOCK_DB_PATH':td+'/mock.db','PORT':'28080','MOCK_PORT':'28081','REDPACKET_URL':'http://127.0.0.1:28081'}
    procs=[]
    def start(file):
        p=subprocess.Popen(['python3',str(ROOT/file)],env=env,stdout=subprocess.DEVNULL,stderr=None);procs.append(p);time.sleep(.6);assert p.poll() is None;return p
    cj=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    def req(path,body=None):
        r=urllib.request.Request('http://127.0.0.1:28080/api/'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with client.open(r,timeout=5) as res:return json.load(res)
    try:
        mock=start('mock_redpacket.py');app=start('server.py')
        req('login',{'username':'demo','password':'demo12345'})
        o=req('exchanges',{'coins':10000,'mode':'timeout_success','requestId':uuid.uuid4().hex})
        time.sleep(3)
        assert req('me')['frozen']==10000
        app.terminate();app.wait();mock.terminate();mock.wait()
        # Both processes are lost after downstream accepted the request but before response.
        mock=start('mock_redpacket.py');app=start('server.py')
        end=time.monotonic()+40
        while time.monotonic()<end:
            u=req('me')
            if u['orders'][0]['status']=='SUCCESS':break
            assert u['frozen']==10000;time.sleep(.5)
        assert u['orders'][0]['status']=='SUCCESS' and u['frozen']==0 and u['available']==1990000
        with sqlite3.connect(td+'/mock.db') as c:assert c.execute('SELECT count(*) FROM packets').fetchone()[0]==1
        with sqlite3.connect(td+'/app.db') as c:assert c.execute("SELECT count(*) FROM ledger WHERE kind='DEBIT'").fetchone()[0]==1
        print('PASS both-process restart during uncertain result: persisted reservation recovered, exactly one packet and debit')
    finally:
        for p in procs:
            if p.poll() is None:p.terminate();p.wait()
