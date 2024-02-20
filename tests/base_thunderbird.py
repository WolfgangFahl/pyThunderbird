"""
Refactored on 2023-11-24

@author: wf
"""
import getpass
import os
import socket

import yaml
from lodstorage.sql import SQLDB
from ngwidgets.basetest import Basetest

from thunderbird.mail import Mail, Thunderbird


class BaseThunderbirdTest(Basetest):
    """
    Base class for Thunderbird related tests, handling common setup and utilities.
    """

    def setUp(self, debug=False, profile=True, temp_dir: str = None):
        """
        Set up the test environment. Differentiate between development and other environments.

        Args:
            temp_dir(str): Configurable temporary directory path
        """
        Basetest.setUp(self, debug=debug, profile=profile)
        self.user = getpass.getuser()
        self.mock_user = "mock-user"
        self.host = socket.gethostname()
        # handle temporary directory
        if temp_dir is None:
            temp_dir = "/tmp/.thunderbird"
        self.temp_dir = temp_dir
        # make sure the temp_dir exists
        os.makedirs(os.path.dirname(temp_dir), exist_ok=True)
        self.db_path = os.path.join(self.temp_dir, f"gloda_{self.user}.sqlite")
        self.profile_path = os.path.join(self.temp_dir, f"tb_{self.user}.profile")

        if self.inPublicCI():
            self.create_mock_thunderbird_config()
        self.mock_mail()

    def create_mock_thunderbird_config(self):
        """
        Create a mock .thunderbird.yaml file in the home directory for public CI environment.
        """
        # Mock configuration
        thunderbird_config = {
            self.user: {"db": self.db_path, "profile": self.profile_path}
        }

        # Write the configuration to a .thunderbird.yaml file in the home directory
        profiles_path = Thunderbird.get_profiles_path()
        if not os.path.isfile(profiles_path):
            with open(profiles_path, "w") as config_file:
                yaml.dump(thunderbird_config, config_file)

    def is_developer(self) -> bool:
        """
        Check whether the test is running on the developer's machine.

        Returns:
            bool: True if on the developer's machine, False otherwise.
        """
        dev = self.user == "wf" and self.host == "fix.bitplan.com"
        return dev

    def mock_mail(self, user: str = None):
        """
        Create a mock SQLITE gloda and Thunderbird environment.

        Args:
            user (str): User name for whom the mail environment is mocked.
        """
        if user is None:
            user = self.mock_user
        mboxFile = os.path.join(
            self.profile_path, "Mail", "Local Folders", f"WF.sbd", "2020-10"
        )
        # make sure the parent directories of the mailbox exist
        os.makedirs(os.path.dirname(mboxFile), exist_ok=True)
        messagesLod = [
            {
                "id": 1003,
                "folderID": 1003,
                "messageKey": 1,
                "conversationID": 286140,
                "date": 1601640003000000,
                "headerMessageID": "mailman.45.1601640003.19840.wikidata@lists.wikimedia.org",
                "deleted": 0,
            }
        ]
        foldersLod = [
            {"id": 1003, "folderURI": "mailbox://nobody@Local%20Folders/WF/2020-10"}
        ]
        sqlDB = SQLDB(self.db_path)
        mEntityInfo = sqlDB.createTable(messagesLod, "messages", "id", withDrop=True)
        sqlDB.store(messagesLod, mEntityInfo)
        fEntityInfo = sqlDB.createTable(
            foldersLod, "folderLocations", "id", withDrop=True
        )
        sqlDB.store(foldersLod, fEntityInfo)
        mboxContent = """From MAILER-DAEMON Sat Oct 24 14:37:31 2020
From: wikidata-request@lists.wikimedia.org
Subject: Wikidata Digest, Vol 107, Issue 2
To: wikidata@lists.wikimedia.org
Reply-To: wikidata@lists.wikimedia.org
Date: Sat, 03 Oct 2020 12:00:03 +0000
Message-ID: <mailman.45.1601640003.19840.wikidata@lists.wikimedia.org>
MIME-Version: 1.0
Content-Type: text/plain; charset="us-ascii"
Content-Transfer-Encoding: 7bit
Sender: "Wikidata" <wikidata-bounces@lists.wikimedia.org>
Send Wikidata mailing list submissions to
    wikidata@lists.wikimedia.org

        
"""
        file = open(mboxFile, "w")
        file.write(mboxContent)
        file.close()
        tb = Thunderbird(user=user, db=self.db_path, profile=self.profile_path)
        Thunderbird.profiles[user] = tb

    def getMockedMail(self):
        """
        get a mocked mail
        """
        mail = Mail(
            f"{self.mock_user}",
            "mailman.45.1601640003.19840.wikidata@lists.wikimedia.org",
            debug=self.debug,
        )
        return mail
