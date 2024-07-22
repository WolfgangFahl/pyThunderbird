"""
Created on 2023-12-06

@author: wf
"""
from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Thunderbird
from thunderbird.search import MailSearch


class TestMailSearch(BaseThunderbirdTest):
    """
    Test the MailSearch class for constructing SQL queries based on search criteria.
    """

    def test_construct_query(self):
        """
        Test the construct_query method of MailSearch.
        """
        if self.is_developer():
            user = self.user
            subject = "iSAQB"
            expected_count = 9000
        else:
            user = self.mock_user
            subject = "Wikidata Digest"
            expected_count = 1

        tb = Thunderbird.get(user)
        # if we are in a public CI environment
        # we need to create an index database
        if self.inPublicCI() and not tb.index_db_exists():
            ixs=tb.create_or_update_index()
            ixs.show_index_report()
        search_dict = {
            "Subject": f"{subject}",
            "From": "",
            "To": "",
        }
        mail_search = MailSearch(
            webserver=None, tb=tb, search_dict=search_dict, with_ui=False
        )
        sql_query, query_params = mail_search.construct_query(search_dict)
        debug = self.debug
        # debug=True
        if debug:
            print(sql_query)
            print(query_params)
        self.assertTrue("SELECT * FROM mail_index WHERE subject LIKE ?" in sql_query)
        self.assertTrue(f"%{subject}%" in query_params)
        search_results = tb.index_db.query(sql_query, query_params)
        found_mails = len(search_results)
        if debug:
            print(f"found {found_mails} mails")
        self.assertTrue(found_mails >= expected_count)
