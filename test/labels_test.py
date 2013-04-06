import json
import unittest
from base import LovebeatBase


class LabelsTests(LovebeatBase):
    def test_no_labels(self):
        self.app.post('/s/test.no')
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['conf']['labels']
        self.assertEquals([], labels)

    def test_add_labels(self):
        self.app.post('/s/test.add', data=dict(labels='one,two'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['conf']['labels']
        self.assertEquals(['one', 'two'], labels)

    def test_add_remove_labels(self):
        self.app.post('/s/test.mod', data=dict(labels='one,two,three'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['conf']['labels']
        self.assertEquals(['one', 'three', 'two'], labels)

        self.app.post('/s/test.mod', data=dict(labels='one,three'))
        obj = json.loads(self.app.get('/dashboard/all/json').data)
        labels = obj['services'][0]['conf']['labels']
        self.assertEquals(['one', 'three'], labels)


if __name__ == '__main__':
    unittest.main()
