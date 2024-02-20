"""
Created on 25.11.2023

@author: wf
"""
import json

from ngwidgets.basetest import Profiler

from tests.base_thunderbird import BaseThunderbirdTest
from thunderbird.mail import Thunderbird


class TestGloda(BaseThunderbirdTest):
    """
    test the thunderbird global database access
    """

    def test_performance(self):
        """
        test the query performance
        """
        debug = self.debug
        message_id = "67c9445016a73fa63e5b18c6c386b5a1@www.medimops.de"
        queries = [
            "select * from messages where headerMessageID=(?)",
            """select m.*,f.* 
from  messages m join
folderLocations f on m.folderId=f.id
where m.headerMessageID==(?)""",
        ]
        if self.is_developer():
            tb = Thunderbird.get(self.user)
            if debug:
                print(tb.to_dict())
            for index, sql_query in enumerate(queries, start=1):
                profiler = Profiler(f"query {index}")
                params = (message_id,)
                records = tb.query(sql_query, params)
                if debug:
                    print(f"{index+1}:")
                    print(json.dumps(records, indent=2))
                profiler.time()
                pass
