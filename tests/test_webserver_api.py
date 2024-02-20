"""
Created on 2023-12-19

@author: wf
"""
import time

from ngwidgets.webserver_test import WebserverTest

from thunderbird.mail_cmd import ThunderbirdMailCmd
from thunderbird.tb_webserver import ThunderbirdWebserver


class TestAPI(WebserverTest):
    """
    test the Thunderbird Server RESTFul API
    """

    def setUp(self, debug=True, profile=True):
        """
        setUp the testcase by starting the webserver
        """
        server_class = ThunderbirdWebserver
        cmd_class = ThunderbirdMailCmd
        WebserverTest.setUp(
            self,
            debug=debug,
            profile=profile,
            server_class=server_class,
            cmd_class=cmd_class,
        )

        self.wait_for_configure_run()

    def wait_for_configure_run(self, timeout=10):
        """
        Wait until the configure_run method has been called and the mail_archives attribute is set.

        Args:
            timeout (int): Maximum time to wait in seconds.
        """
        start_time = time.time()
        while not hasattr(self.ws, "mail_archives") or self.ws.mail_archives is None:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise TimeoutError("Timed out waiting for configure_run to complete.")
            time.sleep(0.01)  # Wait for a short period before checking again
        if self.debug:
            print(f"configure run done after {int(round(elapsed/1000))} msecs")

    def test_mail_endpoints(self):
        """
        Test various /mail/{user}/{mailid}.wiki endpoints.
        """
        test_cases = [
            ("invalid_user", "invalid_id", 404, "Mail with id"),
        ]
        if not self.inPublicCI():
            test_cases.append(
                (
                    "wf",
                    "0c2e98c4-1bc7-9ce9-f80e-07fbed60e554@apache.org",
                    200,
                    "{{mail",
                ),
            )
        for user, mail_id, expected_status, substring in test_cases:
            path = f"/mail/{user}/{mail_id}.wiki"
            response = self.get_response(path, expected_status)
            if expected_status != 404:
                text = response.content.decode()
                if self.debug:
                    print(f"{user} {mail_id}\n{text}")

                self.assertIn(substring, text)
