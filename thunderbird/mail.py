'''
Created on 2020-10-24

@author: wf
'''
from lodstorage.sql import SQLDB
from pathlib import Path
from mailbox import mbox
import re
import os
import urllib
import yaml

class Thunderbird(object):
    profiles={}
    
    def __init__(self,user):
        '''
        construct a Thunderbird access instance for the given user
        '''
        profileMap=Thunderbird.getProfileMap()
        if user in profileMap:
            profile=profileMap[user]
            self.user=user
            self.db=profile['db']
            self.profile=profile['profile']
            self.sqlDB=SQLDB(self.db)
        else:
            raise Exception("user %s missing in .thunderbird.yaml" % user)
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

    def __init__(self, user,mailid,debug=False):
        '''
        Constructor
        
        Args:
            user(string): userid of the user 
            mailid(string): unique id of the mail
        '''
        self.tb=Thunderbird.get(user)
        self.mailid=mailid
        self.debug=debug
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
        if len(maillookup)==1:
            mailInfo=maillookup[0]
            folderURI=mailInfo['folderURI']
            messageKey=int(mailInfo['messageKey'])
            folderURI=urllib.parse.unquote(folderURI)
            folder=folderURI.replace('mailbox://nobody@','/Mail/')
            # https://stackoverflow.com/a/14007559/1497139
            folder=re.sub(r"(.*)/(.*)/(.*)",r"\1/\2.sbd/\3",folder)
            folderPath=self.tb.profile+folder
            if os.path.isfile(folderPath):
                if self.debug:
                    print (folderPath)
                self.mbox=mbox(folderPath)
                self.msg=self.mbox.get(messageKey-1)
                pass
                
        
        
        