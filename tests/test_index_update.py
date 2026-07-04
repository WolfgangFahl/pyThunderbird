"""
Created on 2026-07-04

@author: wf

Regression test for https://github.com/WolfgangFahl/pyThunderbird/issues/37
"""
import os
import time

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Thunderbird


class TestIndexUpdate(BaseThunderbirdTest):
    """
    test the incremental indexing decision in prepare_mailboxes_for_indexing
    """

    def test_never_indexed_folder_with_old_mtime_is_scheduled(self):
        """
        #37: a folder that was never indexed must be (re)indexed even when its
        mbox mtime is older than the global index_db mtime - as happens after
        mailbackup rsyncs archive folders in with their original timestamps.
        The decision must use the folder's OWN last-indexed time, not the
        global index mtime.
        """
        tb = Thunderbird.get(self.mock_user)

        # a fresh, never-indexed folder with a deliberately OLD mtime
        new_mbox = os.path.join(tb.local_folders, "WF.sbd", "2099-01")
        if os.path.exists(new_mbox):
            os.remove(new_mbox)

        # 1. full index of the initial mock folder(s) only - the new folder does
        #    not exist yet, so it is intentionally left out of the index
        tb.create_or_update_index(force_create=True)
        self.assertTrue(tb.index_db_exists())

        # 2. now add the new folder on disk with an old timestamp
        os.makedirs(os.path.dirname(new_mbox), exist_ok=True)
        with open(new_mbox, "w") as mbox_file:
            mbox_file.write(
                "From x\nMessage-ID: <new-2099@id>\nSubject: t\n"
                "Date: Sat, 01 Jan 2000 00:00:00 +0000\n\n\n"
            )
        old = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, -1))
        os.utime(new_mbox, (old, old))

        # 3. make the index look recent so the previous (buggy) global-mtime
        #    comparison would have skipped the old-mtime folder
        tb.index_db_update_time = "2099-12-31 23:59:59"

        # 4. prepare and assert the never-indexed folder is scheduled anyway
        ixs = tb.get_indexing_state(force_create=False)
        tb.prepare_mailboxes_for_indexing(ixs)

        scheduled = list(ixs.mailboxes_to_update.keys())
        if self.debug:
            print(f"scheduled for update: {scheduled}")
        self.assertTrue(
            any("2099-01" in path for path in scheduled),
            f"never-indexed folder 2099-01 was not scheduled: {scheduled}",
        )

        # cleanup so the test stays repeatable
        os.remove(new_mbox)

    def test_folded_message_id_is_normalized_in_index(self):
        """
        #38: a folded (multi-line) Message-ID header must be stored without
        whitespace so exact-match index lookup works.
        """
        from thunderbird.mail import ThunderbirdMailbox

        tb = Thunderbird.get(self.mock_user)
        mbox_path = os.path.join(tb.local_folders, "WF.sbd", "folded")
        os.makedirs(os.path.dirname(mbox_path), exist_ok=True)
        # Message-ID folded onto a continuation line (leading CRLF + space),
        # as produced for long Outlook ids
        with open(mbox_path, "w") as mbox_file:
            mbox_file.write(
                "From x\r\n"
                "Subject: folded id\r\n"
                "Message-ID: \r\n <FOLDED123@FOO.PROD.OUTLOOK.COM>\r\n"
                "Date: Sat, 01 Jan 2022 00:00:00 +0000\r\n\r\nbody\r\n"
            )

        # restore_toc=False: index straight from the mbox, as the real indexer
        # does (a leftover index from another test would otherwise clear the TOC)
        mailbox = ThunderbirdMailbox(tb, mbox_path, restore_toc=False)
        index_lod = mailbox.get_index_lod()
        mailbox.close()

        message_ids = [record["message_id"] for record in index_lod]
        if self.debug:
            print(f"indexed message_ids: {message_ids}")
        self.assertIn("<FOLDED123@FOO.PROD.OUTLOOK.COM>", message_ids)
        for message_id in message_ids:
            self.assertNotIn("\n", message_id)
            self.assertNotIn("\r", message_id)

        os.remove(mbox_path)

    def test_incremental_index_not_gated_by_gloda_mtime(self):
        """
        #37: a plain (non-forced) reindex must pick up a new folder even when the
        index_db is newer than the gloda db - as it always is after mailbackup
        copies the gloda with scp -p (older timestamp). The outer needs_update
        gate must not skip the per-folder evaluation.
        """
        from thunderbird.mail import Mail

        tb = Thunderbird.get(self.mock_user)
        new_mbox = os.path.join(tb.local_folders, "WF.sbd", "outergate")
        if os.path.exists(new_mbox):
            os.remove(new_mbox)

        # 1. full index of the initial folder(s); index_db is now newer than gloda
        tb.create_or_update_index(force_create=True)
        self.assertTrue(tb.index_db_exists())
        self.assertGreater(
            os.path.getmtime(tb.index_db_path), os.path.getmtime(tb.gloda_db_path)
        )

        # 2. add a new folder AFTER indexing
        os.makedirs(os.path.dirname(new_mbox), exist_ok=True)
        with open(new_mbox, "w") as mbox_file:
            mbox_file.write(
                "From x\r\nSubject: outer gate\r\n"
                "Message-ID: <OUTERGATE@x.com>\r\n"
                "Date: Sat, 01 Jan 2022 00:00:00 +0000\r\n\r\nbody\r\n"
            )

        # 3. plain incremental reindex (NOT forced) must still index it
        tb.create_or_update_index(force_create=False)
        mail = Mail(self.mock_user, "OUTERGATE@x.com")
        self.assertIsNotNone(
            mail.msg, "new folder not indexed by a non-forced incremental reindex"
        )

        os.remove(new_mbox)

    def test_folded_message_id_resolves_end_to_end(self):
        """
        #38: a mail whose Message-ID header is folded must be resolvable by its
        clean id through the index + check_mailid path.
        """
        from thunderbird.mail import Mail

        tb = Thunderbird.get(self.mock_user)
        mbox_path = os.path.join(tb.local_folders, "WF.sbd", "folded2")
        os.makedirs(os.path.dirname(mbox_path), exist_ok=True)
        with open(mbox_path, "w") as mbox_file:
            mbox_file.write(
                "From x\r\n"
                "Subject: folded end to end\r\n"
                "Message-ID: \r\n <FOLDED456@FOO.PROD.OUTLOOK.COM>\r\n"
                "Date: Sat, 01 Jan 2022 00:00:00 +0000\r\n\r\nbody\r\n"
            )
        tb.create_or_update_index(force_create=True)

        mail = Mail(self.mock_user, "FOLDED456@FOO.PROD.OUTLOOK.COM")
        self.assertIsNotNone(mail.msg)

        os.remove(mbox_path)
