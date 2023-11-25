"""
Created on 2023-11-23

@author: wf
"""
from ngwidgets.input_webserver import InputWebserver
from ngwidgets.webserver import WebserverConfig
from ngwidgets.progress import Progressbar,NiceguiProgressbar
from thunderbird.version import Version
from nicegui import ui, Client, app
from thunderbird.mail import Mail, Thunderbird
from ngwidgets.background import BackgroundTaskHandler

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
        self.bth=BackgroundTaskHandler()
        app.on_shutdown(self.bth.cleanup())
        
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
        
        def get_mail():
            """
            get the mail
            """
            tb = self.mailboxes[user]
            mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
            html_markup=mail.as_html()
            self.mail_view.content = html_markup
            pass

        async def show():
            self.progress_bar = NiceguiProgressbar(100,"load mail","steps") 
            if user in self.mailboxes:
                self.mail_view= ui.html(f"Loading {mailid} for user {user}")
                self.future, result_coro = self.bth.execute_in_background(get_mail)
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