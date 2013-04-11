import json
import os
import unittest

import lovebeat


class LovebeatCoreBase(unittest.TestCase):
    def setUp(self):
        lovebeat.app.config['TESTING'] = True
        self.app = lovebeat.app.test_client()


class LovebeatBase(LovebeatCoreBase):
    def setUp(self):
        super(LovebeatBase, self).setUp()
        self.set_ts(0)
        if os.environ.get('TRAVIS') == 'true':
            lovebeat.use_test_db(6379)
        else:
            lovebeat.use_test_db(16379)

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

    def get_config(self, service):
        j = self.get_json(service)
        return j['config']

    def get_json(self, service):
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        for s in obj['services']:
            if s['id'] == service:
                return s
        assert False
