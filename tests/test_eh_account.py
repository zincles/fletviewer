import unittest
from unittest.mock import Mock

from core.provider.ehgrabber import EHentaiClient


class EHAccountTests(unittest.TestCase):
    def test_read_only_hentaiverse_pages_map_balances(self):
        lottery = Mock(status_code=200, text="<div>You currently have 8,423,532 GP.</div>")
        shop = Mock(status_code=200, text='<div id="networth">Credits: 69,604</div>')
        perks = Mock(status_code=200, text='<p>You currently have <span>588.99</span> Hath.</p>')
        hath_home = Mock(status_code=200, text='<p>Free Archive Quota: <strong>10.2 GB per week</strong>, measured in a 168-hour sliding window.</p>')
        home = Mock(
            status_code=200,
            text='''<h2>Image Limits</h2><div class="homebox">
                <p>You are currently at <strong>1,250</strong> towards your account limit of <strong>50,000</strong>.</p>
                <p>You can reset your image quota by spending <strong>2,500</strong> GP.</p>
            </div>''',
        )
        session = Mock()
        session.get.side_effect = [lottery, shop, perks, hath_home, home]
        balance = EHentaiClient(session=session).get_account_balance()
        self.assertEqual(balance.gallery_points, 8423532)
        self.assertEqual(balance.credits, 69604)
        self.assertEqual(balance.hath, 588.99)
        self.assertEqual(balance.free_archive_quota_gb, 10.2)
        self.assertAlmostEqual(balance.paid_archive_capacity_mib, 421176.6)
        self.assertEqual(balance.estimated_gallery_count(250), 1684)
        self.assertEqual(balance.image_limit_used, 1250)
        self.assertEqual(balance.image_limit_total, 50000)
        self.assertEqual(balance.image_limit_reset_cost_gp, 2500)
        self.assertEqual(session.get.call_count, 5)
