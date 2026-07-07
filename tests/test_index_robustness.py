"""
Created on 2026-07-07

Tests for graceful handling of a missing mail_index table (#32)
and stale index entries whose folder file is gone (#33).

@author: wf
"""
import os

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Mail, Thunderbird


class TestIndexRobustness(BaseThunderbirdTest):
    """
    Test index-related error handling of issues #32 and #33.
    """

    def test_has_index_table(self):
        """
        Test that has_index_table reflects the actual table state (#32):
        the index db file exists right after connect, but the mail_index
        table only exists once indexing has run.
        """
        tb = Thunderbird.get(self.mock_user)
        if os.path.isfile(tb.index_db_path):
            os.remove(tb.index_db_path)
        tb = Thunderbird(
            user=self.mock_user, db=self.db_path, profile=self.profile_path
        )
        Thunderbird.profiles[self.mock_user] = tb
        self.assertFalse(tb.has_index_table())
        # searching a mail must fall back to gloda instead of crashing
        mail = self.getMockedMail()
        self.assertIsNotNone(mail.msg)
        # after indexing the table exists
        tb.create_or_update_index()
        self.assertTrue(tb.has_index_table())

    def test_stale_index_folder(self):
        """
        Test that a mail whose index record points to a no longer existing
        folder file is reported as not found instead of raising (#33).
        """
        tb = Thunderbird.get(self.mock_user)
        if not tb.has_index_table():
            tb.create_or_update_index()
        stale_mailid = "stale-folder-test@example.org"
        record = {
            "folder_path": "/WF.sbd/gone",
            "message_id": f"<{stale_mailid}>",
            "sender": "test@example.org",
            "recipient": "test@example.org",
            "subject": "stale folder test",
            "date": "2020-10-03",
            "iso_date": "2020-10-03T12:00:00",
            "email_index": 0,
            "start_pos": 0,
            "stop_pos": 1,
            "error": "",
        }
        columns = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        tb.index_db.query(
            f"INSERT INTO mail_index ({columns}) VALUES ({placeholders})",
            tuple(record.values()),
            commit=True,
        )
        mail = Mail(user=self.mock_user, mailid=stale_mailid, tb=tb)
        self.assertIsNone(mail.msg)
        self.assertIn("does not exist", mail.error)
