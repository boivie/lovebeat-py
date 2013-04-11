import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class AlertTests(LovebeatBase):
    def test_alert_num(self):
        md1 = MultiDict([('heartbeat', 'warning:20'),
                         ('heartbeat', 'error:30')])
        md2 = MultiDict([('heartbeat', 'warning:25'),
                         ('heartbeat', 'error:35')])
        self.app.post('/s/test.one', data=md1)
        self.app.post('/s/test.two', data=md2)

        def expect_alert(sid, status, alert_id):
            s = self.get_json(sid)['state']
            self.assertEquals(s['status'], status)
            self.assertEquals(s['seq_id'], alert_id)

        expect_alert('test.one', 'ok', 0)
        expect_alert('test.two', 'ok', 0)

        self.set_ts(20)
        expect_alert('test.one', 'warning', 1)
        expect_alert('test.two', 'ok', 0)

        self.set_ts(30)
        expect_alert('test.one', 'error', 1)
        expect_alert('test.two', 'warning', 1)

        self.set_ts(40)
        self.app.post('/s/test.one', data=md1)
        expect_alert('test.one', 'ok', 1)
        expect_alert('test.two', 'error', 1)

        self.set_ts(60)
        expect_alert('test.one', 'warning', 2)
        expect_alert('test.two', 'error', 1)

        self.set_ts(100)
        self.app.post('/s/test.one', data=md1)
        expect_alert('test.one', 'ok', 2)

        self.app.post('/s/test.one/maint', data=dict(type='soft', expiry=50))
        expect_alert('test.one', 'maint', 2)

        self.set_ts(151)
        expect_alert('test.one', 'error', 3)


if __name__ == '__main__':
    unittest.main()
