import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class SimpleTests(LovebeatBase):
    def test_default_maint1(self):
        md = MultiDict([('heartbeat', 'warning:500'),
                        ('heartbeat', 'error:1000')])
        self.app.post('/s/test.one', data=md)

        # should default to soft, 10 minutes
        self.set_ts(10)
        self.dbtrace('before')
        self.app.post('/s/test.one/maint')
        self.dbtrace('after')
        self.expect('test.one', 'MAINT')

        self.set_ts(10 + 10 * 60)
        self.expect('test.one', 'MAINT')

        self.set_ts(10 + 10 * 60 + 1)
        self.expect('test.one', 'WARN')

    def test_default_maint2(self):
        md = MultiDict([('heartbeat', 'warning:500'),
                        ('heartbeat', 'error:1000')])
        self.app.post('/s/test.one', data=md)

        # should default to soft, 10 minutes
        self.set_ts(10)
        self.app.post('/s/test.one/maint')
        self.expect('test.one', 'MAINT')

        self.set_ts(10 + 10 * 60)
        self.expect('test.one', 'MAINT')

        self.app.post('/s/test.one')
        self.expect('test.one', 'OK')

    def test_soft_maint1(self):
        md = MultiDict([('heartbeat', 'error:15')])
        self.app.post('/s/test.one', data=md)

        self.set_ts(10)
        self.app.post('/s/test.one/maint', data=dict(type='soft', expiry=20))
        self.expect('test.one', 'MAINT')
        self.expect('test.one', 'MAINT', 10 + 20)
        self.expect('test.one', 'ERROR', 10 + 20 + 1)

    def test_soft_maint2(self):
        md = MultiDict([('heartbeat', 'error:15')])
        self.app.post('/s/test.one', data=md)

        self.set_ts(10)
        self.app.post('/s/test.one/maint', data=dict(type='soft', expiry=20))
        self.expect('test.one', 'MAINT')

        self.set_ts(20)
        self.app.post('/s/test.one')
        self.expect('test.one', 'OK')
        self.expect('test.one', 'OK', 20 + 15 - 1)
        self.expect('test.one', 'ERROR', 20 + 15)

    def test_hard_maint1(self):
        md = MultiDict([('heartbeat', 'error:15')])
        self.app.post('/s/test.one', data=md)

        self.set_ts(10)
        self.app.post('/s/test.one/maint', data=dict(type='hard', expiry=20))
        self.expect('test.one', 'MAINT')
        self.expect('test.one', 'MAINT', 10 + 20)
        self.expect('test.one', 'ERROR', 10 + 20 + 1)

    def test_hard_maint2(self):
        md = MultiDict([('heartbeat', 'error:15')])
        self.app.post('/s/test.one', data=md)

        self.set_ts(10)
        self.app.post('/s/test.one/maint', data=dict(type='hard', expiry=20))
        self.expect('test.one', 'MAINT')

        self.set_ts(20)
        # this will not 'unmaint' it, but it will still register heartbeat
        self.app.post('/s/test.one')
        self.expect('test.one', 'MAINT')
        self.expect('test.one', 'MAINT', 10 + 20)
        self.expect('test.one', 'OK', 10 + 20 + 1)
        self.expect('test.one', 'ERROR', 20 + 15)


if __name__ == '__main__':
    unittest.main()
