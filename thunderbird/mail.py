'''
Created on 2020-10-24

@author: wf
'''
from lodstorage.sql import SQLDB
from pathlib import Path
import mailbox
import re
import os
import urllib
import yaml


class Thunderbird(object):
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
        self.sqlDB=SQLDB(self.db)
        pass
     
    @staticmethod
    def getProfileMap():
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

    def __init__(self, user,mailid,debug=False,keySearch=True):
        '''
        Constructor
        
        Args:
            user(string): userid of the user 
            mailid(string): unique id of the mail
            debug(bool): True if debugging should be activated
            keySearch(bool): True if a slow keySearch should be tried when lookup fails
        '''
        self.tb=Thunderbird.get(user)
        mailid=re.sub(r"\<(.*)\>",r"\1",mailid)
        self.mailid=mailid
        self.debug=debug
        self.keySearch=keySearch
        self.msg=None
        query="""select m.*,f.* 
from  messages m join
folderLocations f on m.folderId=f.id
where m.headerMessageID==(?)"""
        params=(mailid,)
        maillookup=self.tb.sqlDB.query(query,params)
        #folderId=maillookup['folderId']
        if self.debug:
            print (maillookup)
        if len(maillookup)>=1:
            mailInfo=maillookup[0]
            folderURI=mailInfo['folderURI']
            messageKey=int(mailInfo['messageKey'])
            folderURI=urllib.parse.unquote(folderURI)
            sbdFolder=Mail.toSbdFolder(folderURI)
            folderPath=self.tb.profile+sbdFolder
            if os.path.isfile(folderPath):
                if self.debug:
                    print (folderPath)
                self.mbox=mailbox.mbox(folderPath)
                self.msg=self.mbox.get(messageKey-1)
                # if lookup fails we might loop thru
                # all messages if this option is active ...
                if self.msg is None and self.keySearch:
                    searchId="<%s>" % mailid
                    for key in self.mbox.keys():
                        keyMsg=self.mbox.get(key)
                        msgId=keyMsg.get("Message-Id")
                        if msgId==searchId:
                            self.msg=keyMsg
                            break
                        pass
                self.mbox.close()
                pass
    
    @staticmethod
    def toSbdFolder(folderURI):
        '''
        get the SBD folder for the given folderURI
        '''
        folder=folderURI.replace('mailbox://nobody@','')
        # https://stackoverflow.com/a/14007559/1497139
        parts=folder.split("/")
        sbdFolder="/Mail/"
        for i,part in enumerate(parts):
            if i==0: # e.g. "Local Folders" ... 
                sbdFolder+="%s/" % part
            elif i<len(parts)-1:
                sbdFolder+="%s.sbd/" % part
            else:
                sbdFolder+="%s" % part           
        return sbdFolder
        
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
                
        
        
        