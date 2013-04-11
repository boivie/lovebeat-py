import unittest
from base import LovebeatBase
from werkzeug.datastructures import MultiDict


class StatusTests(LovebeatBase):
    def test_index(self):
        md1 = MultiDict([('heartbeat', 'warning:20'),
                         ('heartbeat', 'error:30')])
        md2 = MultiDict([('heartbeat', 'warning:25'),
                         ('heartbeat', 'error:35')])
        md3 = MultiDict([('heartbeat', 'warning:100')])
        self.app.post('/s/test.one', data=md1)
        self.app.post('/s/test.two', data=md2)
        self.app.post('/s/test.three', data=md3)

        #              error,  warn, maint, "expected"
        self.setExpect(False, False, False, "up+flawless")
        self.setExpect(False, False,  True, "up")
        self.setExpect(False, True,  False, "down+warning")
        self.setExpect(False, True,   True, "down+warning")
        self.setExpect(True,  False, False, "down+error")
        self.setExpect(True,  False,  True, "down+error")
        self.setExpect(True,  True,  False, "down+error")
        self.setExpect(True,  True,   True, "down+error")

    def setExpect(self, errors, warnings, maints, text):
        if not errors and not warnings:
            self.set_ts(0)
        elif not errors and warnings:
            self.set_ts(20)
        elif errors and not warnings:
            self.set_ts(35)
        elif errors and warnings:
            self.set_ts(30)

        if maints:
            self.app.post('/s/test.three/maint')
        else:
            self.app.post('/s/test.three/unmaint')
        rv = self.app.get('/dashboard/all/status')
        self.assertEquals(rv.data, text)


if __name__ == '__main__':
    unittest.main()
