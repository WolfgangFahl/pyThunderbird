"""
Created on 2023-11-23

@author: wf
"""
from ngwidgets.background import BackgroundTaskHandler
from ngwidgets.file_selector import FileSelector
from ngwidgets.input_webserver import InputWebserver
from ngwidgets.lod_grid import ListOfDictsGrid
from ngwidgets.progress import NiceguiProgressbar, Progressbar
from ngwidgets.webserver import WebserverConfig
from ngwidgets.widgets import HideShow
from nicegui import Client, app, ui
from ngwidgets.basetest import Profiler
from thunderbird.mail import Mail, MailArchives, Thunderbird, ThunderbirdMailbox
from thunderbird.version import Version
from fastapi.responses import RedirectResponse
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
        self.tb=None
        
        @ui.page("/mail/{user}/{mailid}")
        async def showMail(user: str, mailid: str):
            return await self.showMail(user, mailid)
        
        @ui.page("/folder/{user}/{folder_path:path}")
        async def showFolder(user:str,folder_path:str):
            return await self.show_folder(user,folder_path) 
        
        @ui.page("/profile/{user}/{profile_key}")
        async def show_folders(user: str, profile_key: str):
            return await self.show_folders(user,profile_key)
  
    async def show_folders(self, user: str, profile_key: str) -> None:
        """
        Asynchronously shows a user's folder contents based on a profile key.
    
        Args:
            user (str): Username for identifying the user profile.
            profile_key (str): Thunderbird profile key
    
        Returns:
            None: The function is intended for display purposes only.
        """
        def show_ui():
            if user not in self.mail_archives.mail_archives:
                ui.html(f"Unknown user {user}")
            else:
                self.user=user
                self.tb=self.mail_archives.mail_archives[user]
                path=f"{self.tb.profile}/Mail/Local Folders"
                extensions={"Folder":".sbd","Mailbox":""}
                self.folder_selector=FileSelector(path=path,extensions=extensions,handler=self.on_select_folder)
        await self.setup_content_div(show_ui)      
        
    async def on_select_folder(self,folder_path):
        """
        open the folder
        """
        relative_path=ThunderbirdMailbox.as_relative_path(folder_path)
        url=f"/folder/{self.user}{relative_path}"
        return ui.open(url,new_tab=True)    
        
    async def show_folder(self,user,folder_path:str):
        """
        show the folder with the given path
        """       
        def show():
            def show_index():
                index_lod=tb_mbox.get_toc_lod_from_sqldb(self.tb.index_db)
                view_lod=tb_mbox.to_view_lod(index_lod, user)
                msg_count=tb_mbox.mbox.__len__()
                self.folder_view.content=(f"{msg_count:5} ({folder_path}")
                self.folder_grid.load_lod(lod=view_lod)
            
            tb=Thunderbird.get(user)
            tb_mbox=ThunderbirdMailbox(tb,folder_path,use_relative_path=True)
            self.folder_view=ui.html()
            self.folder_view.content=f"Loading {tb_mbox.relative_folder_path} ..."
            self.folder_grid=ListOfDictsGrid(key_col="email_index")
            self.folder_grid.html_columns=[1,2]
            self.bth.execute_in_background(show_index)
            
        await self.setup_content_div(show)
        
    async def showMail(self, user: str, mailid: str):
        """
        show the given mail of the given user
        """
        
        def get_mail():
            """
            get the mail
            """
            tb = self.mail_archives.mail_archives[user]
            mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
            html_markup=mail.as_html()
            header_markup=mail.header_as_html()
            with self.header_section.content_div:
                ui.html(header_markup)
            with self.html_section.content_div:
                self.mail_view= ui.html(html_markup)
            pass

        async def show():
            self.progress_bar = NiceguiProgressbar(100,"load mail","steps") 
            if user in self.mail_archives.mail_archives:
                self.html_section=HideShow(("Hide","html"))
                self.header_section = HideShow(("Hide", "Headers"))
                self.future, result_coro = self.bth.execute_in_background(get_mail)
            else:
                self.mail_view= ui.html(f"unknown user {user}")    

        await self.setup_content_div(show)

    def configure_run(self):
        """
        configure me e.g. the allowed urls
        """
        self.mail_archives=MailArchives(self.args.user_list)
        
    def setup_content(self):
        """
        select users
        """
        self.view_lod=self.mail_archives.as_view_lod()
        self.lod_grid=ListOfDictsGrid(lod=self.view_lod)
        
    async def home(self,_client:Client):
        '''
        provide the main content page
        
        '''
        await self.setup_content_div(self.setup_content)