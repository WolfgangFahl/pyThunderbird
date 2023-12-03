"""
Created on 2020-10-24

@author: wf
"""
import mailbox
import os
import pendulum
import re
import sqlite3
import sys
import tempfile
import urllib
from collections import Counter, OrderedDict
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from mimetypes import guess_extension
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi.responses import FileResponse
from ftfy import fix_text
from lodstorage.sql import SQLDB
from ngwidgets.file_selector import FileSelector
from ngwidgets.progress import Progressbar, TqdmProgressbar
from ngwidgets.widgets import Link

from thunderbird.profiler import Profiler


@dataclass
class MailArchive:
    """
    Represents a single mail archive for a user.

    Attributes:
        user (str): The user to whom the mail archive belongs.
        gloda_db_path (str): The file path of the mailbox global database (sqlite).
        index_db_path (str, optional): The file path of the mailbox index database (sqlite).
        profile (str, optional): the Thunderbird profile directory of this mailbox.
        gloda_db_update_time (str, optional): The last update time of the global database, default is None.
        index_db_update_time (str, optional): The last update time of the index database, default is None.
    """
    user: str
    gloda_db_path: str
    index_db_path: str = None
    profile: str = None
    gloda_db_update_time: str = None
    index_db_update_time: str = None

    def index_db_exists(self) -> bool:
        """Checks if the index database file exists and is not empty.

        Returns:
            bool: True if the index database file exists and has a size greater than zero, otherwise False.
        """
        # Check if the index database file exists and its size is greater than zero bytes
        result: bool = (
            os.path.isfile(self.index_db_path)
            and os.path.getsize(self.index_db_path) > 0
        )
        return result

    def __post_init__(self):
        """
        Post-initialization processing to set the database update times.
        """
        self.gloda_db_update_time = self._get_file_update_time(self.gloda_db_path)
        self.index_db_path = os.path.join(
            os.path.dirname(self.gloda_db_path), "index_db.sqlite"
        )
        if self.index_db_exists():
            self.index_db_update_time = self._get_file_update_time(self.index_db_path)

    def _get_file_update_time(self, file_path: str) -> str:
        """
        Gets the formatted last update time of the specified file.

        Args:
            file_path (str): The  path of the file for which to get the update time.

        Returns:
            str: The formatted last update time.
        """
        timestamp = os.path.getmtime(file_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self, index: int = None) -> Dict[str, str]:
        """
        Converts the mail archive data to a dictionary, including the update times for both databases.

        Args:
            index (int, optional): An optional index to be added to the dictionary.

        Returns:
            Dict[str, str]: The dictionary representation of the mail archive.
        """
        profile_shortened = os.path.basename(self.profile) if self.profile else None
        ps_parts = (
            profile_shortened.split(".")
            if profile_shortened and "." in profile_shortened
            else [profile_shortened]
        )
        profile_key = ps_parts[0] if ps_parts else None
        record = {
            "user": self.user,
            "gloda_db_path": self.gloda_db_path,
            "index_db_path": self.index_db_path if self.index_db_path else "-",
            "profile": profile_key,
            "mailbox_updated": self.mailbox_update_time,
            "gloda_updated": self.gloda_db_update_time,
            "index_updated": self.index_db_update_time
            if self.index_db_update_time
            else "-",
        }
        if index is not None:
            record = {"#": index, **record}
        return record

@dataclass
class IndexingResult:
    """
    result of creating the index_db for all mailboxes
    """
    total_mailboxes: int
    total_successes: int
    total_errors: int
    error_rate: float
    success: Counter
    errors: Dict[str, Exception]
    gloda_db_update_time: Optional[datetime] = None
    index_db_update_time: Optional[datetime] = None
    msg: Optional[str] = "" 

class Thunderbird(MailArchive):
    """
    Thunderbird Mailbox access
    """

    profiles = {}

    def __init__(self, user: str, db=None, profile=None):
        """
        construct a Thunderbird access instance for the given user
        """
        self.user = user
        if db is None and profile is None:
            profileMap = Thunderbird.getProfileMap()
            if user in profileMap:
                profile = profileMap[user]
            else:
                raise Exception(f"user {user} missing in .thunderbird.yaml")
            db = profile["db"]
            profile = profile["profile"]

        # Call the super constructor
        super().__init__(user=user, gloda_db_path=db, profile=profile)

        try:
            self.sqlDB = SQLDB(self.gloda_db_path, check_same_thread=False, timeout=5)
        except sqlite3.OperationalError as soe:
            print(f"could not open database {self.db}: {soe}")
            raise soe
        pass
        self.index_db = SQLDB(self.index_db_path, check_same_thread=False)
        self.local_folders = f"{self.profile}/Mail/Local Folders"

    def get_mailboxes(self, progress_bar=None):
        """
        Create a dict of Thunderbird mailboxes.

        """
        # Helper function to add mailbox to the dictionary
        def add_mailbox(node):
            # Check if the node is at the root level or a .sbd directory node
            if node["id"] == "1" or node["label"].endswith(".sbd"):
                return
            if not node["label"].endswith(".sbd"):  # It's a mailbox
                mailbox_path = node["value"]
                mailboxes[mailbox_path] = ThunderbirdMailbox(self, mailbox_path)
                if progress_bar:
                    progress_bar.update(1)

        extensions = {"Folder": ".sbd", "Mailbox": ""}
        file_selector = FileSelector(
            path=self.local_folders, extensions=extensions, create_ui=False
        )
        if progress_bar is not None:
            progress_bar.total = file_selector.file_count
        mailboxes = {}  # Dictionary to store ThunderbirdMailbox instances

        # Define the recursive lambda function for tree traversal
        traverse_tree = (lambda func: (lambda node: func(func, node)))(
            lambda self, node: (
                add_mailbox(node),
                [self(self, child) for child in node.get("children", [])],
            )
        )

        # Traverse the tree and populate the mailboxes dictionary
        traverse_tree(file_selector.tree_structure)
        return mailboxes

    def create_or_update_index(
        self,
        progress_bar: Optional[Progressbar] = None,
        force_create: bool = False,
    ) -> IndexingResult:
        """
        Create or update an index of emails from Thunderbird mailboxes, storing the data in an SQLite database.
        If an index already exists and is up-to-date, this method will update it instead of creating a new one.

        Args:
            progress_bar (Progressbar, optional): Progress bar to display the progress of index creation.
            force_create (bool, optional): If True, forces the creation of a new index even if an up-to-date one exists.
            verbose (bool, optional): If True, prints detailed error and success messages; otherwise, only prints a summary.

        Returns:
            IndexingResult: An instance of IndexingResult containing detailed results of the indexing process.
        """
        # Initialize variables
        total_mailboxes, total_errors, total_successes, error_rate = 0, 0, 0, 0.0
        errors, success = {}, Counter()
        msg = "Indexing operation completed."
        gloda_db_update_time = (
            datetime.fromtimestamp(os.path.getmtime(self.gloda_db_path))
            if self.gloda_db_path
            else None
        )
        index_db_update_time = (
            datetime.fromtimestamp(os.path.getmtime(self.index_db_path))
            if self.index_db_exists()
            else None
        )

        # Check if update is needed
        index_up_to_date = (
            self.index_db_exists()
            and self.index_db_update_time > self.gloda_db_update_time
        )
        if not index_up_to_date or force_create:
            if progress_bar is None:
                progress_bar = TqdmProgressbar(
                    total=total_mailboxes, desc="create index", unit="mailbox"
                )
            mailboxes = self.get_mailboxes(progress_bar)
            total_mailboxes = len(mailboxes)
            progress_bar.total=total_mailboxes
            progress_bar.reset()
            mailboxes_lod=[]
            for mailbox in mailboxes.values():
                mailboxes_lod.append(mailbox.to_dict())
                try:
                    mbox_lod = mailbox.get_index_lod()
                    progress_bar.update(1)
                    message_count = len(mbox_lod)
                    if message_count > 0:
                        with_create = not self.index_db_exists() or force_create
                        mbox_entity_info = self.index_db.createTable(
                            mbox_lod,
                            "mail_index",
                            withCreate=with_create,
                            withDrop=with_create,
                        )
                        self.index_db.store(mbox_lod, mbox_entity_info, fixNone=True)
                    success[mailbox.folder_path] = message_count
                except Exception as ex:
                    errors[mailbox.folder_path] = ex
            mailboxes_entity_info=self.index_db.createTable(mailboxes_lod, "mailboxes",withCreate=True,withDrop=True)

            # Store the mailbox data in the 'mailboxes' table
            self.index_db.store(mailboxes_lod, mailboxes_entity_info)

            total_errors = len(errors)
            total_successes = sum(success.values())
            error_rate = (
                (total_errors / total_mailboxes) * 100 if total_mailboxes > 0 else 0
            )
        else:
            msg = f"Index is up-to-date for user {self.user}. No action was performed."

        return IndexingResult(
            total_mailboxes,
            total_successes,
            total_errors,
            error_rate,
            success,
            errors,
            gloda_db_update_time,
            index_db_update_time,
            msg,
        )

    def show_index_report(self, indexing_result: IndexingResult, verbose: bool):
        """
        Displays a report on the indexing results of email mailboxes.

        Args:
            indexing_result (IndexingResult): The result of the indexing process containing detailed results.
            verbose (bool): If True, displays detailed error and success messages.
        """
        print(indexing_result.msg)
        if verbose:
            # Detailed error messages
            if indexing_result.errors:
                err_msg = "Errors occurred during index creation:\n"
                for path, error in indexing_result.errors.items():
                    err_msg += f"Error in {path}: {error}\n"
                print(err_msg, file=sys.stderr)

            # Detailed success messages
            if indexing_result.success:
                success_msg = "Index created successfully for:\n"
                for path, count in indexing_result.success.items():
                    success_msg += f"{path}: {count} entries\n"
                print(success_msg)

        # Summary message
        total_errors = len(indexing_result.errors)
        total_successes = sum(indexing_result.success.values())
        average_success = (total_successes / len(indexing_result.success)) if indexing_result.success else 0
        error_rate = (total_errors / indexing_result.total_mailboxes) * 100 if indexing_result.total_mailboxes > 0 else 0

        marker = "❌ " if total_errors > 0 else "✅"
        msg_channel = sys.stderr if total_errors > 0 else sys.stdout
        summary_msg = (
            f"Indexing completed: {marker}Total indexed messages: {total_successes}, "
            f"Average messages per successful mailbox: {average_success:.2f}, "
            f"{total_errors} mailboxes with errors ({error_rate:.2f}%)."
        )
        if indexing_result.total_mailboxes>0:
            print(summary_msg, file=msg_channel)

    @staticmethod
    def getProfileMap():
        """
        get the profile map from a thunderbird.yaml file
        """
        home = str(Path.home())
        profilesPath = home + "/.thunderbird.yaml"
        with open(profilesPath, "r") as stream:
            profileMap = yaml.safe_load(stream)
        return profileMap

    @staticmethod
    def get(user):
        if not user in Thunderbird.profiles:
            tb = Thunderbird(user)
            Thunderbird.profiles[user] = tb
        return Thunderbird.profiles[user]

    def query(self, sql_query: str, params):
        """
        query this mailbox gloda

        Args:
            sql_query(str): the sql query to execute
            params: the parameters for the query
        """
        records = self.sqlDB.query(sql_query, params)
        return records


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
            archives[user] = tb_instance
        return archives

    def as_view_lod(self) -> List[Dict[str, str]]:
        """
        Creates a list of dictionaries representation of the mail archives.

        Returns:
            List[Dict[str,str]]: A list of dictionaries, each representing a mail archive.
        """
        lod = []
        for index, archive in enumerate(self.mail_archives.values()):
            record = archive.to_dict(index + 1)
            user = record["user"]
            profile = record["profile"]
            profile_url = f"/profile/{user}/{profile}"
            record["profile"] = Link.create(profile_url, profile)
            record["index"] = Link.create(f"{profile_url}/index", "index")
            # add restful call to update index
            lod.append(record)
        return lod


class ThunderbirdMailbox:
    """
    mailbox wrapper
    """

    def __init__(
        self,
        tb: Thunderbird,
        folder_path: str,
        use_relative_path: bool = False,
        debug: bool = False,
    ):
        """
        Initializes a new Mailbox object associated with a specific Thunderbird email client and mailbox folder.

        Args:
            tb (Thunderbird): An instance of the Thunderbird class representing the email client to which this mailbox belongs.
            folder_path (str): The file system path to the mailbox folder.
            use_relative_path (bool): If True, use a relative path for the mailbox folder. Default is False.
            debug (bool, optional): A flag for enabling debug mode. Default is False.

        The constructor sets the Thunderbird instance, folder path, and debug flag. It checks if the provided folder_path
        is a valid file and raises a ValueError if it does not exist. The method also handles the extraction of
        the relative folder path from the provided folder_path, especially handling the case where "Mail/Local Folders"
        is part of the path. Finally, it initializes the mailbox using the `mailbox.mbox` method.

        Raises:
            ValueError: If the provided folder_path does not correspond to an existing file.
        """
        self.tb = tb
        # Convert relative path to absolute path if use_relative_path is True
        if use_relative_path:
            folder_path = os.path.join(tb.profile, "Mail/Local Folders", folder_path)

        self.folder_path = folder_path
        self.folder_update_time = self.tb._get_file_update_time(self.folder_path)

        self.debug = debug
        if not os.path.isfile(folder_path):
            msg = f"{folder_path} does not exist"
            raise ValueError(msg)
        self.relative_folder_path = ThunderbirdMailbox.as_relative_path(folder_path)
        self.mbox = mailbox.mbox(folder_path)
        if tb.index_db_exists():
            self.restore_toc_from_sqldb(tb.index_db)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the ThunderbirdMailbox data to a dictionary for SQL database storage.

        Returns:
            Dict[str, Any]: The dictionary representation of the ThunderbirdMailbox.
        """
        return {
            "folder_path": self.folder_path,
            "relative_folder_path": self.relative_folder_path,
            "folder_update_time": self.folder_update_time,
            # Add any other relevant fields here
        }

    @staticmethod
    def as_relative_path(folder_path: str) -> str:
        """
        convert the folder_path to a relative path

        Args:
            folder_path(str): the folder path to  convert

        Returns:
            str: the relative path
        """
        # Check if "Mail/Local Folders" is in the folder path and split accordingly
        if "Mail/Local Folders" in folder_path:
            relative_folder_path = folder_path.split("Mail/Local Folders")[-1]
        else:
            # If the specific string is not found, use the entire folder_path or handle as needed
            relative_folder_path = folder_path
        return relative_folder_path

    def restore_toc_from_sqldb(self, sql_db: SQLDB) -> None:
        """
        Restore the table of contents from the given SQL database.

        This method fetches the TOC data from the SQLite database and uses it to rebuild the TOC in the mailbox.

        Args:
            sql_db (SQLDB): An instance of SQLDB connected to the SQLite database.
        """
        index_lod = self.get_toc_lod_from_sqldb(sql_db)
        self.restore_toc_from_lod(index_lod)

    def get_toc_lod_from_sqldb(self, sql_db: SQLDB) -> list:
        """
        Retrieve the index list of dictionaries (LoD) representing the TOC from the given SQL database.

        This method performs a SQL query to fetch the TOC information, which includes the email index, start position,
        and stop position for each email in the mailbox corresponding to the current folder path.

        Args:
            sql_db (SQLDB): An instance of SQLDB connected to the SQLite database.

        Returns:
            list: A list of dictionaries, each containing the index and TOC information for an email.
        """
        sql_query = """SELECT *
FROM mail_index 
WHERE folder_path = ?
ORDER BY email_index"""
        folder_path_param = (self.relative_folder_path,)
        index_lod = sql_db.query(sql_query, folder_path_param)
        return index_lod

    def to_view_lod(
        self, index_lod: List[Dict[str, Any]], user: str
    ) -> List[Dict[str, Any]]:
        """
        Converts a list of index record dictionaries into a format suitable for display in an ag-grid.
        It renames and repositions the 'email_index' key, removes 'start_pos' and 'stop_pos', and converts
        'message_id' to a hyperlink using a custom Link.create() function.

        Args:
            index_lod (List[Dict[str, Any]]): A list of dictionaries representing the index records.
            user (str): The user identifier to be used in constructing URLs for hyperlinks.

        Returns:
            List[Dict[str, Any]]: The list of modified index record dictionaries.
        """
        for record in index_lod:
            # Renaming and moving 'email_index' to the first position as '#'
            # shifting numbers by one
            record["#"] = record.pop("email_index") + 1

            # Removing 'start_pos','stop_pos' and 'folder_path'
            record.pop("start_pos", None)
            record.pop("stop_pos", None)
            record.pop("folder_path", None)

            # Converting 'message_id' to a hyperlink
            mail_id = record["message_id"]
            url = f"/mail/{user}/{mail_id}"
            record["message_id"] = Link.create(url, text=mail_id)

        # Reordering keys to ensure '#' is first
        sorted_index_lod = [
            {k: record[k] for k in sorted(record, key=lambda x: x != "#")}
            for record in index_lod
        ]

        return sorted_index_lod

    def restore_toc_from_lod(self, index_lod: list) -> None:
        """
        Restores the table of contents of the mailbox using records from an SQLite database.

        This method iterates over a list of dictionaries where each dictionary contains details about an email,
        including its positions in the mailbox file. It uses this information to reconstruct the mailbox's TOC.

        Args:
            index_lod (list of dict): A list of records from the SQLite database. Each record is a dictionary
                                      containing details about an email, including its positions in the mailbox file.
        """
        # Reinitialize the mailbox's TOC structure
        self.mbox._toc = {}

        # Iterate over the index records to rebuild the TOC
        for record in index_lod:
            idx = record["email_index"]
            start_pos = record["start_pos"]
            stop_pos = record["stop_pos"]

            # Update the TOC with the new positions
            self.mbox._toc[idx] = (start_pos, stop_pos)

    def get_index_lod(self):
        """
        get the list of dicts for indexing
        """
        lod = []
        # Dictionary to map timezone abbreviations to their UTC offsets
        tzinfos = {
            "UT": 0, "UTC": 0, "GMT": 0,  # Universal Time Coordinated
            "EST": -5*3600, "EDT": -4*3600,  # Eastern Time
            "CST": -6*3600, "CDT": -5*3600,  # Central Time
            "MST": -7*3600, "MDT": -6*3600,  # Mountain Time
            "PST": -8*3600, "PDT": -7*3600,  # Pacific Time
            "HST": -10*3600, "AKST": -9*3600, "AKDT": -8*3600,  # Hawaii and Alaska Time
            "CEDT": 2*3600, "EET": 2*3600, "EEST": 3*3600,  # Central European and Eastern European Time
            "CES": 1*3600, "MET": 1*3600  # Central European Summer Time and Middle European Time
        }
        for idx, message in enumerate(self.mbox):
            start_pos, stop_pos = self.mbox._toc.get(idx, (None, None))
            msg_date=message.get("Date")
            parsed_date = pendulum.parse(msg_date, strict=False,tzinfos=tzinfos)
            # Convert to ISO 8601 format
            msg_iso_date = parsed_date.to_iso8601_string()
            record = {
                "folder_path": self.relative_folder_path,
                "message_id": message.get(
                    "Message-ID", f"{self.relative_folder_path}#{idx}"
                ),
                "sender": str(message.get("From", "?")),
                "recipient": str(message.get("To", "?")),
                "subject": str(message.get("Subject", "?")),
                "date": msg_date,
                "iso_date": msg_iso_date,
                # toc columns
                "email_index": idx,
                "start_pos": start_pos,
                "stop_pos": stop_pos,
            }
            lod.append(record)
        return lod

    def get_message_by_key(self, messageKey):
        """
        get the message by its message key
        """
        getTime = Profiler(
            f"mbox.get {messageKey-1} from {self.folder_path}", profile=self.debug
        )
        msg = self.mbox.get(messageKey - 1)
        getTime.time()
        return msg

    def search_message_by_key(self, mailid: str):
        """
        search messages by key
        """
        msg = None
        searchId = f"<{mailid}>"
        searchTime = Profiler(
            f"keySearch {searchId} after mbox.get failed", profile=self.debug
        )
        for key in self.mbox.keys():
            keyMsg = self.mbox.get(key)
            msgId = keyMsg.get("Message-Id")
            if msgId == searchId:
                msg = keyMsg
                break
            pass
        searchTime.time()
        return msg

    def close(self):
        """
        close the mailbox
        """
        self.mbox.close()


@dataclass
class MailLookup:
    """
    A data class representing a mail lookup entity.

    Attributes:
        message_index (int): The index of the message.
        folder_path (str): The path to the folder containing the message.
        message_id (str): The unique identifier of the message.
    """

    message_index: int
    folder_path: str
    message_id: str

    @classmethod
    def from_gloda_record(cls, mail_record: Dict) -> "MailLookup":
        """
        Creates a MailLookup instance from a Gloda record.

        Args:
            mail_record (Dict): A dictionary representing a Gloda record.

        Returns:
            MailLookup: An instance of MailLookup.
        """
        message_id = mail_record["message_id"]
        folder_uri = mail_record["folderURI"]
        message_index = int(mail_record["messageKey"])
        folder_uri = urllib.parse.unquote(folder_uri)
        sbd_folder, _folder = Mail.toSbdFolder(folder_uri)
        relative_folder = ThunderbirdMailbox.as_relative_path(sbd_folder)
        return cls(message_index, relative_folder, message_id)

    @classmethod
    def from_index_db_record(cls, mail_record: Dict) -> "MailLookup":
        """
        Creates a MailLookup instance from an index database record.

        Args:
            mail_record (Dict): A dictionary representing an index database record.

        Returns:
            MailLookup: An instance of MailLookup.
        """
        message_id = mail_record["message_id"]
        message_index = mail_record["email_index"]
        folder_path = mail_record["folder_path"]
        return cls(message_index, folder_path, message_id)

    @classmethod
    def from_mail_record(cls, mail_record: Dict) -> "MailLookup":
        """
        Creates a MailLookup instance based on the source of the mail record.

        Args:
            mail_record (Dict): A dictionary containing the mail record.

        Returns:
            MailLookup: An instance of MailLookup based on the source.
        """
        source = mail_record["source"]
        if source == "gloda":
            return cls.from_gloda_record(mail_record)
        else:
            return cls.from_index_db_record(mail_record)


class Mail(object):
    """
    a single mail
    """

    def __init__(self, user, mailid, tb=None, debug=False, keySearch=True):
        """
        Constructor

        Args:
            user(string): userid of the user
            mailid(string): unique id of the mail
            debug(bool): True if debugging should be activated
            keySearch(bool): True if a slow keySearch should be tried when lookup fails
        """
        self.debug = debug
        self.user = user
        if tb is None:
            self.tb = Thunderbird.get(user)
        else:
            self.tb = tb
        mailid = re.sub(r"\<(.*)\>", r"\1", mailid)
        self.mailid = mailid
        self.keySearch = keySearch
        self.rawMsg = None
        self.msg = None
        self.headers = {}
        self.fromUrl = None
        self.fromMailTo = None
        self.toUrl = None
        self.toMailTo = None
        mail_record = self.search()
        if mail_record is not None:
            mail_lookup = MailLookup.from_mail_record(mail_record)
            self.folder_path = mail_lookup.folder_path
            folderPath = self.tb.local_folders + mail_lookup.folder_path
            tb_mbox = ThunderbirdMailbox(self.tb, folderPath, debug=self.debug)
            self.msg = tb_mbox.get_message_by_key(mail_lookup.message_index)
            # if lookup fails we might loop thru
            # all messages if this option is active ...
            if self.msg is None and self.keySearch:
                self.msg = tb_mbox.search_message_by_key(self.mailid)
            if self.msg is not None:
                self.extract_message()
            tb_mbox.close()

    def extract_message(self):
        for key in self.msg.keys():
            # https://stackoverflow.com/a/21715870/1497139
            self.headers[key] = str(make_header(decode_header(self.msg.get(key))))
        self.txtMsg = ""
        self.html = ""
        # https://stackoverflow.com/a/43833186/1497139
        self.msgParts = []
        # decode parts
        # https://stackoverflow.com/questions/59554237/how-to-handle-all-charset-and-content-type-when-reading-email-from-imap-lib-in-p
        # https://gist.github.com/miohtama/5389146
        for part in self.msg.walk():
            self.msgParts.append(part)
            part.length = len(part._payload)
            # each part is a either non-multipart, or another multipart message
            # that contains further parts... Message is organized like a tree
            contentType = part.get_content_type()
            charset = part.get_content_charset()
            if charset is None:
                charset = "utf-8"
            partname = part.get_param("name")
            part.filename = self.fixedPartName(
                partname, contentType, len(self.msgParts)
            )
            if contentType == "text/plain" or contentType == "text/html":
                part_str = part.get_payload(decode=1)
                rawPart = part_str.decode(charset)
                if contentType == "text/plain":
                    self.txtMsg += rawPart
                elif contentType == "text/html":
                    self.html += rawPart
            pass
        self.handle_headers()

    def handle_headers(self):
        # sort the headers
        self.headers = OrderedDict(sorted(self.headers.items()))
        if "From" in self.headers:
            fromAdr = self.headers["From"]
            self.fromMailTo = f"mailto:{fromAdr}"
            self.fromUrl = f"<a href='{self.fromMailTo}'>{fromAdr}</a>"
        if "To" in self.headers:
            toAdr = self.headers["To"]
            self.toMailTo = f"mailto:{toAdr}"
            self.toUrl = f"<a href='{self.toMailTo}'>{toAdr}</a>"
        pass

    def search(self, use_index_db: bool = True) -> Optional[Dict[str, Any]]:
        """
        Search for an email by its ID in the specified Thunderbird mailbox database.

        This method allows searching either the gloda database or the index database based on the `use_index_db` parameter.
        It returns a dictionary representing the found email or None if not found.

        Args:
            use_index_db (bool): If True, the search will be performed in the index database.
                                 If False, the search will be performed in the gloda database (default).

        Returns:
            Optional[Dict[str, Any]]: A dictionary representing the found email, or None if not found.
        """
        if self.debug:
            print(f"Searching for mail with id {self.mailid} for user {self.user}")

        if use_index_db and self.tb.index_db_exists():
            # Query for the index database
            query = """SELECT * FROM mail_index 
                       WHERE message_id = ?"""
            source = "index_db"
            params = (f"<{self.mailid}>",)
        else:
            # Query for the gloda database
            query = """SELECT m.*, f.* 
                       FROM messages m JOIN
                            folderLocations f ON m.folderId = f.id
                       WHERE m.headerMessageID = (?)"""
            source = "gloda"
            params = (self.mailid,)

        db = (
            self.tb.index_db
            if use_index_db and self.tb.index_db_exists()
            else self.tb.sqlDB
        )
        maillookup = db.query(query, params)

        if self.debug:
            print(maillookup)

        # Store the result in a variable before returning
        mail_record = maillookup[0] if maillookup else None
        if mail_record:
            mail_record["source"] = source
            if not "message_id" in mail_record:
                mail_record["message_id"] = self.mailid
        return mail_record

    def fixedPartName(self, partname: str, contentType: str, partIndex: int):
        """
        get a fixed version of the partname


        Args:
            partname(str): the name of the part
            defaultName(str): the default name to use
        """

        # avoid TypeError: expected string or bytes-like object
        if partname:
            if type(partname) is tuple:
                _encoding, _unknown, partname = partname
            filename = str(make_header(decode_header(partname)))
        else:
            ext = guess_extension(contentType.partition(";")[0].strip())
            if ext is None:
                ext = ".txt"
            filename = f"part{partIndex}{ext}"
        filename = fix_text(filename)
        return filename

    def __str__(self):
        text = f"{self.user}/{self.mailid}"
        return text

    def getHeader(self, headerName: str):
        """
        get the header with the given name

        Args:
            headerName(str): the name of the header

        Returns:
            str: the header value
        """
        if headerName in self.headers:
            headerValue = self.headers[headerName]
        else:
            headerValue = "?"
        return headerValue

    def asWikiMarkup(self) -> str:
        """
        convert me to wiki markup in Wikison notation

        Returns:
            str: a http://wiki.bitplan.com/index.php/WikiSon notation
        """
        wikison = f"""{{{{mail
|user={self.user}
|id={self.mailid}
|from={self.getHeader('From')}
|to={self.getHeader('To')}
|subject={self.getHeader('Subject')}
}}}}"""
        return wikison

    def table_line(self, key, value):
        """Generate a table row with a key and value."""
        return f"<tr><th>{key}:</th><td>{value}</td><tr>"

    def mail_part_row(self, loop_index: int, part):
        """Generate a table row for a mail part."""
        # Check if loop_index is 0 to add a header
        header = ""
        if self.mailid:
            mailid = self.mailid.replace(">", "").replace("<", "")
        else:
            mailid = "unknown-mailid"
        if loop_index == 0:
            header = "<tr><th>#</th><th>Content Type</th><th>Charset</th><th>Filename</th><th style='text-align:right'>Length</th></tr>"
        link = Link.create(f"/part/{self.user}/{mailid}/{loop_index}", part.filename)
        # Generate the row for the current part
        row = f"<tr><th>{loop_index+1}:</th><td>{part.get_content_type()}</td><td>{part.get_content_charset()}</td><td>{link}</a></td><td style='text-align:right'>{part.length}</td><tr>"
        return header + row

    def as_html_section(self, section_name):
        """
        convert my content to the given html section

        Args:
            section_name(str): the name of the section to create
        """
        html_parts = []
        # Start building the HTML string
        table_sections = ["info", "parts", "headers"]
        if section_name in table_sections:
            html_parts.append(f"<table id='{section_name}Table'>")
        if section_name == "title":
            if self.mailid:
                html_parts.append(f"<h2>{self.mailid}</h2>")
        elif section_name == "wiki":
            html_parts.append(self.asWikiMarkup())
        elif section_name == "info":
            html_parts.append(self.table_line("User", self.user))
            html_parts.append(self.table_line("Folder", self.folder_path))
            html_parts.append(self.table_line("From", self.fromUrl))
            html_parts.append(self.table_line("To", self.toUrl))
            html_parts.append(self.table_line("Date", self.getHeader("Date")))
            html_parts.append(self.table_line("Subject", self.getHeader("Subject")))
        elif section_name == "headers":
            for key, value in self.headers.items():
                html_parts.append(self.table_line(key, value))
        # Closing t
        elif section_name == "parts":
            for index, part in enumerate(self.msgParts):
                html_parts.append(self.mail_part_row(index, part))
        elif section_name == "text":
            # Add raw message parts if necessary
            html_parts.append(
                f"<hr><p id='txtMsg'>{self.txtMsg}</p><hr><div id='htmlMsg'>{self.html}</div>"
            )
        if section_name in table_sections:
            # Closing tables
            html_parts.append("</table>")
        markup = "".join(html_parts)
        return markup

    def as_html(self):
        """Generate the HTML representation of the mail."""
        html = ""
        for section_name in ["title", "info", "parts", "text"]:
            html += self.as_html_section(section_name)
        return html

    def part_as_fileresponse(
        self, part_index: int, attachments_path: str = None
    ) -> Any:
        """
        Return the specified part of a message as a FileResponse.

        Args:
            part_index (int): The index of the part to be returned.

        Returns:
            FileResponse: A FileResponse object representing the specified part.

        Raises:
            IndexError: If the part_index is out of range of the message parts.
            ValueError: If the part content is not decodable.

        Note:
            The method assumes that self.msgParts is a list-like container holding the message parts.
            Since FastAPI's FileResponse is designed to work with file paths, this function writes the content to a temporary file.
        """
        # Check if part_index is within the range of msgParts
        if not 0 <= part_index < len(self.msgParts):
            raise IndexError("part_index out of range.")

        # Get the specific part from the msgParts
        part = self.msgParts[part_index]

        # Get the content of the part, decode if necessary
        try:
            content = part.get_payload(decode=True)
        except:
            raise ValueError("Unable to decode part content.")

        # Write content to a temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file_name = temp_file.name
            temp_file.write(content)

        # Create and return a FileResponse object
        file_response = FileResponse(
            path=temp_file_name, filename=part.get_filename() or "file"
        )

        # Delete the temporary file after sending the response
        async def on_send_response() -> None:
            os.unlink(temp_file_name)

        file_response.background = on_send_response

        # response=StreamingResponse(io.BytesIO(content),media_type=)
        return file_response

    @staticmethod
    def toSbdFolder(folderURI):
        """
        get the SBD folder for the given folderURI as a tuple

        Args:
            folderURI(str): the folder uri
        Returns:
            sbdFolder(str): the prefix
            folder(str): the local path
        """
        folder = folderURI.replace("mailbox://nobody@", "")
        # https://stackoverflow.com/a/14007559/1497139
        parts = folder.split("/")
        sbdFolder = "/Mail/"
        folder = ""
        for i, part in enumerate(parts):
            if i == 0:  # e.g. "Local Folders" ...
                sbdFolder += f"{part}/"
            elif i < len(parts) - 1:
                sbdFolder += f"{part}.sbd/"
                folder += f"{part}/"
            else:
                sbdFolder += f"{part}"
                folder += f"{part}"
        return sbdFolder, folder

    @staticmethod
    def create_message(frm, to, content, headers=None):
        if not headers:
            headers = {}
        m = mailbox.Message()
        m["from"] = frm
        m["to"] = to
        for h, v in headers.items():
            m[h] = v
        m.set_payload(content)
        return m
