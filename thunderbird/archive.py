from dataclasses import dataclass
from datetime import datetime
import os
from typing import List, Dict
from thunderbird.mail import Thunderbird

@dataclass
class MailArchive:
    """
    Represents a single mail archive for a user.

    Attributes:
        user (str): The user to whom the mail archive belongs.
        mailbox_db_path (str): The file path of the mailbox database.
        db_update_time (str): The last update time of the mailbox database.
    """
    user: str
    mailbox_db_path: str
    db_update_time: str = ''

    def __post_init__(self):
        """
        Post-initialization processing to set the database update time.
        """
        self.db_update_time = self._get_db_update_time()

    def _get_db_update_time(self) -> str:
        """
        Gets the formatted last update time of the mailbox database.

        Returns:
            str: The formatted last update time.
        """
        timestamp = os.path.getmtime(self.mailbox_db_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self) -> Dict[str, str]:
        """
        Converts the mail archive data to a dictionary.

        Returns:
            Dict[str, str]: The dictionary representation of the mail archive.
        """
        return {
            'user': self.user,
            'updated': self.db_update_time
        }


class MailArchives:
    """
    Manages a collection of MailArchive instances for different users.

    Attributes:
        user_list (List[str]): A list of user names.
        mail_archives (Dict[str, MailArchive]): A dictionary mapping users to their MailArchive instances.
    """
    def __init__(self, user_list: List[str]):
        """
        Initializes the MailArchives with a list of users.

        Args:
            user_list (List[str]): A list of user names.
        """
        self.user_list = user_list
        self.mail_archives = self._create_mail_archives()

    def _create_mail_archives(self) -> Dict[str, MailArchive]:
        """
        Creates MailArchive instances for each user in the user list.
        """
        archives = {}
        for user in self.user_list:
            # Assuming Thunderbird.get(user) returns a Thunderbird instance with a valid mailbox DB path attribute
            tb_instance = Thunderbird.get(user)
            if hasattr(tb_instance, 'db_path'):  # Replace 'db_path' with the actual attribute name
                mailbox_path = tb_instance.db_path
            else:
                raise ValueError(f"Mailbox path for user '{user}' not found")

            archives[user] = MailArchive(user, mailbox_path)
        return archives

    def as_view_lod(self) -> List[Dict[str, str]]:
        """
        Creates a list of dictionaries representation of the mail archives.

        Returns:
            List[Dict[str, str]]: A list of dictionaries, each representing a mail archive.
        """
        return [archive.to_dict() for archive in self.mail_archives.values()]
