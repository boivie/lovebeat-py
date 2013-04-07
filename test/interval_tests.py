import unittest
import lovebeat
from base import LovebeatCoreBase

DAYS = 24 * 60 * 60


class SimpleTests(LovebeatCoreBase):
    def test_interval_simple(self):
        self.assertEquals(lovebeat.pinterval(0), "now")
        self.assertEquals(lovebeat.pinterval(1), "1s")
        self.assertEquals(lovebeat.pinterval(59), "59s")
        self.assertEquals(lovebeat.pinterval(60), "1m")
        self.assertEquals(lovebeat.pinterval(59 * 60), "59m")
        self.assertEquals(lovebeat.pinterval(60 * 60), "1h")
        self.assertEquals(lovebeat.pinterval(23 * 60 * 60), "23h")
        self.assertEquals(lovebeat.pinterval(1 * DAYS), "1d")
        self.assertEquals(lovebeat.pinterval(365 * DAYS), "365d")

    def test_interval_smart_rounding(self):
        # Show seconds up to one minute. Then skip those.
        self.assertEquals(lovebeat.pinterval(1), "1s")
        self.assertEquals(lovebeat.pinterval(59), "59s")
        self.assertEquals(lovebeat.pinterval(60 + 1), "1m")
        self.assertEquals(lovebeat.pinterval(60 + 59), "1m")

        # Show minutes unless we show days
        self.assertEquals(lovebeat.pinterval(60 * 60 + 1 * 60), "1h1m")
        self.assertEquals(lovebeat.pinterval(23 * 60 * 60 + 59 * 60), "23h59m")
        self.assertEquals(lovebeat.pinterval(DAYS + 1  * 60), "1d")
        self.assertEquals(lovebeat.pinterval(DAYS + 59  * 60), "1d")

        # Show hours unless we show 10+ days
        self.assertEquals(lovebeat.pinterval(1 * DAYS + 3600), "1d1h")
        self.assertEquals(lovebeat.pinterval(9 * DAYS + 3600), "9d1h")
        self.assertEquals(lovebeat.pinterval(10 * DAYS + 3600), "10d")
        self.assertEquals(lovebeat.pinterval(10 * DAYS + 23 * 3600), "10d")
        self.assertEquals(lovebeat.pinterval(100 * DAYS + 23 * 3600), "100d")

if __name__ == '__main__':
    unittest.main()
