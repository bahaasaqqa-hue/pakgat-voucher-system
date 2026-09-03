import unittest
from urllib.parse import parse_qs, urlsplit

from app.social_attribution import OFFICIAL_SOCIAL_ACCOUNTS, build_utm_url, profile_utm_links


class SocialAttributionTests(unittest.TestCase):
    def test_official_accounts_use_the_approved_shared_handle(self):
        self.assertEqual({row["handle"] for row in OFFICIAL_SOCIAL_ACCOUNTS}, {"@pakgat.sa"})
        self.assertEqual({row["platform"] for row in OFFICIAL_SOCIAL_ACCOUNTS}, {"instagram", "tiktok", "snapchat"})

    def test_utm_url_is_deterministic_and_keeps_existing_query(self):
        url = build_utm_url("https://pakgat.com/ar?lang=ar", source="instagram", campaign="profile")
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query["lang"], ["ar"])
        self.assertEqual(query["utm_source"], ["instagram"])
        self.assertEqual(query["utm_medium"], ["social"])
        self.assertEqual(query["utm_campaign"], ["profile"])

    def test_profile_links_are_unique_per_platform(self):
        links = profile_utm_links()
        self.assertEqual(set(links), {"instagram", "tiktok", "snapchat"})
        self.assertEqual(len(set(links.values())), 3)


if __name__ == "__main__":
    unittest.main()
