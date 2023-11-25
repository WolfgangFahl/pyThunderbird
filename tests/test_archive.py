"""
Created on 2023-11-24

@author: wf
"""

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.archive import MailArchive, MailArchives  
import os

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
        self.mock_mail('wf')  # Ensure the mock mail environment for user 'wf' is set up

    def test_mail_archive_creation_and_update_time(self):
        """
        Test the creation of a MailArchive instance and its database update time retrieval.
        """
        user = self.mock_user
        gloda_db_path = os.path.join(self.temp_dir, f"tb_{user}.profile", "Mail", "Local Folders", f"{user}.sbd", "2020-10")

        # Ensure the file exists
        if not os.path.exists(gloda_db_path):
            self.fail(f"Expected mock mailbox gloda db file does not exist: {gloda_db_path}")

        archive = MailArchive(user, gloda_db_path)
        self.assertEqual(archive.user, user)
        self.assertEqual(archive.gloda_db_path, gloda_db_path)
        self.assertRegex(archive.db_update_time, r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        
    def test_mail_archives_creation_and_view_lod(self):
        """
        Test the creation of MailArchives with multiple users and the as_view_lod method.
        """
        users = ['wf', 'test_user']
        for user in users:
            self.mock_mail(user)
        archives = MailArchives(users)
        self.assertEqual(len(archives.mail_archives), len(users))
        for user in users:
            self.assertIn(user, archives.mail_archives)
        view_lod = archives.as_view_lod()
        self.assertEqual(len(view_lod), len(users))
        for item in view_lod:
            self.assertIn('user', item)
            self.assertIn('updated', item)