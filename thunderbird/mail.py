"""
Created on 2020-10-24

@author: wf
"""
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
        result: bool = os.path.isfile(self.index_db_path) and os.path.getsize(self.index_db_path) > 0
        return result
    
    def __post_init__(self):
        """
        Post-initialization processing to set the database update times.
        """
        self.gloda_db_update_time = self._get_db_update_time(self.gloda_db_path)
        self.index_db_path = os.path.join(os.path.dirname(self.gloda_db_path), "index_db.sqlite")
        if self.index_db_exists():
            self.index_db_update_time = self._get_db_update_time(self.index_db_path)

    def _get_db_update_time(self, db_path: str) -> str:
        """
        Gets the formatted last update time of the specified database.

        Args:
            db_path (str): The file path of the database for which to get the update time.

        Returns:
            str: The formatted last update time.
        """
        timestamp = os.path.getmtime(db_path)
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
        ps_parts = profile_shortened.split(".") if profile_shortened and "." in profile_shortened else [profile_shortened]
        profile_key = ps_parts[0] if ps_parts else None
        record = {
            'user': self.user,
            'gloda_db_path': self.gloda_db_path,
            'index_db_path': self.index_db_path if self.index_db_path else 'Not provided',
            'profile': profile_key,
            'gloda_updated': self.gloda_db_update_time,
            'index_updated': self.index_db_update_time if self.index_db_update_time else 'Not provided'
        }
        if index is not None:
            record = {'#': index, **record}
        return record

class Thunderbird(MailArchive):
    """
    Thunderbird Mailbox access
    """

    profiles = {}

    def __init__(self, user:str, db=None, profile=None):
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
        super().__init__(user=user, gloda_db_path=db,profile=profile)
            
        try:
            self.sqlDB = SQLDB(self.gloda_db_path, check_same_thread=False, timeout=5)
        except sqlite3.OperationalError as soe:
            print(f"could not open database {self.db}: {soe}")
            raise soe
        pass   
        self.index_db = SQLDB(self.index_db_path,check_same_thread=False)
    
    def get_mailboxes(self):
        """
        Create a dict of Thunderbird mailboxes.

        """
        # Helper function to add mailbox to the dictionary
        def add_mailbox(node):
            # Check if the node is at the root level or a .sbd directory node
            if node["id"]=="1" or  node["label"].endswith(".sbd"):
                return
            if not node["label"].endswith(".sbd"):  # It's a mailbox
                mailbox_path = node["value"]
                mailboxes[mailbox_path] = ThunderbirdMailbox(self,mailbox_path)
                
        path = f"{self.profile}/Mail/Local Folders"
        extensions = {"Folder": ".sbd", "Mailbox": ""}
        file_selector = FileSelector(path=path, extensions=extensions, create_ui=False)

        mailboxes = {}  # Dictionary to store ThunderbirdMailbox instances

        # Define the recursive lambda function for tree traversal
        traverse_tree = (lambda func: (lambda node: func(func, node)))(lambda self, node: (
            add_mailbox(node),
            [self(self, child) for child in node.get("children", [])]
        ))

        # Traverse the tree and populate the mailboxes dictionary
        traverse_tree(file_selector.tree_structure)
        return mailboxes  
    
    def create_or_update_index(self, progress_bar: Optional[Progressbar] = None, force_create: bool = False, verbose: bool = True) -> None:
        """
        Create or update an index of emails from Thunderbird mailboxes, storing the data in an SQLite database.
        If an index already exists and is up-to-date, this method will update it instead of creating a new one.

        Args:
            progress_bar (TqdmProgressbar, optional): Progress bar to display the progress of index creation.
            force_create (bool, optional): If True, forces the creation of a new index even if an up-to-date one exists.
            verbose (bool, optional): If True, prints detailed error and success messages; otherwise, only prints a summary.

        Raises:
            Exception: If any error occurs during database operations.
        """
        mailboxes=self.get_mailboxes()
        if progress_bar is None:
            progress_bar=TqdmProgressbar(total=len(mailboxes),desc="create index",unit="mailbox")      
        errors={}    
        success=Counter()
        first=True
        total_mailboxes = len(mailboxes)
        # Determine whether to create a new index or update the existing one.
        index_up_to_date = self.index_db_exists() and self.index_db_update_time > self.gloda_db_update_time

        if not index_up_to_date or force_create:
            for mailbox in mailboxes.values():
                try:        
                    mbox_lod=mailbox.get_index_lod()
                    progress_bar.update(1)
                    message_count=len(mbox_lod)
                    if message_count>0:
                        if first:
                            with_create=not self.index_db_exists() or force_create
                            entity_info = self.index_db.createTable(mbox_lod, "mail_index",withCreate=with_create,withDrop=with_create)
                            first=False
                        self.index_db.store(mbox_lod, entity_info, fixNone=True)
                    success[mailbox.folder_path]=message_count
                except Exception as ex:
                    errors[mailbox.folder_path]=ex
            self.show_index_report(total_mailboxes,errors,success,verbose)
        else:
            if verbose:
                print(f"Index is up-to-date for user {self.user}. No action was performed.")    
                
    def show_index_report(self,total_mailboxes:int,errors:list,success:Counter,verbose:bool):
        """
        Displays a report on the indexing results of email mailboxes.
    
        Args:
            total_mailboxes (int): The total number of mailboxes involved in the indexing process.
            errors (list): A list of errors encountered during indexing, with each entry containing the path and error details.
            success (Counter): A Counter object (from collections module) that records the number of successful indexing operations for each mailbox.
            verbose (bool): A boolean flag that, when set to True, enables the display of detailed error and success messages.
    
        The function prints detailed error and success messages if verbose is True. 
        It calculates and displays a summary of the indexing process, including the total number of errors, 
        the total number of successful index entries, the average success rate, and the error rate.
        The summary is printed to sys.stderr if there are any errors, and to sys.stdout otherwise.
        """
        # Detailed error and success messages
        if verbose:
            if errors:
                err_msg = "Errors occurred during index creation:\n"
                for path, error in errors.items():
                    err_msg += f"Error in {path}: {error}\n"
                print(err_msg, file=sys.stderr)

            if success:
                success_msg = "Index created successfully for:\n"
                for path, count in success.items():
                    success_msg += f"{path}: {count} entries\n"
                print(success_msg)

        total_errors = len(errors)
        total_successes = sum(success.values())
        average_success = (total_successes / len(success)) if success else 0
        error_rate = (total_errors / total_mailboxes) * 100 if total_mailboxes > 0 else 0
        marker = "❌ " if len(errors) > 0 else "✅"
        msg_channel = sys.stderr if len(errors) > 0 else sys.stdout
        summary_msg = (f"Indexing completed: {marker} Total indexed messages: {total_successes}, "
                       f"Average messages per successful mailbox: {average_success:.2f}, "
                       f"{total_errors} mailboxes with errors ({error_rate:.2f}%).")
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

    def as_view_lod(self) -> List[Dict[str,str]]:
        """
        Creates a list of dictionaries representation of the mail archives.

        Returns:
            List[Dict[str,str]]: A list of dictionaries, each representing a mail archive.
        """
        lod=[]
        for index,archive in enumerate(self.mail_archives.values()):
            record=archive.to_dict(index+1)
            user=record["user"]
            profile=record["profile"]
            record["profile"]=Link.create(f"/profile/{user}/{profile}",profile)
            lod.append(record)
        return lod
    
class ThunderbirdMailbox:
    """
    mailbox wrapper
    """
    
    def __init__(self,tb:Thunderbird,folder_path:str,use_relative_path:bool=False,debug:bool=False):
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
        self.tb=tb
        # Convert relative path to absolute path if use_relative_path is True
        if use_relative_path:
            folder_path = os.path.join(tb.profile, "Mail/Local Folders", folder_path)

        self.folder_path=folder_path
        self.debug=debug
        if not os.path.isfile(folder_path):
            msg=f"{folder_path} does not exist"
            raise ValueError(msg)
        self.relative_folder_path=ThunderbirdMailbox.as_relative_path(folder_path)
        self.mbox = mailbox.mbox(folder_path)
        if tb.index_db_exists():
            self.restore_toc_from_sqldb(tb.index_db)
            
    @staticmethod 
    def as_relative_path(folder_path:str) -> str:
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
    
    def to_view_lod(self, index_lod: List[Dict[str, Any]], user: str) -> List[Dict[str, Any]]:
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
            record["#"] = record.pop("email_index")+1
    
            # Removing 'start_pos','stop_pos' and 'folder_path'
            record.pop("start_pos", None)
            record.pop("stop_pos", None)
            record.pop("folder_path",None)
    
            # Converting 'message_id' to a hyperlink
            mail_id = record["message_id"]
            url = f'/mail/{user}/{mail_id}'
            record["message_id"] = Link.create(url, text=mail_id)
    
        # Reordering keys to ensure '#' is first
        sorted_index_lod = [{k: record[k] for k in sorted(record, key=lambda x: x != '#')} for record in index_lod]
    
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
            idx = record['email_index']
            start_pos = record['start_pos']
            stop_pos = record['stop_pos']

            # Update the TOC with the new positions
            self.mbox._toc[idx] = (start_pos, stop_pos)
        
    def get_index_lod(self):
        """
        get the list of dicts for indexing
        """
        lod=[]
        for idx,message in enumerate(self.mbox):          
            start_pos, stop_pos = self.mbox._toc.get(idx, (None, None))
            record = {
                "folder_path": self.relative_folder_path,
                "message_id": message.get("Message-ID",f"{self.relative_folder_path}#{idx}"),
                "sender": str(message.get("From","?")),
                "recipient": str(message.get("To","?")),
                "subject": str(message.get("Subject","?")),
                "date": message.get("Date"),
                # toc columns
                "email_index": idx,
                "start_pos": start_pos,
                "stop_pos": stop_pos
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
    
    def search_message_by_key(self,mailid:str):
        """
        search messages by key
        """
        msg=None
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
        mailInfo = self.search()
        if mailInfo is not None:
            folderURI = mailInfo["folderURI"]
            messageKey = int(mailInfo["messageKey"])
            folderURI = urllib.parse.unquote(folderURI)
            sbdFolder, self.folder = Mail.toSbdFolder(folderURI)
            folderPath = self.tb.profile + sbdFolder
            tb_mbox=ThunderbirdMailbox(self.tb,folderPath,debug=self.debug)
            self.msg=tb_mbox.get_message_by_key(messageKey)
            # if lookup fails we might loop thru
            # all messages if this option is active ...
            if self.msg is None and self.keySearch:
                self.msg=tb_mbox.search_message_by_key(self.mailid)
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

    def search(self):
        if self.debug:
            print(f"Searching for mail with id {self.mailid} for user {self.user}")
        query = """select m.*,f.* 
from  messages m join
folderLocations f on m.folderId=f.id
where m.headerMessageID==(?)"""
        params = (self.mailid,)
        maillookup = self.tb.query(query, params)
        # folderId=maillookup['folderId']
        if self.debug:
            print(maillookup)
        if len(maillookup) == 0:
            return None
        else:
            mailInfo = maillookup[0]
        return mailInfo

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

    def mail_part_row(self,loop_index:int, part):
        """Generate a table row for a mail part."""
        # Check if loop_index is 0 to add a header
        header = ""
        if self.mailid:
            mailid=self.mailid.replace(">","").replace("<","")
        else:
            mailid="unknown-mailid"
        if loop_index == 0:
            header = "<tr><th>#</th><th>Content Type</th><th>Charset</th><th>Filename</th><th style='text-align:right'>Length</th></tr>"
        link=Link.create(f"/part/{self.user}/{mailid}/{loop_index}",part.filename)
        # Generate the row for the current part
        row = f"<tr><th>{loop_index+1}:</th><td>{part.get_content_type()}</td><td>{part.get_content_charset()}</td><td>{link}</a></td><td style='text-align:right'>{part.length}</td><tr>"
        return header + row
    
    def as_html_section(self,section_name):
        """
        convert my content to the given html section
        
        Args:
            section_name(str): the name of the section to create
        """
        html_parts = []
        # Start building the HTML string
        table_sections=["info","parts","headers"]
        if section_name in  table_sections:
            html_parts.append(f"<table id='{section_name}Table'>")
        if section_name=="title":
            if self.mailid:
                html_parts.append(f"<h2>{self.mailid}</h2>")
        elif section_name=="wiki":
            html_parts.append(self.asWikiMarkup())        
        elif section_name=="info":
            html_parts.append(self.table_line("User", self.user))
            html_parts.append(self.table_line("Folder", self.folder))
            html_parts.append(self.table_line("From", self.fromUrl))
            html_parts.append(self.table_line("To", self.toUrl))
            html_parts.append(self.table_line("Date", self.getHeader("Date")))
            html_parts.append(self.table_line("Subject", self.getHeader("Subject")))
        elif section_name=="headers":
            for key, value in self.headers.items():
                html_parts.append(self.table_line(key, value))
        # Closing t    
        elif section_name=="parts":
            for index, part in enumerate(self.msgParts):
                html_parts.append(self.mail_part_row(index, part))
        elif section_name=="text":
            # Add raw message parts if necessary
            html_parts.append(
                f"<hr><p id='txtMsg'>{self.txtMsg}</p><hr><div id='htmlMsg'>{self.html}</div>"
            )
        if section_name in table_sections:
            # Closing tables
            html_parts.append("</table>")
        markup="".join(html_parts)
        return markup
  
    def as_html(self):
        """Generate the HTML representation of the mail."""
        html=""
        for section_name in ["title","info","parts","text"]:
            html+=self.as_html_section(section_name)
        return html

    def part_as_fileresponse(self, part_index: int,attachments_path:str=None) -> Any:
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
        file_response = FileResponse(path=temp_file_name, filename=part.get_filename() or "file")

        # Delete the temporary file after sending the response
        async def on_send_response() -> None:
            os.unlink(temp_file_name)
        file_response.background = on_send_response
        
        #response=StreamingResponse(io.BytesIO(content),media_type=)
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
