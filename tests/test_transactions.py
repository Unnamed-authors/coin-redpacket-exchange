import unittest,tempfile,sys,uuid,time,sqlite3,concurrent.futures,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
class Transactions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();server.DB=self.tmp.name+'/app.db';server.init()
    def tearDown(self):self.tmp.cleanup()
    def order(self):
        oid=uuid.uuid4().hex;now=int(time.time())
        with server.conn() as c:
            c.execute('UPDATE users SET available=available-100,frozen=frozen+100')
            c.execute("INSERT INTO exchanges(id,user_id,idem,coins,amount,status,mode,day,created,updated) VALUES(?,'demo',?,100,1,'PENDING','success','2026-10-16',?,?)",(oid,oid,now,now))
            c.execute("INSERT INTO ledger(exchange_id,kind,coins,created) VALUES(?,'FREEZE',100,?)",(oid,now))
        return oid
    def user(self):
        with server.conn() as c:return dict(c.execute('SELECT * FROM users').fetchone())
    def test_concurrent_success_settles_once(self):
        oid=self.order();result={'code':0,'data':{'redpacketId':'p1','issuedAt':int(time.time())}}
        with concurrent.futures.ThreadPoolExecutor(12) as ex:list(ex.map(lambda _:server.settle(oid,result),range(30)))
        self.assertEqual(self.user()['frozen'],0);self.assertEqual(self.user()['available'],1999900)
        with server.conn() as c:self.assertEqual(c.execute("SELECT count(*) FROM ledger WHERE kind='DEBIT'").fetchone()[0],1)
        server.settle(oid,{'code':1001});self.assertEqual(self.user()['available'],1999900)
    def test_concurrent_failure_releases_once(self):
        oid=self.order()
        with concurrent.futures.ThreadPoolExecutor(12) as ex:list(ex.map(lambda _:server.settle(oid,{'code':1001}),range(30)))
        self.assertEqual(self.user()['available'],2000000);self.assertEqual(self.user()['frozen'],0)
    def test_unknown_never_releases(self):
        oid=self.order()
        for r in [{'code':404},{'code':503},{'code':102},{'code':999}]:server.settle(oid,r)
        self.assertEqual(self.user()['frozen'],100)
        with self.assertRaises(ValueError):server.settle(oid,{'code':0,'data':{}})
        self.assertEqual(self.user()['frozen'],100)
    def test_quota_reset_preserves_orders_and_funds(self):
        self.order();before=self.user()
        with server.conn() as c:
            self.assertEqual(server.daily_count(c,'demo','2026-10-16'),1)
            cutoff=c.execute('SELECT max(rowid) FROM exchanges').fetchone()[0]
            c.execute('INSERT INTO quota_resets VALUES(?,?,?,?)',('demo','2026-10-16',cutoff,int(time.time())))
        with server.conn() as c:
            self.assertEqual(server.daily_count(c,'demo','2026-10-16'),0)
            self.assertEqual(c.execute('SELECT count(*) FROM exchanges').fetchone()[0],1)
            self.assertEqual(server.daily_count(c,'other','2026-10-16'),0)
        self.assertEqual(self.user(),before)
        self.order()
        with server.conn() as c:self.assertEqual(server.daily_count(c,'demo','2026-10-16'),1)

    def test_db_constraints(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with server.conn() as c:c.execute('UPDATE users SET available=-1')
if __name__=='__main__':unittest.main(verbosity=2)
