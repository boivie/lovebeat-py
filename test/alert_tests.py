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

    def expect_status(self, sid, status):
        s = self.get_json(sid)['state']
        self.assertEquals(s['status'], status)

    def expect_alert(self, sid, status, alert_id, state = None, ts = None):
        s = self.get_json(sid)['state']
        self.assertEquals(s['alert']['status'], status)
        self.assertEquals(s['alert']['id'], alert_id)
        if state:
            self.assertEquals(s['alert']['state'], state)
        if ts:
            self.assertEquals(s['alert']['ts'] - self.EPOCH, ts)

    def expect_claimed(self, sid, agent):
        s = self.get_json(sid)['state']
        self.assertEquals(s['alert']['state'], 'claimed')
        self.assertEquals(s['alert']['claim']['agent'], agent)

    def claim(self, service, alert_id, status, agent):
        rv = self.app.post('/agent/%s/claim/%s/%s/%s' %
                           (agent, service, alert_id, status))
        if rv.data == 'ok':
            return True
        elif rv.data == 'already_claimed':
            return False
        self.assertFalse(True, "Bad claim return: %s" % rv.data)

    def confirm(self, service, alert_id, status, agent):
        rv = self.app.post('/agent/%s/confirm/%s/%s/%s' %
                           (agent, service, alert_id, status))
        if rv.data == 'ok':
            return True
        elif rv.data == 'already_confirmed':
            return False
        self.assertFalse(True, "Bad confirm return: %s" % rv.data)

    def test_claimed_perfect(self):
        """The perfect case - everything is claimed"""
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 0, 'confirmed', ts=0)
        self.expect_status('test.two', 'ok')
        self.expect_alert('test.two', 'ok', 0, 'confirmed', ts=0)

        self.set_ts(20)
        self.expect_status('test.one', 'warning')
        self.expect_alert('test.one', 'warning', 1, 'new', ts=20)
        self.expect_status('test.two', 'ok')
        self.expect_alert('test.two', 'ok', 0, 'confirmed', ts=0)

        self.assertTrue(self.claim('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1, 'claimed')

        self.assertTrue(self.confirm('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1, 'confirmed')

        self.set_ts(30)
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'error', 1, 'new', ts=30)
        self.expect_status('test.two', 'warning')
        self.expect_alert('test.two', 'warning', 1, 'new', ts=30)

        self.assertTrue(self.claim('test.one', 1, 'error', 'bond'))
        self.expect_alert('test.one', 'error', 1, 'claimed')

        self.assertTrue(self.confirm('test.one', 1, 'error', 'bond'))
        self.expect_alert('test.one', 'error', 1, 'confirmed')

        # Going straight from 'new' to 'confirmed' - we can do that.
        self.assertTrue(self.confirm('test.two', 1, 'warning', 'bond'))
        self.expect_alert('test.two', 'warning', 1, 'confirmed')

        self.set_ts(35)
        self.app.post('/s/test.one')

        self.set_ts(40)
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 1, 'new', ts=40)
        self.expect_status('test.two', 'error')
        self.expect_alert('test.two', 'error', 1, 'new', ts=40)

    def test_claimed_duplicates(self):
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 0, 'confirmed')

        self.set_ts(20)
        self.expect_status('test.one', 'warning')
        self.expect_alert('test.one', 'warning', 1, 'new')

        self.assertTrue(self.claim('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1)
        self.expect_claimed('test.one', 'bond')

        # Now, another agent can't claim it.
        self.assertFalse(self.claim('test.one', 1, 'warning', 'smith'))
        self.expect_claimed('test.one', 'bond')

        # but claiming it again is not an offense
        self.assertTrue(self.claim('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1)
        self.expect_claimed('test.one', 'bond')

    def test_must_confirm_before_status_change(self):
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 0, 'confirmed')

        self.set_ts(20)
        self.expect_status('test.one', 'warning')
        self.expect_alert('test.one', 'warning', 1, 'new')

        self.set_ts(30)
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'warning', 1, 'new')

        self.set_ts(40)
        self.app.post('/s/test.one')
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'warning', 1, 'new')

        # Confirming it makes the alert status update itself to the current
        self.assertTrue(self.confirm('test.one', 1, 'warning', 'bond'))
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 1, 'new')

    def test_out_of_sequence(self):
        self.expect_status('test.one', 'ok')
        self.expect_alert('test.one', 'ok', 0, 'confirmed')

        self.set_ts(20)
        self.expect_status('test.one', 'warning')
        self.expect_alert('test.one', 'warning', 1, 'new')

        self.assertTrue(self.claim('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1)
        self.expect_claimed('test.one', 'bond')

        self.assertTrue(self.confirm('test.one', 1, 'warning', 'bond'))
        self.expect_status('test.one', 'warning')
        self.expect_alert('test.one', 'warning', 1, 'confirmed')

        # now we can't claim it again - it's confirmed.
        self.assertFalse(self.claim('test.one', 1, 'warning', 'bond'))
        self.expect_alert('test.one', 'warning', 1, 'confirmed')

        self.set_ts(30)
        self.app.post('/s/test.one')
        self.expect_alert('test.one', 'ok', 1, 'new')
        self.assertTrue(self.confirm('test.one', 1, 'ok', 'bond'))

        self.set_ts(60)
        self.expect_alert('test.one', 'error', 2, 'new')

        # we can't claim no 1 again - it's now no 2!
        self.assertFalse(self.claim('test.one', 1, 'error', 'bond'))
        self.expect_alert('test.one', 'error', 2, 'new')

        # and we can't claim it as the wrong type either.
        self.assertFalse(self.claim('test.one', 2, 'warning', 'bond'))
        self.expect_alert('test.one', 'error', 2, 'new')

        # but it is claimable - with the right id and type.
        self.assertTrue(self.claim('test.one', 2, 'error', 'bond'))
        self.expect_alert('test.one', 'error', 2)
        self.expect_claimed('test.one', 'bond')

        # and confirmable...
        self.assertTrue(self.confirm('test.one', 2, 'error', 'bond'))
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'error', 2, 'confirmed')

        # ... even if we stutter and repeat ourselves.
        self.assertTrue(self.confirm('test.one', 2, 'error', 'bond'))
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'error', 2, 'confirmed')

        # but only with the right ID
        self.assertFalse(self.confirm('test.one', 3, 'error', 'bond'))
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'error', 2, 'confirmed')

        # and type
        self.assertFalse(self.confirm('test.one', 2, 'warning', 'bond'))
        self.expect_status('test.one', 'error')
        self.expect_alert('test.one', 'error', 2, 'confirmed')

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
