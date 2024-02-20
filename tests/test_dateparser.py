"""
Created on 2023-12-03

@author: wf
"""

import json
import os

from ngwidgets.basetest import Basetest
from ngwidgets.dateparser import DateParser

from thunderbird.mail import Thunderbird


class TestDateParser(Basetest):
    """
    test date parser
    """

    def test_dateparser(self):
        """
        test the dateparser by reading test cases from a JSON file
        """
        date_parser = DateParser()
        config_path = Thunderbird.get_config_path()
        mail_json_path = os.path.join(config_path, "mail-errors.json")
        if not os.path.isfile(mail_json_path):
            return
        # Read test cases from JSON file
        with open(mail_json_path, "r") as file:
            test_cases = json.load(file)

        failed = 0
        total = 0
        for test_case in test_cases:
            date_input = test_case["date"]
            try:
                total += 1
                # Attempt to parse the date
                result = date_parser.parse_date(date_input)
            except Exception as e:
                failed += 1
                print(date_input)
        # Calculate and print the percentage of failed cases
        failure_rate = (failed / total) * 100
        print(f"{failed}/{total} ({failure_rate:.2f}%) failed")
