"""
Created on 2023-11-23

@author: wf
"""
from ngwidgets.input_webserver import InputWebserver
from ngwidgets.webserver import WebserverConfig
from thunderbird.version import Version
from nicegui import ui, Client, app
from thunderbird.mail import Mail, Thunderbird

class ThunderbirdWebserver(InputWebserver):
    """
    webserver for Thunderbird mail access via python
    """

    @classmethod
    def get_config(cls) -> WebserverConfig:
        """
        get the configuration for this Webserver
        """
        copy_right = "(c)2020-2023 Wolfgang Fahl"
        config = WebserverConfig(
            copy_right=copy_right, version=Version(), default_port=8482
        )
        return config

    def __init__(self):
        """Constructs all the necessary attributes for the WebServer object."""
        InputWebserver.__init__(self, config=ThunderbirdWebserver.get_config())

        @ui.page("/mail/{user}/{mailid}")
        async def showMail(user: str, mailid: str):
            return await self.showMail(user, mailid)

    def initUsers(self,userList):
        """
        initialize my users
        """
        self.mailboxes={}
        for user in userList:
            self.mailboxes[user]=Thunderbird.get(user)
        pass
    
    async def showMail(self, user: str, mailid: str):
        """
        show the given mail of the given user
        """

        def show():
            if user in self.mailboxes:
                tb = self.mailboxes[user]
                mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
                self.mail_view = ui.html(mail.as_html())
            else:
                self.mail_view= ui.html(f"unknown user {user}")    

        await self.setup_content_div(show)

    def configure_run(self):
        """
        configure the allowed urls
        """
        self.initUsers(self.args.user_list)
        
    def setup_content(self):
        """
        select users
        """
        user_names=list(self.mailboxes.keys())
        self.add_select("users",user_names)
        
    async def home(self,_client:Client):
        '''
        provide the main content page
        
        '''
        await self.setup_content_div(self.setup_content)