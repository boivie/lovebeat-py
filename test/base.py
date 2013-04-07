import lovebeat
import unittest


class LovebeatBase(unittest.TestCase):
    def setUp(self):
        lovebeat.app.config['TESTING'] = True
        self.set_ts(0)
        self.app = lovebeat.app.test_client()
        lovebeat.use_test_db()

    def dbtrace(self, tracer):
        r = lovebeat.conn()
        r.set("DBTRACE", tracer)

    def set_ts(self, ts):
        EPOCH = 1364774400
        lovebeat.app.config['TESTING_TS'] = EPOCH + ts

    def expect(self, service, status, when=None):
        if when is not None:
            self.set_ts(when)
        rv = self.app.get('/dashboard/all/raw')
        s = '[%s] %s' % (status, service)
        if not s in rv.data:
            print(rv.data)
            assert(False)

    def tearDown(self):
        pass
