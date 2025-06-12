"""
Created on 2023-11-23

@author: wf
"""
from fastapi import HTTPException, Response
from fastapi.responses import  FileResponse
from ngwidgets.file_selector import FileSelector
from ngwidgets.input_webserver import InputWebserver, InputWebSolution
from ngwidgets.lod_grid import GridConfig, ListOfDictsGrid
from ngwidgets.progress import NiceguiProgressbar
from ngwidgets.webserver import WebserverConfig
from ngwidgets.widgets import HideShow
from nicegui import Client, app, ui, run

from thunderbird.mail import Mail, MailArchives, Thunderbird, ThunderbirdMailbox,\
    IndexingState
from thunderbird.search import MailSearch
from thunderbird.version import Version

from typing import Any

class ThunderbirdWebserver(InputWebserver):
    """
    webserver for Thunderbird mail access via python
    """

    @classmethod
    def get_config(cls) -> WebserverConfig:
        """
        get the configuration for this Webserver
        """
        copy_right = "(c)2020-2024 Wolfgang Fahl"
        config = WebserverConfig(
            copy_right=copy_right,
            version=Version(),
            short_name="tbmail",
            default_port=8482,
            timeout=15.0
        )
        server_config = WebserverConfig.get(config)
        server_config.solution_class = ThunderbirdSolution
        return server_config


    def __init__(self):
        """Constructor"""
        InputWebserver.__init__(self, config=ThunderbirdWebserver.get_config())

        @app.get("/part/{user}/{mailid}/{part_index:int}")
        async def get_part(user: str, mailid: str, part_index: int):
            return await self.get_part(
                user, mailid, part_index
            )

        @app.get("/mail/{user}/{mailid}.wiki")
        def get_mail_wikimarkup(user: str, mailid: str):
            mail = self.get_mail(user, mailid)
            if (
                not mail.msg
            ):  # Assuming mail objects have a 'msg' attribute to check if the message exists
                html_markup = mail.as_html_error_msg()

                raise HTTPException(status_code=404, detail=html_markup)
            response = Response(content=mail.asWikiMarkup(), media_type="text/plain")
            return response

        @ui.page("/mailq/{user}")
        async def showMailWithQuery(client: Client, user: str):
            mailid = client.request.query_params.get("mailid")
            return await self.page(client, ThunderbirdSolution.showMail, user, mailid)


        @ui.page("/mail/{user}/{mailid}")
        async def showMail(client: Client,user: str, mailid: str):
            return await self.page(
                client,ThunderbirdSolution.showMail,
                user, mailid
            )

        @ui.page("/folder/{user}/{folder_path:path}")
        async def showFolder(client: Client,user: str, folder_path: str):
            return await self.page(
                client,ThunderbirdSolution.show_folder,
                user, folder_path
            )

        @ui.page("/profile/{user}/{profile_key}/mailboxes")
        async def show_mailboxes(client: Client,user: str, profile_key: str):
            return await self.page(
                client,ThunderbirdSolution.show_mailboxes,
                user, profile_key
            )

        @ui.page("/profile/{user}/{profile_key}/search")
        async def show_search(client: Client,user: str, profile_key: str):
            return await self.page(
                client,ThunderbirdSolution.show_search,
                user, profile_key
            )

        @ui.page("/profile/{user}/{profile_key}/index")
        async def create_or_update_index(client: Client,user: str, profile_key: str):
            return await self.page(
                client,ThunderbirdSolution.create_or_update_index,
                user, profile_key
            )

        @ui.page("/profile/{user}/{profile_key}")
        async def show_folders(client: Client,user: str, profile_key: str):
            return await self.page(
                client,ThunderbirdSolution.show_folders,
                user, profile_key
            )

    def configure_run(self):
        """
        configure me e.g. the allowed urls
        """
        InputWebserver.configure_run(self)
        # If args.user_list is None or empty, use users from the profiles
        # see https://github.com/WolfgangFahl/pyThunderbird/issues/19
        if not self.args.user_list:
            profile_map = Thunderbird.getProfileMap()
            user_list = list(profile_map.keys())
        else:
            user_list = self.args.user_list

        self.mail_archives = MailArchives(user_list)

    def get_mail(self, user: str, mailid: str) -> Any:
        """
        Retrieves a specific mail for a given user by its mail identifier.

        Args:
            user (str): The username of the individual whose mail is to be retrieved.
            mailid (str): The unique identifier for the mail to be retrieved.

        Returns:
            Any: Returns an instance of the Mail class corresponding to the specified `mailid` for the `user`.

        Raises:
            HTTPException: If the user is not found in the mail archives, an HTTP exception with status code 404 is raised.
        """
        if user not in self.mail_archives.mail_archives:
            raise HTTPException(status_code=404, detail=f"User '{user}' not found")
        tb = self.mail_archives.mail_archives[user]
        mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
        return mail

    async def get_part(self, user: str, mailid: str, part_index: int) -> FileResponse:
        """
        Asynchronously retrieves a specific part of a mail for a given user, identified by the mail's unique ID and the part index.

        Args:
            user (str): The username of the individual whose mail part is to be retrieved.
            mailid (str): The unique identifier for the mail whose part is to be retrieved.
            part_index (int): The index of the part within the mail to retrieve.

        Returns:
            FileResponse: A file response object containing the specified part of the mail.

        Raises:
            HTTPException: If the user or the specified mail part does not exist, an HTTP exception could be raised.

       """
        tb = self.mail_archives.mail_archives[user]
        mail = Mail(user=user, mailid=mailid, tb=tb, debug=self.debug)
        response = mail.part_as_fileresponse(part_index)
        return response


class ThunderbirdSolution(InputWebSolution):
    """
    the Thunderbird Mail solution
    """

    def __init__(self, webserver: ThunderbirdWebserver, client: Client):
        """
        Initialize the solution

        Calls the constructor of the base solution
        Args:
            webserver (DynamicCompotenceMapWebServer): The webserver instance associated with this context.
            client (Client): The client instance this context is associated with.
        """
        super().__init__(webserver, client)  # Call to the superclass constructor
        self.tb = None
        self.mail_archives=self.webserver.mail_archives

    async def show_mailboxes(self, user: str, profile_key: str):
        """
        Shows a mailboxes for a Thunderbird user profile

        Args:
            user (str): Username for identifying the user profile.
            profile_key (str): Thunderbird profile key.
        """

        def show_ui():
            try:
                if user not in self.mail_archives.mail_archives:
                    ui.html(f"Unknown user {user}")
                    return

                # Initialize the Thunderbird instance for the given user
                self.tb = Thunderbird.get(user)
                # get all mailboxes
                mboxes_view_lod = self.tb.get_synched_mailbox_view_lod()
                self.mboxes_view = ListOfDictsGrid(lod=mboxes_view_lod)
            except Exception as ex:
                self.handle_exception(ex)

        await self.setup_content_div(show_ui)

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

    def update_mailboxes_grid(self,update_lod):
        with self.mailboxes_grid_container:
            self.mailboxes_grid.load_lod(update_lod)
            self.mailboxes_grid.sizeColumnsToFit()

    def run_indexing(self, tb, progress_bar):
        """
        prepare and run indexing of mailboxes
        """
        def update_grid(mailbox,message_count:int):
            """
            """
            index=len(update_lod)+1
            if index==1:
                self.mailboxes_label.text=self.ixs.msg

            mb_record=mailbox.as_view_record(index=index)
            mb_record["count"]=message_count
            update_lod.append(mb_record)
            self.update_mailboxes_grid(update_lod)

        try:
            update_lod = []
            tb.do_create_or_update_index(ixs=self.ixs,progress_bar=progress_bar,callback=update_grid)
        except Exception as ex:
            self.handle_exception(ex)

    def run_prepare_indexing(self):
        try:
            self.tb.prepare_mailboxes_for_indexing(ixs=self.ixs,progress_bar=self.progress_bar)
            update_lod=self.ixs.get_update_lod()
            self.update_mailboxes_grid(update_lod)
        except Exception as ex:
            self.handle_exception(ex)

    async def create_or_update_index(self, user: str, profile_key: str) -> None:
        """
        user interface to start create or updating index
        """
        async def on_prepare():
            """
            Handle the prepare button click
            """
            # force index db update time
            self.tb.index_db_update_time=None
            await run.io_bound(self.run_prepare_indexing)


        async def on_index():
            """
            Handle the reindex button click
            """
            self.ixs.force_create = self.force_create_checkbox.value
            self.ixs.needs_update=True

            await run.io_bound(self.run_indexing, self.tb, progress_bar=self.progress_bar)

        def show_ui():
            """
            show my user interface
            """
            if user not in self.mail_archives.mail_archives:
                ui.html(f"Unknown user {user}")
            else:
                self.user = user
                self.tb = self.mail_archives.mail_archives[user]
                self.ixs=self.tb.get_indexing_state()
                self.progress_bar = NiceguiProgressbar(
                    total=100, desc="updating index", unit="mailboxes"
                )
                with ui.row() as self.header_row:
                    self.state_label=ui.label(self.ixs.state_msg)
                    self.mailboxes_label=ui.label("")
                    self.force_create_checkbox = ui.checkbox("Force Create")
                    self.prepare_button = ui.button("Prepare", on_click=on_prepare)
                    self.reindex_button = ui.button("Reindex", on_click=on_index)
                with ui.row() as self.mailboxes_grid_container:
                    # Create an instance of ListOfDictsGrid to display mailboxes
                    self.mailboxes_grid = ListOfDictsGrid(lod=[])

        await self.setup_content_div(show_ui)
        await run.io_bound(self.run_indexing, self.tb, progress_bar=self.progress_bar)


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
                self.user = user
                self.tb = self.mail_archives.mail_archives[user]
                extensions = {"Folder": ".sbd", "Mailbox": ""}
                self.folder_selector = FileSelector(
                    path=self.tb.local_folders,
                    extensions=extensions,
                    handler=self.on_select_folder,
                )

        await self.setup_content_div(show_ui)

    async def on_select_folder(self, folder_path):
        """
        open the folder
        """
        relative_path = ThunderbirdMailbox.as_relative_path(folder_path)
        url = f"/folder/{self.user}{relative_path}"
        return ui.navigate.to(url, new_tab=True)

    async def show_folder(self, user, folder_path: str):
        """
        show the folder with the given path
        """

        def show_index():
            try:
                index_lod = self.folder_mbox.get_toc_lod_from_sqldb(self.tb.index_db)
                view_lod = ThunderbirdMailbox.to_view_lod(index_lod, user)
                msg_count = self.folder_mbox.mbox.__len__()
                with self.folder_view:
                    self.folder_view.content = f"{msg_count:5} ({folder_path})"
                    self.folder_grid.load_lod(lod=view_lod)
                    self.folder_grid.sizeColumnsToFit()
            except Exception as ex:
                self.handle_exception(ex)

        def show():
            self.tb = Thunderbird.get(user)
            self.folder_mbox = ThunderbirdMailbox(self.tb, folder_path, use_relative_path=True)
            self.folder_view = ui.html()
            self.folder_view.content = f"Loading {self.folder_mbox.relative_folder_path} ..."
            grid_config = GridConfig(key_col="email_index")
            self.folder_grid = ListOfDictsGrid(config=grid_config)
            self.folder_grid.html_columns = [1, 2]

        await self.setup_content_div(show)
        await run.io_bound(show_index)


    async def showMail(self, user: str, mailid: str):
        """
        Show the given mail of the given user.
        """

        def get_mail():
            """
            Get the mail.
            """
            try:
                mail = self.webserver.get_mail(user, mailid)
                # check mail has a message
                if not mail.msg:
                    title_section = self.sections["title"]
                    html_markup = mail.as_html_error_msg()
                    title_section.content_div.content = html_markup
                else:
                    for section_name, section in self.sections.items():
                        html_markup = mail.as_html_section(section_name)
                        with section.content_div:
                            section.content_div.content = html_markup
                            section.update()
            except Exception as ex:
                self.handle_exception(ex)

        async def show():
            try:
                self.sections = {}
                section_names = [
                    "title",
                    "info",
                    "wiki",
                    "headers",
                    "text",
                    "html",
                    "parts",
                ]
                visible_sections = {
                    "title",
                    "info",
                    "text",
                    "html",
                }  # Sections to be initially visible
                self.progress_bar = NiceguiProgressbar(100, "load mail", "steps")
                if user in self.mail_archives.mail_archives:
                    for section_name in section_names:
                        # Set initial visibility based on the section name
                        show_content = section_name in visible_sections
                        self.sections[section_name] = HideShow(
                            (section_name, section_name),
                            show_content=show_content,
                            lazy_init=True,
                        )
                    for section_name in section_names:
                        self.sections[section_name].set_content(ui.html())

                else:
                    self.mail_view = ui.html(f"unknown user {user}")
            except Exception as ex:
                self.handle_exception(ex)

        await self.setup_content_div(show)
        await run.io_bound(get_mail)

    def setup_content(self):
        """
        select users
        """
        self.view_lod = self.mail_archives.as_view_lod()
        self.lod_grid = ListOfDictsGrid(lod=self.view_lod)

    async def home(self):
        """
        provide the main content page

        """
        await self.setup_content_div(self.setup_content)
