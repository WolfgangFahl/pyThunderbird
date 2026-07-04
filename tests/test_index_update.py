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
