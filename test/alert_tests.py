import json
import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class AlertTests(LovebeatBase):
    def setUp(self):
        super(AlertTests, self).setUp()
        md1 = MultiDict([('heartbeat', 'warning:20'),
                         ('heartbeat', 'error:30'),
                         ('labels', 'foo,bar')])
        md2 = MultiDict([('heartbeat', 'warning:25'),
                         ('heartbeat', 'error:35'),
                         ('labels', 'foo,bar,gazonk')])
        self.app.post('/s/test.one', data=md1)
        self.app.post('/s/test.two', data=md2)

        rcpt1 = "gtalk:foo@example.com"
        rcpt2 = "email:foo@example.com"
        rcpt3 = "sms:0015551234"
        rcpt4 = "sms:0015559999"
        md = MultiDict([('alert', 'warning:' + rcpt1),
                        ('alert', 'error:' + rcpt2),
                        ('alert', 'error:' + rcpt3),
                        ('alert', 'error:' + rcpt4)])
        self.app.post('/l/foo', data=md)

    def test_alert_num(self):
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
        self.app.post('/s/test.one')
        expect_alert('test.one', 'ok', 1)
        expect_alert('test.two', 'error', 1)

        self.set_ts(60)
        expect_alert('test.one', 'warning', 2)
        expect_alert('test.two', 'error', 1)

        self.set_ts(100)
        self.app.post('/s/test.one')
        expect_alert('test.one', 'ok', 2)

        self.app.post('/s/test.one/maint', data=dict(type='soft', expiry=50))
        expect_alert('test.one', 'maint', 2)

        self.set_ts(151)
        expect_alert('test.one', 'error', 3)

    def test_set_alert_rcpts(self):
        rcpt1 = "gtalk:foo@example.com"
        rcpt2 = "email:foo@example.com"
        rcpt3 = "sms:0015551234"
        rcpt4 = "sms:0015559999"
        md = MultiDict([('alert', 'warning:' + rcpt1),
                        ('alert', 'error:' + rcpt2),
                        ('alert', 'error:' + rcpt3),
                        ('alert', 'error:' + rcpt4)])
        self.app.post('/l/foo', data=md)

        data = json.loads(self.app.get('/l/foo').data)
        self.assertEquals([rcpt1], data['alerts']['warning'])
        self.assertEquals(3, len(data['alerts']['error']))
        self.assertTrue(rcpt2 in data['alerts']['error'])
        self.assertTrue(rcpt3 in data['alerts']['error'])
        self.assertTrue(rcpt4 in data['alerts']['error'])

    def test_set_alerts_txt(self):
        alerts = self.app.get('/agent/bond/alerts.txt').data
        self.assertEquals("1\nENDFILE\n", alerts)

        self.set_ts(20)
        alerts = self.app.get('/agent/bond/alerts.txt').data
        ref = """\
1
SERVICE
test.one
ALERTID
1
TYPE
warning
TO
gtalk:foo@example.com
SUBJECT
DOWN alert: test.one is DOWN [#1]
MESSAGE
test.one is down with warning status.

Yours Sincerely
Lovebeat
EOF
ENDSERVICE
ENDFILE
"""
        self.assertEquals(ref, alerts)

        self.set_ts(30)
        alerts = self.app.get('/agent/bond/alerts.txt').data
        assert("SERVICE\ntest.one\nALERTID\n1\nTYPE\nerror\n" in alerts)
        assert("SERVICE\ntest.two\nALERTID\n1\nTYPE\nwarning\n" in alerts)

        self.app.post('/s/test.one')
        self.app.post('/s/test.two')
        alerts = self.app.get('/agent/bond/alerts.txt').data
        self.assertEquals("1\nENDFILE\n", alerts)

if __name__ == '__main__':
    unittest.main()
