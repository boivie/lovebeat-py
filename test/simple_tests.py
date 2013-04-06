import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class SimpleTests(LovebeatBase):
    def test_empty_db(self):
        rv = self.app.get('/dashboard/all/raw')
        assert 'all good' in rv.data

    def test_simple_up(self):
        self.app.post('/s/test.one')
        rv = self.app.get('/dashboard/all/raw')
        assert '[OK] test.one' in rv.data

    def test_simple_up_ui(self):
        self.app.post('/s/test.one')
        rv = self.app.get('/dashboard/all/')
        assert 'test.one' in rv.data

    def test_form_error(self):
        self.app.post('/s/test.one', data=dict(heartbeat=30))
        self.expect('test.one', 'OK', 0)
        self.expect('test.one', 'OK', 29)
        self.expect('test.one', 'ERROR', 30)
        self.expect('test.one', 'ERROR', 31)

    def test_form_warning(self):
        self.app.post('/s/test.one', data=dict(heartbeat="warning:20"))
        self.expect('test.one', 'OK', 0)
        self.expect('test.one', 'OK', 19)
        self.expect('test.one', 'WARN', 20)
        self.expect('test.one', 'WARN', 10000)

    def test_form_mixed(self):
        md = MultiDict([('heartbeat', 'warning:20'),
                        ('heartbeat', 'error:30')])
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK', 0)
        self.expect('test.one', 'OK', 19)
        self.expect('test.one', 'WARN', 20)
        self.expect('test.one', 'WARN', 29)
        self.expect('test.one', 'ERROR', 30)
        self.expect('test.one', 'ERROR', 10000)

    def test_beating(self):
        md = MultiDict([('heartbeat', 'warning:20'),
                        ('heartbeat', 'error:30')])
        # initial with settings
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK')

        self.set_ts(10)
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK')

        self.set_ts(20)
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK')

        self.set_ts(30)
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK')

        self.expect('test.one', 'OK', 49)
        self.expect('test.one', 'WARN', 50)
        self.expect('test.one', 'WARN', 59)
        self.expect('test.one', 'ERROR', 60)
        self.expect('test.one', 'ERROR', 10000)

    def test_recovering(self):
        md = MultiDict([('heartbeat', 'warning:20'),
                        ('heartbeat', 'error:40')])
        # initial with settings
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK')

        self.set_ts(20)
        self.expect('test.one', 'WARN')

        self.set_ts(30)
        self.app.post('/s/test.one', data=md)
        self.expect('test.one', 'OK', 40)

if __name__ == '__main__':
    unittest.main()
