'''
Created on 2020-10-24

@author: wf
'''
from lodstorage.sql import SQLDB
from pathlib import Path
import sqlite3
from collections import OrderedDict
import mailbox
from email.header import decode_header, make_header
from mimetypes import guess_extension
from ftfy import fix_text
import re
import os
import sys
import urllib
import yaml
from thunderbird.profiler import Profiler
from argparse import ArgumentParser, RawDescriptionHelpFormatter

class Thunderbird(object):
    '''
    Thunderbird Mailbox access
    '''
    profiles={}
    
    def __init__(self,user,db=None,profile=None):
        '''
        construct a Thunderbird access instance for the given user
        '''
        self.user=user
        if db is None and profile is None:
            profileMap=Thunderbird.getProfileMap()
            if user in profileMap:
                profile=profileMap[user]
            else:
                raise Exception("user %s missing in .thunderbird.yaml" % user)
            self.db=profile['db']
            self.profile=profile['profile']
        else:
            self.db=db
            self.profile=profile
        try:
            self.sqlDB=SQLDB(self.db,check_same_thread=False,timeout=5)
        except sqlite3.OperationalError as soe:
            print(f"could not open database {self.db}: {soe}")
            raise soe
        pass
     
    @staticmethod
    def getProfileMap():
        '''
        get the profile map from a thunderbird.yaml file
        '''
        home = str(Path.home())
        profilesPath=home+"/.thunderbird.yaml"
        with open(profilesPath, 'r') as stream:
            profileMap = yaml.safe_load(stream)
        return profileMap
    
    @staticmethod
    def get(user):
        if not user in Thunderbird.profiles:
            tb=Thunderbird(user)
            Thunderbird.profiles[user]=tb
        return Thunderbird.profiles[user]    

class Mail(object):
    '''
    classdocs
    '''

    def __init__(self, user,mailid,tb=None,debug=False,keySearch=True):
        '''
        Constructor
        
        Args:
            user(string): userid of the user 
            mailid(string): unique id of the mail
            debug(bool): True if debugging should be activated
            keySearch(bool): True if a slow keySearch should be tried when lookup fails
        '''
        self.debug=debug
        self.user=user
        if tb is None:
            self.tb=Thunderbird.get(user)
        else:
            self.tb=tb
        if self.debug:
            print(f"Searching for mail with id {mailid} for user {user}")
        mailid=re.sub(r"\<(.*)\>",r"\1",mailid)
        self.mailid=mailid
        self.keySearch=keySearch
        self.rawMsg=None
        self.headers={}
        self.fromUrl=None
        self.fromMailTo=None
        self.toUrl=None
        self.toMailTo=None
        query="""select m.*,f.* 
from  messages m join
folderLocations f on m.folderId=f.id
where m.headerMessageID==(?)"""
        params=(mailid,)
        maillookup=self.tb.sqlDB.query(query,params)
        #folderId=maillookup['folderId']
        if self.debug:
            print (maillookup)
        if len(maillookup)==0:
            self.found=False
        else:
            self.found=True
            mailInfo=maillookup[0]
            folderURI=mailInfo['folderURI']
            messageKey=int(mailInfo['messageKey'])
            folderURI=urllib.parse.unquote(folderURI)
            sbdFolder,self.folder=Mail.toSbdFolder(folderURI)
            folderPath=self.tb.profile+sbdFolder
            if os.path.isfile(folderPath):
                if self.debug:
                    print (folderPath)
                self.mbox=mailbox.mbox(folderPath)
                getTime=Profiler(f"mbox.get {messageKey-1}",profile=self.debug)
                self.msg=self.mbox.get(messageKey-1)
                getTime.time()
                # if lookup fails we might loop thru
                # all messages if this option is active ...
                if self.msg is None and self.keySearch:
                    searchId="<%s>" % mailid
                    searchTime=Profiler(f"keySearch {searchId} after mbox.get failed",profile=self.debug)
                    for key in self.mbox.keys():
                        keyMsg=self.mbox.get(key)
                        msgId=keyMsg.get("Message-Id")
                        if msgId==searchId:
                            self.msg=keyMsg
                            break
                        pass
                    searchTime.time()
                self.mbox.close()
                if self.msg is not None:
                    for key in self.msg.keys():
                        #https://stackoverflow.com/a/21715870/1497139
                        self.headers[key]=str(make_header(decode_header(self.msg.get(key))))
                    self.txtMsg=""
                    self.html=""
                    # https://stackoverflow.com/a/43833186/1497139
                    self.msgParts=[]
                    # decode parts
                    # https://stackoverflow.com/questions/59554237/how-to-handle-all-charset-and-content-type-when-reading-email-from-imap-lib-in-p
                    # https://gist.github.com/miohtama/5389146
                    for part in self.msg.walk():
                        self.msgParts.append(part)
                        part.length=len(part._payload)
                        # each part is a either non-multipart, or another multipart message
                        # that contains further parts... Message is organized like a tree
                        contentType=part.get_content_type()
                        charset = part.get_content_charset()
                        if charset is None:
                            charset='utf-8'
                        partname=part.get_param('name')
                        part.filename=self.fixedPartName(partname,contentType,len(self.msgParts))
                        if contentType == 'text/plain' or contentType== 'text/html':
                            part_str = part.get_payload(decode=1)
                            rawPart=part_str.decode(charset)
                            if contentType == 'text/plain':
                                self.txtMsg+=rawPart
                            elif contentType == 'text/html':
                                self.html+=rawPart
                        pass
        # sort the headers
        self.headers=OrderedDict(sorted(self.headers.items()))
        if "From" in self.headers:
            fromAdr=self.headers["From"]
            self.fromMailTo=f"mailto:{fromAdr}"
            self.fromUrl=f"<a href='{self.fromMailTo}'>{fromAdr}</a>"
        if "To" in self.headers:
            toAdr=self.headers["To"]
            self.toMailTo=f"mailto:{toAdr}"
            self.toUrl=f"<a href='{self.toMailTo}'>{toAdr}</a>"
        pass
    
    def fixedPartName(self,partname:str,contentType:str,partIndex:int):
        '''
        get a fixed version of the partname
        
        
        Args:
            partname(str): the name of the part
            defaultName(str): the default name to use
        '''
        
        # avoid TypeError: expected string or bytes-like object
        if partname:
            if type(partname) is tuple:
                _encoding,_unknown,partname=partname
            filename=str(make_header(decode_header(partname)))
        else:
            ext=guess_extension(contentType.partition(';')[0].strip())
            if ext is None:
                ext=".txt"
            filename=f"part{partIndex}{ext}"
        filename=fix_text(filename)
        return filename
    
    def __str__(self):
        text=f"{self.user}/{self.mailid}"
        return text
    
    def getHeader(self,headerName:str):
        '''
        get the header with the given name
        
        Args:    
            headerName(str): the name of the header
            
        Returns:
            str: the header value
        '''
        if headerName in self.headers:
            headerValue=self.headers[headerName]
        else:
            headerValue="?"
        return headerValue
    
    def asWikiMarkup(self)->str:
        '''
        convert me to wiki markup in Wikison notation
        
        Returns:
            str: a http://wiki.bitplan.com/index.php/WikiSon notation
        '''
        wikison=f"""{{{{mail
|user={self.user}
|id={self.mailid}
|from={self.getHeader('From')}
|to={self.getHeader('To')}
|subject={self.getHeader('Subject')}
}}}}"""
        return wikison
        
    
    def partAsFile(self,folder,partIndex):
        '''
        save the given part to a file and return the filename
        '''
        # TODO: check Index 
        part=self.msgParts[partIndex]
        f = open(f"{folder}/{part.filename}", 'wb')
        f.write(part.get_payload(decode=1))
        f.close()
        return part.filename
     
    
    @staticmethod
    def toSbdFolder(folderURI):
        '''
        get the SBD folder for the given folderURI as a tuple
        
        Args:
            folderURI(str): the folder uri
        Returns:
            sbdFolder(str): the prefix
            folder(str): the local path
        '''
        folder=folderURI.replace('mailbox://nobody@','')
        # https://stackoverflow.com/a/14007559/1497139
        parts=folder.split("/")
        sbdFolder="/Mail/"
        folder=""
        for i,part in enumerate(parts):
            if i==0: # e.g. "Local Folders" ... 
                sbdFolder+=f"{part}/" 
            elif i<len(parts)-1:
                sbdFolder+=f"{part}.sbd/" 
                folder+=f"{part}/"
            else:
                sbdFolder+=f"{part}"
                folder+=f"{part}"           
        return sbdFolder,folder
        
    @staticmethod
    def create_message(frm, to, content, headers = None):
        if not headers: 
            headers = {}
        m = mailbox.Message()
        m['from'] = frm
        m['to'] = to
        for h,v in headers.items():
            m[h] = v
        m.set_payload(content)
        return m       
                
    
__version__ = "0.0.8"
__date__ = '2021-09-23'
__updated__ = '2021-09-23'    

DEBUG = 1

    
def main(argv=None): # IGNORE:C0111
    '''main program.'''

    if argv is None:
        argv=sys.argv[1:]
        
    program_name = os.path.basename(__file__)
    program_version = "v%s" % __version__
    program_build_date = str(__updated__)
    program_version_message = '%%(prog)s %s (%s)' % (program_version, program_build_date)
    program_shortdesc = "script to retrieve thunderbird mail via user and mailid"
    user_name="Wolfgang Fahl"
    program_license = '''%s

  Created by %s on %s.
  Copyright 2020-2021 Wolfgang Fahl. All rights reserved.

  Licensed under the Apache License 2.0
  http://www.apache.org/licenses/LICENSE-2.0

  Distributed on an "AS IS" basis without warranties
  or conditions of any kind, either express or implied.

USAGE
''' % (program_shortdesc,user_name, str(__date__))

    try:
        # Setup argument parser
        parser = ArgumentParser(description=program_license, formatter_class=RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug", dest="debug", action="count", help="set debug level [default: %(default)s]")
        parser.add_argument('-V', '--version', action='version', version=program_version_message)
        parser.add_argument('-u','--user',type=str,help="id of the user")       
        parser.add_argument('-i','--id',type=str,help="id of the mail to retrieve")
  
        # Process arguments
        args = parser.parse_args(argv)
        if args.user is None or args.id is None:
            parser.print_help()
        else:
            mail=Mail(user=args.user,mailid=args.id,debug=args.debug)
            print (mail.msg)

    except KeyboardInterrupt:
        ### handle keyboard interrupt ###
        return 1
    except Exception as e:
        if DEBUG:
            raise(e)
        indent = len(program_name) * " "
        sys.stderr.write(program_name + ": " + repr(e) + "\n")
        sys.stderr.write(indent + "  for help use --help")
        return 2     
    
if __name__ == "__main__":
    if DEBUG:
        sys.argv.append("-d")
    sys.exit(main())
        
        