"""
Created on 2026-08-05

@author: wf
"""

import urllib.parse

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Mail, ThunderbirdMailbox


class TestMailUrl(BaseThunderbirdTest):
    """
    Test the reverse proxy safe url generation for message ids (#45).
    """

    def setUp(self, debug=False, profile=True):
        BaseThunderbirdTest.setUp(self, debug=debug, profile=profile)
        self.github_id = "<owner/repo/issues/1/1234567890@github.com>"
        self.plain_id = "<0c2e98c4-1bc7-9ce9-f80e-07fbed60e554@apache.org>"

    def test_to_url(self):
        """
        Test that ids are urlencoded into the query parameter.
        """
        test_cases = [
            (self.plain_id, "0c2e98c4-1bc7-9ce9-f80e-07fbed60e554%40apache.org"),
            (self.github_id, "owner%2Frepo%2Fissues%2F1%2F1234567890%40github.com"),
            ("/WF.sbd/Pilot#17", "%2FWF.sbd%2FPilot%2317"),
        ]
        for mail_id, expected_quoted in test_cases:
            url = Mail.to_url("mock-user", mail_id)
            self.assertEqual(f"/mailq/mock-user?mailid={expected_quoted}", url)
            # the path part must stay a single segment for the reverse proxy
            path = urllib.parse.urlparse(url).path
            self.assertEqual("/mailq/mock-user", path)
            # and the id must survive the round trip without the angle brackets
            mailid = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["mailid"]
            self.assertEqual([Mail.normalize_mailid(mail_id)], mailid)

    def test_to_url_part(self):
        """
        Test the url of a mail part.
        """
        url = Mail.to_url("mock-user", self.github_id, part_index=2)
        expected = "/partq/mock-user/2?mailid=owner%2Frepo%2Fissues%2F1%2F1234567890%40github.com"
        self.assertEqual(expected, url)

    def test_to_view_lod_link(self):
        """
        Test that the message_id column links via the query url and stays html escaped.
        """
        index_lod = [
            {
                "email_index": 0,
                "message_id": self.github_id,
                "subject": "Re: [owner/repo] a & b",
                "start_pos": 0,
                "stop_pos": 1,
                "folder_path": "/WF.sbd/2025-10",
            }
        ]
        view_lod = ThunderbirdMailbox.to_view_lod(index_lod, user="mock-user")
        record = view_lod[0]
        link = record["message_id"]
        self.assertIn(Mail.to_url("mock-user", self.github_id), link)
        # the visible text is escaped, no raw angle bracket leaks into the html
        self.assertIn("owner/repo/issues/1/1234567890@github.com", link)
        self.assertIn("a &amp; b", record["subject"])
        self.assertEqual(1, record["#"])
