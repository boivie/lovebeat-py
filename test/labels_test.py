import json
import unittest
from base import LovebeatBase


class LabelsTests(LovebeatBase):
    def test_no_labels(self):
        self.app.post('/s/test.no')
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['config']['labels']
        self.assertEquals([], labels)

    def test_add_labels(self):
        self.app.post('/s/test.add', data=dict(labels='one,two'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['config']['labels']
        self.assertEquals(['one', 'two'], labels)

    def test_add_remove_labels(self):
        self.app.post('/s/test.mod', data=dict(labels='one,two,three'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['config']['labels']
        self.assertEquals(['one', 'three', 'two'], labels)

        self.app.post('/s/test.mod', data=dict(labels='one,three'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['config']['labels']
        self.assertEquals(['one', 'three'], labels)

    def test_labels_are_persistent(self):
        self.app.post('/s/test.mod')
        obj = json.loads(self.app.get('/dashboard/one/json').data)
        self.assertEquals(0, len(obj['services']))

        self.app.post('/s/test.mod', data=dict(labels='one,two'))
        obj = json.loads(self.app.get('/dashboard/one/json').data)
        self.assertEquals(1, len(obj['services']))
        self.assertEquals(['one', 'two'],
                          obj['services'][0]['config']['labels'])

        self.app.post('/s/test.mod')
        obj = json.loads(self.app.get('/dashboard/one/json').data)
        self.assertEquals(1, len(obj['services']))
        self.assertEquals(['one', 'two'],
                          obj['services'][0]['config']['labels'])


if __name__ == '__main__':
    unittest.main()
