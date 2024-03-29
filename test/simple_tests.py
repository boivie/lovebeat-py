import json
import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class SimpleTests(LovebeatBase):
    def test_index(self):
        rv = self.app.get('/', follow_redirects=True)
        assert '200' in rv.status
        assert '<html>' in rv.data

    def test_ui_list_labels(self):
        self.app.post('/s/test.one', data=dict(labels='one,two'))
        self.app.post('/s/test.two', data=dict(labels='two,three'))
        rv = self.app.get('/dashboard/')
        assert 'one' in rv.data
        assert 'two' in rv.data
        assert 'three' in rv.data

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

    def test_error_smaller_than_warning(self):
        md = MultiDict([('heartbeat', 'warning:20'),
                        ('heartbeat', 'error:10')])
        self.app.post('/s/test.one', data=md)
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        self.assertEquals(10,
                          obj['services'][0]['config']['heartbeat']['error'])
        assert obj['services'][0]['config']['heartbeat']['warning'] is None
        self.expect('test.one', 'OK', 0)
        self.expect('test.one', 'OK', 9)
        self.expect('test.one', 'ERROR', 10)
        self.expect('test.one', 'ERROR', 19)
        self.expect('test.one', 'ERROR', 20)
        self.expect('test.one', 'ERROR', 10000)

    def test_default_conf_is_immutable(self):
        self.app.post('/s/test.orig')
        config = self.get_config('test.orig')
        whb = config['heartbeat']['warning']
        ehb = config['heartbeat']['error']

        md = MultiDict([('heartbeat', 'warning:%d' % (whb * 2)),
                        ('heartbeat', 'error:%d' % (ehb * 3))])
        self.app.post('/s/test.extended', data=md)
        config = self.get_config('test.extended')
        self.assertEquals(whb * 2, config['heartbeat']['warning'])
        self.assertEquals(ehb * 3, config['heartbeat']['error'])

        self.app.post('/s/test.newer')
        config = self.get_config('test.newer')
        self.assertEquals(whb, config['heartbeat']['warning'])
        self.assertEquals(ehb, config['heartbeat']['error'])

    def test_delta_heartbeat(self):
        self.set_ts(15)
        self.app.post('/s/test.one')

        self.set_ts(20)
        obj = self.get_json('test.one')
        self.assertEquals(5, obj['state']['last']['delta'])

        self.set_ts(25)
        obj = self.get_json('test.one')
        self.assertEquals(10, obj['state']['last']['delta'])

        self.set_ts(1025)
        obj = self.get_json('test.one')
        self.assertEquals(1010, obj['state']['last']['delta'])


if __name__ == '__main__':
    unittest.main()
