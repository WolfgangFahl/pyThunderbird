"""
Created on 2023-11-24

@author: wf
"""
import json

from ngwidgets.file_selector import FileSelector
from ngwidgets.progress import TqdmProgressbar

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import MailArchive, MailArchives, Thunderbird, ThunderbirdMailbox


class TestArchive(BaseThunderbirdTest):
    """
    Test the MailArchive and MailArchives classes.
    """

    def setUp(self):
        """
        Set up each test, ensuring the mock mail environment is correctly initialized.
        """
        # Calling the setup of the base class with required parameters
        super().setUp(debug=False, profile=True)
        self.mock_mail()  # Ensure the mock mail environment for the mock_user is setup

    def test_mail_archive_creation_and_update_time(self):
        """
        Test the creation of a MailArchive instance and its database update time retrieval.
        """
        user = self.mock_user
        archive = MailArchive(user, self.db_path)
        self.assertEqual(archive.user, user)
        self.assertEqual(archive.gloda_db_path, self.db_path)
        self.assertRegex(
            archive.gloda_db_update_time, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"
        )

    def test_mail_archives_creation_and_view_lod(self):
        """
        Test the creation of MailArchives with multiple users and the as_view_lod method.
        """
        users = ["test_user1", "test_user2"]
        for user in users:
            self.mock_mail(user)
        archives = MailArchives(users)
        self.assertEqual(len(archives.mail_archives), len(users))
        for user in users:
            self.assertIn(user, archives.mail_archives)
        view_lod = archives.as_view_lod()
        self.assertEqual(len(view_lod), len(users))
        for item in view_lod:
            self.assertIn("user", item)
            self.assertIn("gloda_updated", item)

    def find_in_tree(self, node, label):
        """
        Recursively search for a label in the tree structure.

        Args:
            node (dict): The current node in the tree.
            label (str): The label to search for.

        Returns:
            bool: True if the label is found, False otherwise.
        """
        if node["label"] == label:
            return True

        for child in node.get("children", []):
            if self.find_in_tree(child, label):
                return True

        return False

    def test_file_selector(self):
        """
        test the file selector tree structure
        """
        if self.is_developer():
            user = self.user
            expected_labels = ["Segeln.sbd", "Binnenskipper"]
        else:
            user = self.mock_user
            expected_labels = ["WF.sbd", "2020-10"]

        tb = Thunderbird.get(user)
        path = f"{tb.profile}/Mail/Local Folders"
        extensions = {"Folder": ".sbd", "Mailbox": ""}
        # filter_func=Thunderbird.file_selector_filter
        file_selector = FileSelector(path=path, extensions=extensions, create_ui=False)
        debug = self.debug
        debug = True
        if debug:
            print(json.dumps(file_selector.tree_structure, indent=2))

        tree = file_selector.tree_structure
        self.assertIsNotNone(tree)
        found = 0
        for expected_label in expected_labels:
            if self.find_in_tree(tree, expected_label):
                found += 1
        self.assertEqual(len(expected_labels), found)

    def test_mailbox(self):
        """
        test mailbox access
        """
        if self.is_developer():
            user = self.user
            tb = Thunderbird.get(user)
            path = f"{tb.profile}/Mail/Local Folders/WF.sbd/2023-07"
            tb_mbox = ThunderbirdMailbox(tb, path)
            msg_count = tb_mbox.mbox.__len__()
            print(msg_count)

    def test_get_synched_mailbox_view_lod(self):
        """
        Test the get_synched_mailbox_view_lod method with actual data for a developer.
        """
        if self.is_developer():
            user = self.user
            tb = Thunderbird.get(user)

            # Call the get_synched_mailbox_view_lod method
            mboxes_view_lod = tb.get_synched_mailbox_view_lod()

            # Basic verification to check if the output is in the expected format
            assert isinstance(
                mboxes_view_lod, list
            ), "Expected mboxes_view_lod to be a list"
            assert all(
                isinstance(record, dict) for record in mboxes_view_lod
            ), "Each item in mboxes_view_lod should be a dictionary"

            debug = self.debug
            debug = True
            # if debug is active show a few records
            if debug:
                limit = 10
                count = len(mboxes_view_lod)
                for index, record in enumerate(mboxes_view_lod[:limit]):
                    print(f"{index}/{count}:{record}")

    def test_create_index(self):
        """
        test create index
        """
        if self.is_developer():
            return
            tb = Thunderbird.get(self.user)
            tb.create_or_update_index(force_create=True)
