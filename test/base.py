import lovebeat
import unittest


class LovebeatCoreBase(unittest.TestCase):
    def setUp(self):
        lovebeat.app.config['TESTING'] = True
        self.app = lovebeat.app.test_client()


class LovebeatBase(LovebeatCoreBase):
    def setUp(self):
        super(LovebeatBase, self).setUp()
        self.set_ts(0)
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
