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

    Note: WebserverTest starts a fresh server per test method on the same test
    port, and the previous one is not guaranteed to release it before the next
    setUp binds - so this class keeps a single test method on purpose.
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

    def test_endpoints(self):
        """
        Test the .wiki mail endpoint and the machine-readable /api/* endpoints (#39).
        """
        # --- machine-readable JSON API (#39) ---
        status = self.get_response("/api/status", 200).json()
        if self.debug:
            print(status)
        self.assertEqual(status["status"], "ok")
        self.assertIn("sso", status)

        version = self.get_response("/api/version", 200).json()
        self.assertEqual(version["name"], "pyThunderbird")

        # machine-readable version of the home-page overview (#40)
        archives = self.get_response("/api/archives", 200).json()
        self.assertIn("count", archives)
        self.assertIsInstance(archives["archives"], list)
        for record in archives["archives"]:
            self.assertIn("user", record)
            self.assertIn("gloda_updated", record)
            self.assertIn("index_updated", record)
            # index health verdict so an agent can spot a stale/missing index
            self.assertIn("index_state", record)
            self.assertIn(record["index_state"], ("ok", "stale", "missing"))

        # the new /api/* routes must be discoverable in OpenAPI so they show at /docs
        paths = self.get_response("/openapi.json", 200).json().get("paths", {})
        for expected in [
            "/api/status",
            "/api/archives",
            "/api/mail/{user}/{mailid}",
            "/api/search/{user}",
            "/api/index/{user}/status",
            "/api/folders/{user}",
        ]:
            self.assertIn(expected, paths, f"missing OpenAPI path {expected}")

        # --- /api/search with per-field LIKE parameters (#43) ---
        # unknown user -> 404; no criteria -> 400
        self.get_response("/api/search/invalid_user?subject=x", 404)
        if not self.inPublicCI():
            self.get_response("/api/search/wf", 400)
            search = self.get_response("/api/search/wf?subject=iSAQB", 200).json()
            self.assertGreaterEqual(search["count"], 1)
            self.assertIn("hits", search)
            for hit in search["hits"]:
                self.assertIn("iSAQB".lower(), hit["subject"].lower())
                self.assertIn("folder_path", hit)
                self.assertNotIn("start_pos", hit)

        # --- the existing .wiki mail endpoint ---
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
