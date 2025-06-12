"""
Created on 2020-10-24

@author: wf
"""
from dataclasses import field
import html
from email import message_from_bytes
from email.message import Message
import mailbox
import os
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
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi.responses import FileResponse
from ftfy import fix_text
from lodstorage.sql import SQLDB
from ngwidgets.dateparser import DateParser
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
            #"gloda_db_path": self.gloda_db_path,
            #"index_db_path": self.index_db_path if self.index_db_path else "-",
            "profile": profile_key,
            "gloda_updated": self.gloda_db_update_time,
            "index_updated": self.index_db_update_time
            if self.index_db_update_time
            else "-",
        }
        if index is not None:
            record = {"#": index, **record}
        return record

@dataclass
class IndexingState:
    """
    State of the index_db for all mailboxes
    """
    total_mailboxes: int = 0
    total_successes: int = 0
    total_errors: int = 0
    force_create: bool = False
    index_up_to_date = False
    success: Counter = field(default_factory=Counter)
    errors: Dict[str, Exception] = field(default_factory=dict)
    gloda_db_update_time: Optional[datetime] = None
    index_db_update_time: Optional[datetime] = None
    msg: str = ""

    def update_msg(self):
        msg=f"{self.total_successes}/{self.total_mailboxes} updated - {self.total_errors} errors"
        return msg

    @property
    def error_rate(self):
        """
        Calculate the error rate in percent
        """
        if self.total_mailboxes > 0:
            error_rate = self.total_errors / self.total_mailboxes *100
        else:
            error_rate=0.0
        return error_rate

    def show_index_report(self, verbose: bool=False, with_print:bool=True)->str:
        """
        Displays a report on the indexing results of email mailboxes.

        Args:
            indexing_result (IndexingResult): The result of the indexing process containing detailed results.
            verbose (bool): If True, displays detailed error and success messages.
            with_print(bool): if True - actually print out the index report
        Returns:
            an indexing report message
        """
        report=""
        if with_print:
            print(self.msg)
            report=self.msg
        if verbose:
            # Detailed error messages
            if self.errors:
                err_msg = "Errors occurred during index creation:\n"
                for path, error in self.errors.items():
                    err_msg += f"Error in {path}: {error}\n"
                if with_print:
                    print(err_msg, file=sys.stderr)
                report+="\n"+err_msg

            # Detailed success messages
            if self.success:
                success_msg = "Index created successfully for:\n"
                for path, count in self.success.items():
                    success_msg += f"{path}: {count} entries\n"
                if with_print:
                    print(success_msg)
                report+="\n"+success_msg

        # Summary message
        total_errors = len(self.errors)
        total_successes = sum(self.success.values())
        average_success = (
            (total_successes / len(self.success))
            if self.success
            else 0
        )
        error_rate = (
            (total_errors / self.total_mailboxes) * 100
            if self.total_mailboxes > 0
            else 0
        )

        marker = "❌ " if total_errors > 0 else "✅"
        summary_msg = (
            f"Indexing completed: {marker}Total indexed messages: {total_successes}, "
            f"Average messages per successful mailbox: {average_success:.2f}, "
            f"{total_errors} mailboxes with errors ({error_rate:.2f}%)."
        )
        msg_channel = sys.stderr if total_errors > 0 else sys.stdout
        if self.total_mailboxes > 0:
            print(summary_msg, file=msg_channel)
            report+="\n"+summary_msg
        return report

    def get_update_lod(self):
        """
        get a list of dict of update records
        """
        update_lod = []
        for i,mailbox in enumerate(self.mailboxes_to_update.values()):
            mb_record=mailbox.as_view_record(index=i+1)
            update_lod.append(mb_record)
        return update_lod


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
        self.errors=[]

    def get_mailboxes(self, progress_bar=None, restore_toc: bool = False):
        """
        Create a dict of Thunderbird mailboxes.

        """
        extensions = {"Folder": ".sbd", "Mailbox": ""}
        file_selector = FileSelector(
            path=self.local_folders, extensions=extensions, create_ui=False
        )
        if progress_bar is not None:
            progress_bar.total = file_selector.file_count
        mailboxes = {}  # Dictionary to store ThunderbirdMailbox instances
        self.errors=[]
        self._traverse_tree(file_selector.tree_structure, mailboxes, progress_bar, restore_toc)
        return mailboxes

    def add_mailbox(self,mailbox_path,mailboxes, progress_bar, restore_toc:bool=False):
        """
        add a ThunderbirdMailBox for the given mailbox_path to the mailboxes
        """
        mailboxes[mailbox_path] = ThunderbirdMailbox(
            self, mailbox_path, restore_toc=restore_toc
        )
        if progress_bar:
            progress_bar.update(1)

    def _traverse_tree(self, parent, mailboxes, progress_bar, restore_toc):
        """
        traves the file system tree from the given parent node
        """
        self._add_mailbox_from_node(parent, mailboxes, progress_bar, restore_toc)
        for child in parent.get("children", []):
            self._traverse_tree(child, mailboxes, progress_bar, restore_toc)

    def _add_mailbox_from_node(self, node, mailboxes, progress_bar, restore_toc):
        """
        add a mailbox from the given file system tree node
        """
        is_valid_mailbox=node["id"] != "1" and not node["label"].endswith(".sbd")
        if is_valid_mailbox:
            try:
                mailbox_path = node["value"]
                self.add_mailbox(mailbox_path, mailboxes, progress_bar, restore_toc)
            except ValueError as e:
                errmsg=f"{node['value']}: {str(e)}"
                self.errors.append(errmsg)

    def get_mailboxes_by_relative_path(self) -> Dict[str, "ThunderbirdMailbox"]:
        """
        Retrieves all mailboxes and returns a dictionary keyed by their relative folder paths.

        This method fetches all Thunderbird mailboxes and organizes them in a dictionary where the keys are the
        relative paths of the mailboxes, providing a quick way to access a mailbox by its relative path.

        Returns:
            Dict[str, ThunderbirdMailbox]: A dictionary where the keys are relative folder paths and the values are
                                           ThunderbirdMailbox objects representing the corresponding mailboxes.
        """
        mailboxes_dict = self.get_mailboxes()
        mailboxes_by_relative_path = {}
        for mailbox in mailboxes_dict.values():
            mailboxes_by_relative_path[mailbox.relative_folder_path] = mailbox
        return mailboxes_by_relative_path

    def to_view_lod(
        self,
        fs_mailboxes_dict: Dict[str, "ThunderbirdMailbox"],
        db_mailboxes_dict: Dict[str, Any],
        force_count: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Merges mailbox information from the filesystem and SQL database into a unified view.

        Args:
            fs_mailboxes_dict (Dict[str, ThunderbirdMailbox]): Mailboxes from the filesystem.
            db_mailboxes_dict (Dict[str, Any]): Mailboxes from the SQL database.
            force_count(bool): if True get count from mailboxes (costly!)
        Returns:
            List[Dict[str, Any]]: A unified list of dictionaries, each representing a mailbox.
        """
        merged_view_lod = []
        all_keys = set(fs_mailboxes_dict.keys()) | set(db_mailboxes_dict.keys())
        unknown = "❓"
        disk_symbol = "💾"  # Symbol representing the filesystem
        database_symbol = "🗄️"  # Symbol representing the database

        for key in all_keys:
            fs_mailbox = fs_mailboxes_dict.get(key)
            db_mailbox = db_mailboxes_dict.get(key)

            state_char = (
                "🔄"
                if fs_mailbox and db_mailbox
                else disk_symbol
                if fs_mailbox
                else database_symbol
            )
            if db_mailbox and "message_count" in db_mailbox:
                count_str = str(db_mailbox["message_count"])
            elif fs_mailbox and force_count:
                count_str = (
                    str(len(fs_mailbox.mbox)) if hasattr(fs_mailbox, "mbox") else "⚠️❓"
                )
            else:
                count_str = unknown
            relative_folder_path = (
                fs_mailbox.relative_folder_path
                if fs_mailbox
                else db_mailbox["relative_folder_path"]
            )
            folder_url = (
                f"/folder/{self.user}{relative_folder_path}" if fs_mailbox else "#"
            )
            error_str = (
                fs_mailbox.error if fs_mailbox else db_mailbox.get("Error", unknown)
            )
            fs_update_time = fs_mailbox.folder_update_time if fs_mailbox else unknown
            db_update_time = db_mailbox["folder_update_time"] if db_mailbox else unknown

            mailbox_record = {
                "State": state_char,
                "Folder": Link.create(folder_url, relative_folder_path),
                f"{disk_symbol}-Updated": fs_update_time,
                f"{database_symbol}-Updated": db_update_time,
                "Count": count_str,
                "Error": error_str,
            }
            merged_view_lod.append(mailbox_record)

        # Sorting by 'Updated' field
        merged_view_lod.sort(key=lambda x: x[f"{disk_symbol}-Updated"], reverse=True)

        # Assigning index after sorting
        for index, record in enumerate(merged_view_lod):
            merged_view_lod[index] = {"#": index, **record}

        return merged_view_lod

    def get_synched_mailbox_view_lod(self):
        """
        Fetches and synchronizes mailbox data from the filesystem and SQL database and returns a unified view.

        Returns:
            List[Dict[str, Any]]: A unified list of dictionaries, each representing a mailbox.
        """
        # Retrieve mailbox data from the filesystem
        fs_mboxes_dict = self.get_mailboxes_by_relative_path()

        # Retrieve mailbox data from the SQL database
        db_mboxes_dict = self.get_mailboxes_dod_from_sqldb(
            self.index_db
        )  # Database mailboxes

        # Merge and format the data for view
        mboxes_view_lod = self.to_view_lod(fs_mboxes_dict, db_mboxes_dict)

        return mboxes_view_lod

    def get_mailboxes_dod_from_sqldb(self, sql_db: SQLDB) -> dict:
        """
        Retrieve the mailbox list of dictionaries (LoD) from the given SQL database,
        and return it as a dictionary keyed by relative_folder_path.

        Args:
            sql_db (SQLDB): An instance of SQLDB connected to the SQLite database.

        Returns:
            dict: A dictionary of mailbox dictionaries, keyed by relative_folder_path.
        """
        sql_query = """SELECT *
                       FROM mailboxes
                       ORDER BY folder_update_time DESC"""
        try:
            mailboxes_lod = sql_db.query(sql_query)
            mailboxes_dict = {mb["relative_folder_path"]: mb for mb in mailboxes_lod}
            return mailboxes_dict
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                return {}
            else:
                raise e

    def index_mailbox(
        self,
        mailbox: "ThunderbirdMailbox",
        progress_bar: Progressbar,
        force_create: bool,
    ) -> tuple:
        """
        Process a single mailbox for updating the index.

        Args:
            mailbox (ThunderbirdMailbox): The mailbox to be processed.
            progress_bar (Progressbar): Progress bar object for visual feedback.
            force_create (bool): Flag to force creation of a new index.

        Returns:
            tuple: A tuple containing the message count and any exception occurred.
        """
        message_count = 0
        exception = None

        try:
            mbox_lod = mailbox.get_index_lod()
            message_count = len(mbox_lod)

            if message_count > 0:
                with_create = not self.index_db_exists() or force_create
                mbox_entity_info = self.index_db.createTable(
                    mbox_lod,
                    "mail_index",
                    withCreate=with_create,
                    withDrop=with_create,
                )
                # first delete existing index entries (if any)
                delete_cmd = f"DELETE FROM mail_index WHERE folder_path='{mailbox.relative_folder_path}'"
                self.index_db.execute(delete_cmd)
                # then store the new ones
                # ignore warnings
                mbox_entity_info.quiet=True
                self.index_db.store(mbox_lod, mbox_entity_info, fixNone=True)

        except Exception as ex:
            exception = ex
        finally:
            if mailbox:
                mailbox.close()     #  ensure mailbox is closed
        progress_bar.update(1)  # Update the progress bar after processing each mailbox
        return message_count, exception  # Single return statement

    def prepare_mailboxes_for_indexing(
        self,
        ixs:IndexingState,
        progress_bar: Optional[Progressbar] = None,
        relative_paths: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, "ThunderbirdMailbox"], Dict[str, "ThunderbirdMailbox"]]:
        """
        Prepare a list of mailboxes for indexing by identifying which ones need to be updated.

        This function iterates through all Thunderbird mailboxes, checking if each needs an update
        based on the last update time in the index database. It returns two dictionaries: one containing
        all mailboxes and another containing only the mailboxes that need updating.

        Args:
            ixs:IndexingState: the indexing state to work on
            force_create (bool): Flag to force creation of a new index for all mailboxes.
            progress_bar (Optional[Progressbar]): A progress bar instance for displaying the progress.
            relative_paths (Optional[List[str]]): A list of relative paths for specific mailboxes to update. If None, all mailboxes are considered.

        Returns:
            Tuple[Dict[str, ThunderbirdMailbox], Dict[str, ThunderbirdMailbox]]: A tuple containing two dictionaries.
                The first dictionary contains all mailboxes, and the second contains only mailboxes that need updating.
        """

        # optionally Retrieve all mailboxes
        if not relative_paths:
            ixs.all_mailboxes = self.get_mailboxes(progress_bar)
        else:
            ixs.all_mailboxes = {}
            for relative_path in relative_paths:
                mailbox_path = f"{self.profile}/Mail/Local Folders{relative_path}"
                mailbox = ThunderbirdMailbox(self, mailbox_path)
                ixs.all_mailboxes[mailbox_path] = mailbox
        # Retrieve the current state of mailboxes from the index database, if not forcing creation
        mailboxes_update_dod = {}
        if not ixs.force_create:
            mailboxes_update_dod = self.get_mailboxes_dod_from_sqldb(self.index_db)

        # List to hold mailboxes that need updating
        ixs.mailboxes_to_update = {}

        # Iterate through each mailbox to check if it needs updating
        if ixs.force_create:
            # If force_create is True, add all mailboxes to the update list
            for mailbox in ixs.all_mailboxes.values():
                ixs.mailboxes_to_update[mailbox.relative_folder_path] = mailbox
        else:
            if relative_paths is not None:
                for mailbox in ixs.all_mailboxes.values():
                    if mailbox.relative_folder_path in relative_paths:
                        ixs.mailboxes_to_update[mailbox.relative_folder_path] = mailbox
            else:
                for mailbox in ixs.all_mailboxes.values():
                    # Check update times only if not forcing creation
                    mailbox_info = mailboxes_update_dod.get(
                        mailbox.relative_folder_path, {}
                    )
                    _prev_mailbox_update_time = mailbox_info.get("folder_update_time")
                    current_folder_update_time = mailbox.folder_update_time

                    # Check if the mailbox needs updating
                    if (
                        self.index_db_update_time is None
                    ) or current_folder_update_time > self.index_db_update_time:
                        ixs.mailboxes_to_update[mailbox.relative_folder_path] = mailbox
        ixs.total_mailboxes = len(ixs.mailboxes_to_update)
        if progress_bar:
            progress_bar.total = ixs.total_mailboxes
            progress_bar.reset()


    def get_indexing_state(self, force_create: bool=False) -> IndexingState:
        """
        Check if the index database needs to be updated or created.

        Args:
            force_create (bool): Flag to force creation of a new index.

        Returns:
            IndexingState
        """
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
        index_up_to_date = (
            self.index_db_exists() and index_db_update_time > gloda_db_update_time
        )
        ixs=IndexingState(
            gloda_db_update_time=gloda_db_update_time,
            index_db_update_time=index_db_update_time,
            force_create=force_create)
        ixs.needs_update = not index_up_to_date or force_create
        marker = "❌ " if ixs.needs_update else "✅"
        ixs.state_msg = f"""{marker} {self.user} update times:
Index db: {ixs.index_db_update_time}
   Gloda: {ixs.gloda_db_update_time}
"""
        return ixs

    def create_or_update_index(self,
        relative_paths: Optional[List[str]] = None,
        force_create:bool=False)->IndexingState:
        # Initialize IndexingResult
        ixs=self.get_indexing_state(force_create)
        self.do_create_or_update_index(ixs,relative_paths=relative_paths)
        return ixs

    def mailboxes_to_lod(self, mailbox_dict: Dict[str, Any], progress_bar: Optional[Progressbar] = None) -> List[Dict[str, Any]]:
        """
        Convert a dictionary of mailbox objects to a list of dicts, updating progress if provided.
        """
        lod = []
        if progress_bar:
            progress_bar.total = len(mailbox_dict)
            progress_bar.reset()
        for mbox in mailbox_dict.values():
            record = mbox.to_dict()
            lod.append(record)
            if progress_bar:
                progress_bar.update(1)
        return lod

    def do_create_or_update_index(
        self,
        ixs:IndexingState,
        progress_bar: Optional[Progressbar] = None,
        relative_paths: Optional[List[str]] = None,
        callback:callable = None
    ) :
        """
        Create or update an index of emails from Thunderbird mailboxes, storing the data in an SQLite database.
        If an index already exists and is up-to-date, this method will update it instead of creating a new one.

        Args:
            ixs:IndexingState: the indexing state to work with
            progress_bar (Progressbar, optional): Progress bar to display the progress of index creation.
            relative_paths (Optional[List[str]]): List of relative mailbox paths to specifically update. If None, updates all mailboxes or based on `force_create`.

        """
        if ixs.needs_update or relative_paths:
            if progress_bar is None:
                progress_bar = TqdmProgressbar(
                    total=ixs.total_mailboxes,
                    desc="create index",
                    unit=" mailbox"
                )

            self.prepare_mailboxes_for_indexing(
               ixs=ixs,
               progress_bar=progress_bar,
               relative_paths=relative_paths
            )

            needs_create = ixs.force_create or not self.index_db_exists()
            for mailbox in ixs.mailboxes_to_update.values():
                message_count, exception = self.index_mailbox(
                    mailbox, progress_bar, needs_create
                )
                if message_count > 0 and needs_create:
                    needs_create = (
                        False  # Subsequent updates will not recreate the table
                    )

                if exception:
                    mailbox.error = exception
                    ixs.errors[mailbox.folder_path] = exception
                else:
                    ixs.success[mailbox.folder_path] = message_count
                ixs.update_msg()
                if callback:
                    callback(mailbox,message_count)
            # if not relative paths were set we need to recreate the mailboxes table
            needs_create = relative_paths is None
            if relative_paths:
                # Delete existing entries for updated mailboxes
                for relative_path in relative_paths:
                    delete_query = (
                        f"DELETE FROM mailboxes WHERE folder_path = '{relative_path}'"
                    )
                    self.index_db.execute(delete_query)

                # Re-create the list of dictionaries for all selected mailboxes
                mailboxes_lod = self.mailboxes_to_lod(ixs.mailboxes_to_update,progress_bar=progress_bar)
            else:
                mailboxes_lod = self.mailboxes_to_lod(ixs.all_mailboxes,progress_bar=progress_bar)
            mailboxes_entity_info = self.index_db.createTable(
                mailboxes_lod,
                "mailboxes",
                withCreate=needs_create,
                withDrop=needs_create,
            )
            # Store the mailbox data in the 'mailboxes' table
            mailboxes_entity_info.quiet=True
            if len(mailboxes_lod) > 0:
                self.index_db.store(mailboxes_lod, mailboxes_entity_info)
        else:
            ixs.msg=ixs.state_msg

    @classmethod
    def get_config_path(cls) -> str:
        home = str(Path.home())
        return os.path.join(home, ".thunderbird")

    @classmethod
    def get_profiles_path(cls) -> str:
        """
        get the profile path
        """
        config_path = cls.get_config_path()
        # Ensure the config_path exists
        os.makedirs(config_path, exist_ok=True)

        profiles_path = os.path.join(config_path, "thunderbird.yaml")
        return profiles_path

    @classmethod
    def getProfileMap(cls):
        """
        get the profile map from a thunderbird.yaml file
        """
        profiles_path = cls.get_profiles_path()
        with open(profiles_path, "r") as stream:
            profile_map = yaml.safe_load(stream)
            # expand ~ in all paths
            for _user, entry in profile_map.items():
                for key in ["db", "profile"]:
                    if key in entry:
                        entry[key] = os.path.expanduser(entry[key])
        return profile_map

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

    def search_mailid_like(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Search for mail headerMessageIDs matching the given SQL LIKE pattern.

        Args:
            pattern (str): SQL LIKE pattern, e.g. '%discourse%'

        Returns:
            List[Dict[str, Any]]: list of matching mail records
        """
        query = """
        SELECT
          strftime('%Y-%m-%d %H:%M:%S', m.date / 1000000, 'unixepoch') AS date,
          m.headerMessageID,
          fl.name AS folder_name,
          fl.folderURI AS folder_uri
        FROM messages m
        JOIN folderLocations fl ON m.folderID = fl.id
        WHERE m.headerMessageID LIKE ?
        ORDER BY m.date DESC
        """
        records = self.query(query, (pattern,))
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
            record["mailboxes"] = Link.create(f"{profile_url}/mailboxes", "mailboxes")
            record["search"] = Link.create(f"{profile_url}/search", "search")
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
        restore_toc: bool = True,
        debug: bool = False,
    ):
        """
        Initializes a new Mailbox object associated with a specific Thunderbird email client and mailbox folder.

        Args:
            tb (Thunderbird): An instance of the Thunderbird class representing the email client to which this mailbox belongs.
            folder_path (str): The file system path to the mailbox folder.
            use_relative_path (bool): If True, use a relative path for the mailbox folder. Default is False.
            restore_toc(bool): If True restore the table of contents
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

        self.debug = debug
        self.error = ""
        if not os.path.isfile(folder_path):
            msg = f"{folder_path} does not exist"
            raise ValueError(msg)
        self.folder_update_time = self.tb._get_file_update_time(self.folder_path)
        self.relative_folder_path = ThunderbirdMailbox.as_relative_path(folder_path)
        self.mbox = mailbox.mbox(folder_path)
        if restore_toc and tb.index_db_exists():
            self.restore_toc_from_sqldb(tb.index_db)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the ThunderbirdMailbox data to a dictionary for SQL database storage.

        Returns:
            Dict[str, Any]: The dictionary representation of the ThunderbirdMailbox.
        """
        message_count = len(self.mbox)  # Assuming self.mbox is a mailbox object
        return {
            "folder_path": self.folder_path,
            "relative_folder_path": self.relative_folder_path,
            "folder_update_time": self.folder_update_time,
            "message_count": message_count,
            "error": str(self.error),
        }

    def as_view_record(self,index:int):
        """
        return me as dict to view in a list of dicts grid
        """
        return {
            "#": index,
            "path": self.relative_folder_path,
            "folder_update_time": self.folder_update_time,
            "error": str(self.error),
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

    @classmethod
    def to_view_lod(
        cls, index_lod: List[Dict[str, Any]], user: str
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
            # HTML-encode potentially unsafe fields
            for key in record:
                if isinstance(record[key], str):
                    record[key] = html.escape(record[key])

            # Renaming and moving 'email_index' to the first position as '#'
            record["#"] = record.pop("email_index") + 1

            # Removing 'start_pos','stop_pos' and 'folder_path'
            record.pop("start_pos", None)
            record.pop("stop_pos", None)
            record.pop("folder_path", None)

            # Converting 'message_id' to a hyperlink
            mail_id = record["message_id"]
            normalized_mail_id = Mail.normalize_mailid(mail_id)
            url = f"/mail/{user}/{normalized_mail_id}"
            record["message_id"] = Link.create(url, text=normalized_mail_id)

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

    def decode_subject(self, subject) -> str:
        # Decode the subject
        decoded_bytes = decode_header(subject)
        # Concatenate the decoded parts
        decoded_subject = "".join(
            str(text, charset or "utf-8") if isinstance(text, bytes) else text
            for text, charset in decoded_bytes
        )
        return decoded_subject

    def get_index_lod(self):
        """
        get the list of dicts for indexing
        """
        lod = []
        for idx, message in enumerate(self.mbox):
            start_pos, stop_pos = self.mbox._toc.get(idx, (None, None))
            error_msg = ""  # Variable to store potential error messages
            decoded_subject = "?"
            msg_date, msg_iso_date, error_msg = Mail.get_iso_date(message)
            try:
                # Decode the subject
                decoded_subject = self.decode_subject(message.get("Subject", "?"))
            except Exception as e:
                error_msg = f"{str(e)}"

            record = {
                "folder_path": self.relative_folder_path,
                "message_id": message.get(
                    "Message-ID", f"{self.relative_folder_path}#{idx}"
                ),
                "sender": str(message.get("From", "?")),
                "recipient": str(message.get("To", "?")),
                "subject": decoded_subject,
                "date": msg_date,
                "iso_date": msg_iso_date,
                "email_index": idx,
                "start_pos": start_pos,
                "stop_pos": stop_pos,
                "error": error_msg,  # Add the error message if any
            }
            lod.append(record)

        return lod

    def get_message_by_key(self, messageKey: int) -> Message:
        """
        Retrieves the email message by its message key.

        This method fetches an email message based on its unique message key from the mbox mailbox file. It uses the
        `messageKey` to index into the mbox file and retrieve the specific message. The method profiles the time taken
        to fetch the message using the `Profiler` utility class for performance monitoring.

        Args:
            messageKey (int): The unique key (index) of the email message to be retrieved.

        Returns:
            Message: The email message object corresponding to the specified message key.

        Note:
            The `messageKey` is assumed to be 1-based when passed to this function, but the `mailbox.mbox` class uses
            0-based indexing, so 1 is subtracted from `messageKey` for internal use.
        """
        getTime = Profiler(
            f"mbox.get {messageKey-1} from {self.folder_path}", profile=self.debug
        )
        msg = self.mbox.get(messageKey - 1)
        getTime.time()
        return msg

    def get_message_by_pos(self, start_pos: int, stop_pos: int) -> Optional[Message]:
        """
        Fetches an email message by its start and stop byte positions in the mailbox file
        and parses it into an email.message.Message object.

        Args:
            start_pos (int): The starting byte position of the message in the mailbox file.
            stop_pos (int): The stopping byte position of the message in the mailbox file.

        Returns:
            Message: The email message object parsed from the specified byte range,
        Raises:
            FileNotFoundError: If the mailbox file does not exist.
            IOError: If an error occurs during file opening or reading.
            ValueError: If the byte range does not represent a valid email message.

        """
        with open(self.folder_path, 'rb') as mbox_file:
            mbox_file.seek(start_pos)  # Move to the start position
            content = mbox_file.read(stop_pos - start_pos)  # Read the specified range

            # Parse the content into an email.message.Message object
            msg = message_from_bytes(content)
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
        Properly close the mailbox
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
        start_pos (int, optional): The start byte position of the message in the mailbox file.
        stop_pos (int, optional): The stop byte position of the message in the mailbox file.
    """

    message_index: int
    folder_path: str
    message_id: str
    start_pos: Optional[int] = None
    stop_pos: Optional[int] = None

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
        start_pos = mail_record.get("start_pos")  # Use .get to handle missing keys
        stop_pos = mail_record.get("stop_pos")
        return cls(message_index, folder_path, message_id, start_pos, stop_pos)

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
        mailid = Mail.normalize_mailid(mailid)
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
            found=False
            if mail_lookup.start_pos is not None and mail_lookup.stop_pos is not None:
                self.msg = tb_mbox.get_message_by_pos(mail_lookup.start_pos, mail_lookup.stop_pos)
                found = self.check_mailid()
            if not found:
                # Fallback to other methods if start_pos and stop_pos are not available
                self.msg = tb_mbox.get_message_by_key(mail_lookup.message_index)
            # if lookup fails we might loop thru
            # all messages if this option is active ...
            found = self.check_mailid()
            if not found and self.keySearch:
                self.msg = tb_mbox.search_message_by_key(self.mailid)
            if self.msg is not None:
                if self.check_mailid():
                    self.extract_message()
                else:
                    self.msg = None
            tb_mbox.close()

    def check_mailid(self) -> bool:
        """
        check the mailid
        """
        found = False
        self.extract_headers()
        # workaround awkward mail ID handling
        # headers should be case insensitive but in reality they might be not
        # if any message-id fits the self.mailid we'll consider the mail as found
        id_headers = ["Message-ID","Message-Id"]
        for id_header in id_headers:
            if id_header in self.headers:
                header_id = self.headers[id_header]
                header_id = self.normalize_mailid(header_id)
                if header_id == self.mailid:
                    found=True
        return found

    @classmethod
    def get_iso_date(cls, msg) -> Tuple[str, Optional[str], Optional[str]]:
        """
        Extracts and formats the date from the email header in ISO format.

        Args:
            msg (Mail): The mail object from which to extract the date.

        Returns:
            Tuple[str, Optional[str], Optional[str]]: A tuple containing the msg_date, the formatted date in ISO format,
            and an error message if the date cannot be extracted or parsed, otherwise None.
        """
        date_parser = DateParser()
        msg_date = msg.get("Date", "")
        iso_date = "?"
        error_msg = None
        if msg_date:
            try:
                iso_date = date_parser.parse_date(msg_date)
            except Exception as e:
                error_msg = f"Error parsing date '{msg_date}': {e}"
        return msg_date, iso_date, error_msg

    @classmethod
    def normalize_mailid(cls, mail_id: str) -> str:
        """
        remove the surrounding <> of the given mail_id
        """
        mail_id = re.sub(r"\<(.*)\>", r"\1", mail_id)
        return mail_id

    def as_html_error_msg(self) -> str:
        """
        Generates an HTML formatted error message for the Mail instance.

        This method should be called when a Mail object is requested but not found.
        It uses the `normalize_mailid` method to format the mail ID in the error message.

        Returns:
            str: An HTML string representing the error message.
        """
        normalized_mailid = Mail.normalize_mailid(self.mailid)
        html_error_msg = f"<span style='color: red;'>Mail with id {normalized_mailid} not found</span>"
        return html_error_msg

    def extract_headers(self):
        """
        update the headers
        """
        if not self.msg:
            self.headers = {}
        else:
            for key in self.msg.keys():
                # https://stackoverflow.com/a/21715870/1497139
                self.headers[key] = str(make_header(decode_header(self.msg.get(key))))

    def extract_message(self, lenient: bool = False) -> None:
        """
        Extracts the message body and headers from the email message.

        This method decodes each part of the email message, handling different content types and charsets. It appends
        the decoded text to the message object's text and HTML attributes.

        Args:
            lenient (bool): If True, the method will not raise an exception for decoding errors, and will instead skip the problematic parts.

        """
        if len(self.headers) == 0:
            self.extract_headers()
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
                rawPart = self.try_decode(part_str, charset, lenient)
                if rawPart is not None:
                    if contentType == "text/plain":
                        self.txtMsg += rawPart
                    elif contentType == "text/html":
                        self.html += rawPart
            pass
        self.handle_headers()

    def try_decode(self, byte_str: bytes, charset: str, lenient: bool) -> str:
        """
        Attempts to decode a byte string using multiple charsets.

        Tries to decode the byte string using a series of common charsets, returning the decoded string upon success.
        If all attempts fail, it either raises a UnicodeDecodeError or returns None, based on the lenient flag.

        Args:
            byte_str (bytes): The byte string to be decoded.
            charset (str): The initial charset to attempt decoding with.
            lenient (bool): If True, suppresses UnicodeDecodeError and returns None for undecodable byte strings.

        Returns:
            str: The decoded string, or None if lenient is True and decoding fails.

        Raises:
            UnicodeDecodeError: If decoding fails and lenient is False.

        """
        charsets_to_try = [charset, "utf-8", "iso-8859-1", "ascii"]
        # Ensure no duplicate charsets in the list
        unique_charsets = list(dict.fromkeys(charsets_to_try))

        for encoding in unique_charsets:
            try:
                decoded = byte_str.decode(encoding)
                return decoded
            except UnicodeDecodeError:
                continue

        if not lenient:
            raise UnicodeDecodeError(
                f"Failed to decode with charsets: {unique_charsets}"
            )
        return None

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
        if len(self.headers) == 0:
            self.extract_headers()
        _msg_date, iso_date, _error_msg = Mail.get_iso_date(self.msg)
        wikison = f"""{{{{mail
|user={self.user}
|id={self.mailid}
|from={self.getHeader('From')}
|to={self.getHeader('To')}
|subject={self.getHeader('Subject')}
|date={iso_date}
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
            html_parts.append("<hr>")
            html_parts.append(f"<table id='{section_name}Table'>")
        if section_name == "title":
            if self.mailid:
                html_parts.append(f"<h2>{self.mailid}</h2>")
        elif section_name == "wiki":
            html_parts.append(f"<hr><pre>{self.asWikiMarkup()}</pre>")
        elif section_name == "info":
            html_parts.append(self.table_line("User", self.user))
            html_parts.append(self.table_line("Folder", self.folder_path))
            html_parts.append(self.table_line("From", self.fromUrl))
            html_parts.append(self.table_line("To", self.toUrl))
            html_parts.append(self.table_line("Date", self.getHeader("Date")))
            html_parts.append(self.table_line("Subject", self.getHeader("Subject")))
            html_parts.append(
                self.table_line("Message-ID", self.getHeader("Message-ID"))
            )
        elif section_name == "headers":
            for key, value in self.headers.items():
                html_parts.append(self.table_line(key, value))
        # Closing t
        elif section_name == "parts":
            for index, part in enumerate(self.msgParts):
                html_parts.append(self.mail_part_row(index, part))
        elif section_name == "text":
            # Add raw message parts if necessary
            html_parts.append(f"<hr><p id='txtMsg'>{self.txtMsg}</p>")
        elif section_name == "html":
            html_parts.append(f"<hr><div id='htmlMsg'>{self.html}</div>")
        if section_name in table_sections:
            # Closing tables
            html_parts.append("</table>")
        markup = "".join(html_parts)
        return markup

    def as_html(self):
        """Generate the HTML representation of the mail."""
        html = ""
        for section_name in ["title", "info", "parts", "text", "html"]:
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
