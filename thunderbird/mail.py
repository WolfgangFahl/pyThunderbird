"""
Created on 2020-10-24

@author: wf
"""
import mailbox
import os
import re
import sqlite3
import sys
import urllib
from collections import Counter,OrderedDict
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from mimetypes import guess_extension
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from ftfy import fix_text
from ngwidgets.file_selector import FileSelector
from ngwidgets.widgets import Link
from ngwidgets.progress import Progressbar
from lodstorage.sql import SQLDB

from thunderbird.profiler import Profiler
from ngwidgets.progress import TqdmProgressbar


@dataclass
class MailArchive:
    """
    Represents a single mail archive for a user.

    Attributes:
        user (str): The user to whom the mail archive belongs.
        gloda_db_path (str): The file path of the mailbox global database (sqlite).
        profile (str, optional): the thunderbird profile directory of this mailbox.
        db_update_time (str, optional): The last update time of the mailbox database, default is None.
    """
    user: str
    gloda_db_path: str
    index_db_path: str = None
    profile: str = None
    db_update_time: str = None

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
        timestamp = os.path.getmtime(self.gloda_db_path)
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    
    def to_dict(self,index:int=None) -> Dict[str, str]:
        """
        Converts the mail archive data to a dictionary.
        
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
            'profile': profile_key,
            'updated': self.db_update_time
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
    
    def get_mailboxes(self):
        """
        Create an dict of Thunderbird mailboxes.


        """
        # Helper function to add mailbox to the dictionary
        def add_mailbox(node):
            # Check if the node is at the root level or a .sbd directory node
            if node["id"]=="1" or  node["label"].endswith(".sbd"):
                return
            if not node["label"].endswith(".sbd"):  # It's a mailbox
                mailbox_path = node["value"]
                mailboxes[mailbox_path] = ThunderbirdMailbox(mailbox_path)
                
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
    
    def create_index(self, progress_bar: Optional[Progressbar] = None, force_create: bool = False, verbose: bool = True) -> None:
        """
        Create an index of emails from Thunderbird mailboxes, storing the data in an SQLite database.

        Args:
            progress_bar (TqdmProgressbar, optional): Progress bar to display the progress of index creation.
            force_create (bool, optional): If True, forces the creation of a new table even if it already exists.
            verbose (bool, optional): If True, prints detailed error and success messages; otherwise, only prints a summary.

        Raises:
            Exception: If any error occurs during database operations.
        """
        mailboxes=self.get_mailboxes()
        if progress_bar is None:
            progress_bar=TqdmProgressbar(total=len(mailboxes),desc="create index",unit="mailbox")      
        errors={}    
        success=Counter()
        for mailbox in mailboxes.values():
            try:        
                mbox_lod=mailbox.get_index_lod()
                progress_bar.update(1)
                with_create=False
                if self.index_db_path is None:
                    self.index_db_path = os.path.join(os.path.dirname(self.gloda_db_path), "index_db.sqlite")
                    db_exist=os.path.isfile(self.index_db_path)
                    with_create=not db_exist or force_create
                db = SQLDB(self.index_db_path)
                entity_info = db.createTable(mbox_lod, "mail_index",withCreate=with_create,withDrop=with_create)
                db.store(mbox_lod, entity_info, fixNone=True)
                success[mailbox.folder_path]=len(mbox_lod)
            except Exception as ex:
                errors[mailbox.folder_path]=ex
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

        total_mailboxes = len(mailboxes)
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
    
    def __init__(self,folder_path:str,debug:bool=False):
        """
        construct the Mailbox
        """
        self.folder_path=folder_path
        self.debug=debug
        if not os.path.isfile(folder_path):
            msg=f"{folder_path} does not exist"
            raise ValueError(msg)
        self.mbox = mailbox.mbox(folder_path)
        
    def get_index_lod(self):
        """
        get the list of dicts for indexing
        """
        lod=[]
        for message in self.mbox:
            record = {
                "message_id": message.get("Message-ID"),
                "sender": message.get("From"),
                "recipient": message.get("To"),
                "subject": message.get("Subject"),
                "date": message.get("Date"),
                # Add more fields as necessary
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
            tb_mbox=ThunderbirdMailbox(folderPath,debug=self.debug)
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

    def mail_part_row(self, loop_index, part):
        """Generate a table row for a mail part."""
        return f"<tr><th>{loop_index}:</th><td>{part.get_content_type()}</td><td>{part.get_content_charset()}</td><td><a href='...'>{part.filename}</a></td><td style='text-align:right'>{part.length}</td><tr>"

    def as_html(self):
        """Generate the HTML representation of the mail."""
        html_parts = []

        # Add title if exists
        if self.mailid:
            html_parts.append(f"<h2>{self.mailid}</h2>")

        # Start building the HTML string
        html_parts.append("<table id='relevantHeaderTable'>")
        html_parts.append(self.table_line("User", self.user))
        html_parts.append(self.table_line("Folder", self.folder))
        html_parts.append(self.table_line("From", self.fromUrl))
        html_parts.append(self.table_line("To", self.toUrl))
        html_parts.append(self.table_line("Date", self.getHeader("Date")))
        html_parts.append(self.table_line("Subject", self.getHeader("Subject")))

        # Loop for headers
        for key, value in self.headers.items():
            html_parts.append(self.table_line(key, value))

        # Loop for message parts
        html_parts.append(
            "<table id='messageParts' style='display:none'><tr><th>#</th><th>type</th><th>charset</th><th>name</th><th>len</th></tr>"
        )
        for index, part in enumerate(self.msgParts):
            html_parts.append(self.mail_part_row(index, part))

        # Closing tables
        html_parts.append("</table>")

        # Add raw message parts if necessary
        html_parts.append(
            f"<hr><p id='txtMsg'>{self.txtMsg}</p><hr><div id='htmlMsg'>{self.html}</div>"
        )

        return "".join(html_parts)

    def partAsFile(self, folder, partIndex):
        """
        save the given part to a file and return the filename
        """
        # TODO: check Index
        part = self.msgParts[partIndex]
        f = open(f"{folder}/{part.filename}", "wb")
        f.write(part.get_payload(decode=1))
        f.close()
        return part.filename

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
