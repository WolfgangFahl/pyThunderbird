"""
Created on 2023-12-06

@author: wf
"""
from ngwidgets.dict_edit import DictEdit
from ngwidgets.lod_grid import ListOfDictsGrid
from nicegui import ui
from nicegui.events import GenericEventArguments

from thunderbird.mail import ThunderbirdMailbox


class IndexQuery:
    """
    UI-independent construction of mail_index SQL queries with
    substring (LIKE) semantics per field - shared by the interactive
    search and the /api/search endpoint
    https://github.com/WolfgangFahl/pyThunderbird/issues/43

    The search is based on the `index_db` table structure:

    CREATE TABLE mail_index (
      folder_path TEXT,
      message_id TEXT,
      sender TEXT,
      recipient TEXT,
      subject TEXT,
      date TEXT,
      iso_date TEXT,
      email_index INTEGER,
      start_pos INTEGER,
      stop_pos INTEGER,
      error TEXT
    )
    """

    columns = ["subject", "sender", "recipient", "message_id"]

    @classmethod
    def construct_query(cls, criteria: dict) -> (str, list):
        """
        Construct the SQL query for the given column-space criteria.

        Args:
            criteria (dict): mail_index column name -> substring to match;
                empty/None values are ignored.

        Returns:
            tuple: A tuple containing the SQL query string and the list of parameters.
        """
        sql_query = "SELECT * FROM mail_index WHERE "
        query_conditions = []
        query_params = []

        for column in cls.columns:
            value = criteria.get(column)
            if value:
                query_conditions.append(f"{column} LIKE ?")
                query_params.append(f"%{value}%")

        if not query_conditions:
            sql_query = "SELECT * FROM mail_index"
        else:
            sql_query += " AND ".join(query_conditions)

        return sql_query, query_params


class MailSearch:
    """
    utility module to search Thunderbird mails
    https://github.com/WolfgangFahl/pyThunderbird/issues/15
    """

    def __init__(
        self,
        webserver,
        tb,
        search_dict: dict,
        with_ui: bool = True,
        result_limit: int = 1000,
    ):
        """
        Constructor.

        Args:
            webserver: The webserver instance.
            tb: The Thunderbird instance.
            search_dict (dict): The dictionary containing search parameters.
            result_limit(int): maximum number of mails to be displayed
            with_ui (bool): If True, sets up the UI components.
        """
        self.webserver = webserver
        self.tb = tb
        self.result_limit = result_limit
        if with_ui:
            self.setup_form(search_dict)

    def setup_form(self, search_dict: dict):
        """
        Set up a search form.

        Args:
            search_dict (dict): The dictionary containing search parameters.
        """
        self.dict_edit = DictEdit(search_dict)
        self.dict_edit.expansion.open()
        self.search_button = (
            ui.button("search", icon="search", color="primary")
            .tooltip("search thunderbird mails")
            .on("click", handler=self.on_search)
        )
        self.search_summary = ui.html()
        self.search_results_grid = ListOfDictsGrid(lod=[])

    # Mapping from search form keys to SQL table columns
    column_mappings = {
        "Subject": "subject",
        "From": "sender",
        "To": "recipient",
        "Message-ID:": "message_id",
    }

    def construct_query(self, search_criteria: dict) -> (str, list):
        """
        Construct the SQL query based on the search form criteria.

        Args:
            search_criteria (dict): The dictionary containing search parameters
                keyed by form labels (Subject, From, To, Message-ID:).

        Returns:
            tuple: A tuple containing the SQL query string and the list of parameters.
        """
        criteria = {}
        for field, value in search_criteria.items():
            column = self.column_mappings.get(field)
            if column and value:
                criteria[column] = value
        sql_query, query_params = IndexQuery.construct_query(criteria)
        return sql_query, query_params

    async def on_search(self, _event: GenericEventArguments):
        """
        Handle the search based on the search form criteria.

        Args:
            event (GenericEventArguments): Event arguments (unused in this method).
        """
        try:
            search_criteria = self.dict_edit.d
            sql_query, query_params = self.construct_query(search_criteria)
            search_results = self.tb.index_db.query(sql_query, query_params)
            result_count = len(search_results)
            msg = f"{result_count} messages found"
            if result_count > self.result_limit:
                msg = f"too many results: {result_count}>{self.result_limit}"
            self.search_summary.content = msg
            search_results = search_results[: self.result_limit]
            view_lod = ThunderbirdMailbox.to_view_lod(search_results, user=self.tb.user)

            self.search_results_grid.load_lod(view_lod)
            self.search_results_grid.update()
        except Exception as ex:
            self.webserver.handle_exception(ex)
