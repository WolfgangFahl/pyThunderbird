"""
Created on 2023-11-23

@author: wf
"""
from ngwidgets.background import BackgroundTaskHandler
from ngwidgets.file_selector import FileSelector
from ngwidgets.input_webserver import InputWebserver
from ngwidgets.lod_grid import ListOfDictsGrid
from ngwidgets.progress import NiceguiProgressbar
from ngwidgets.webserver import WebserverConfig
from ngwidgets.widgets import HideShow
from nicegui import Client, app, ui
from thunderbird.mail import Mail, MailArchives, Thunderbird, ThunderbirdMailbox
from thunderbird.search import MailSearch
from thunderbird.version import Version

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
        """Constructor """
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
        
        @ui.page("/profile/{user}/{profile_key}/search")
        async def show_search(user: str, profile_key: str):
            return await self.show_search(user,profile_key)
        
        @ui.page("/profile/{user}/{profile_key}/index")
        async def create_or_update_index(user: str, profile_key: str):
            return await self.create_or_update_index(user,profile_key)
        
        @ui.page("/profile/{user}/{profile_key}")
        async def show_folders(user: str, profile_key: str):
            return await self.show_folders(user,profile_key)
        
        @app.get("/part/{user}/{mailid}/{part_index:int}")
        async def get_part(user:str,mailid:str,part_index:int):
            return await self.get_part(user,mailid,part_index)
  
    def prepare_indexing(self,tb,progress_bar):
        """
        prepare indexing of mailboxes
        """
        # Prepare mailboxes for indexing
        try:
            all_mailboxes, mailboxes_to_update = tb.prepare_mailboxes_for_indexing(progress_bar=progress_bar)
            update_lod = [mb.to_dict() for mb in mailboxes_to_update.values()]
            self.mailboxes_grid.load_lod(all_mailboxes)
        except Exception as ex:
            self.handle_exception(ex, self.do_trace)
            
    async def show_search(self, user: str, profile_key: str):
        """
        Shows a search interface for Thunderbird mails.

        Args:
            user (str): Username for identifying the user profile.
            profile_key (str): Thunderbird profile key.
        """

        def show_ui():
            if user not in self.mail_archives.mail_archives:
                ui.html(f"Unknown user {user}")
                return
    
            # Initialize the Thunderbird instance for the given user
            self.tb = Thunderbird.get(user)
    
            # Define a search dictionary with default values or criteria
            search_dict = {
                "Subject": "",
                "From": "",
                "To": "",
                "Message-ID:": "",
            } 
            # Initialize MailSearch with the Thunderbird instance and the search dictionary
            self.mail_search = MailSearch(self, self.tb, search_dict)
        
        await self.setup_content_div(show_ui)
        
    async def create_or_update_index(self, user: str, profile_key: str) -> None:
        def show_ui():
            if user not in self.mail_archives.mail_archives:
                ui.html(f"Unknown user {user}")
            else:
                self.user=user
                tb=self.mail_archives.mail_archives[user]
                progress_bar=NiceguiProgressbar(total=100,desc="updating index",unit="mailboxes")
                with ui.element():
                    # Create an instance of ListOfDictsGrid to display mailboxes
                    self.mailboxes_grid=ListOfDictsGrid(lod=[])
                self.bth.execute_in_background(self.prepare_indexing,tb,progress_bar=progress_bar)
        
        await self.setup_content_div(show_ui) 
   
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
                extensions={"Folder":".sbd","Mailbox":""}
                self.folder_selector=FileSelector(path=self.tb.local_folders,extensions=extensions,handler=self.on_select_folder)
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
                view_lod=ThunderbirdMailbox.to_view_lod(index_lod, user)
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
        
    async def get_part(self,user:str,mailid:str,part_index:int):
        tb = self.mail_archives.mail_archives[user]
        mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
        response=mail.part_as_fileresponse(part_index)
        return response
        
    async def showMail(self, user: str, mailid: str):
        """
        Show the given mail of the given user.
        """
        
        def get_mail():
            """
            Get the mail.
            """
            try:
                tb = self.mail_archives.mail_archives[user]
                mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
                for section_name, section in self.sections.items():
                    html_markup = mail.as_html_section(section_name)
                    section.content_div.content = html_markup
                    section.update()
            except Exception as ex:
                self.handle_exception(ex, self.do_trace)
    
        async def show():
            try:
                self.sections = {}
                section_names = ["title", "info", "wiki", "headers", "text", "html", "parts"]
                visible_sections = {"title", "info", "text", "html"}  # Sections to be initially visible
                self.progress_bar = NiceguiProgressbar(100, "load mail", "steps")
                if user in self.mail_archives.mail_archives:
                    for section_name in section_names:
                        # Set initial visibility based on the section name
                        show_content = section_name in visible_sections
                        self.sections[section_name] = HideShow(
                            (section_name, section_name), 
                            show_content=show_content,
                            lazy_init=True
                        )
                    for section_name in section_names:
                        self.sections[section_name].set_content(ui.html())
                    # Execute get_mail in the background
                    # self.future, _result_coro = await self.bth.execute_in_background(get_mail)
          
                    get_mail()  # Removed background execution for simplicity
                else:
                    self.mail_view = ui.html(f"unknown user {user}")
            except Exception as ex:
                self.handle_exception(ex)
    
        await self.setup_content_div(show)

    def configure_run(self):
        """
        configure me e.g. the allowed urls
        """
        # If args.user_list is None or empty, use users from the profiles
        # see https://github.com/WolfgangFahl/pyThunderbird/issues/19
        if not self.args.user_list:
            profile_map = Thunderbird.getProfileMap()
            user_list = list(profile_map.keys())
        else:
            user_list = self.args.user_list

        self.mail_archives = MailArchives(user_list)
        
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