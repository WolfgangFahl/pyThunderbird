"""
Created on 2023-11-13

@author: wf
"""
import json
from dataclasses import asdict
from datetime import datetime
from unittest.mock import patch

from ngwidgets.basetest import Basetest

from thunderbird.github import GithubDownloader, GithubFile


class TestGithubDownloader(Basetest):
    """
    test the GibhubDownloader
    """

    def setUp(self, debug=False, profile=True):
        Basetest.setUp(self, debug=debug, profile=profile)
        # List of test URLs with their corresponding repositories and file paths
        self.test_urls = [
            (
                "https://github.com/catmin/inetsim/blob/master/data/pop3/sample.mbox",
                "catmin/inetsim",
                "data/pop3/sample.mbox",
            ),
            (
                "https://github.com/hoffmangroup/segway-mailing-list-archives/blob/master/segway-announce.mbox",
                "hoffmangroup/segway-mailing-list-archives",
                "segway-announce.mbox",
            ),
            (
                "https://github.com/hoffmangroup/segway-mailing-list-archives/blob/master/segway-users.mbox",
                "hoffmangroup/segway-mailing-list-archives",
                "segway-users.mbox",
            ),
        ]
        self.target_dir = "/tmp/test_ghget"

    def test_github_files(self):
        """
        Test the from_url method of GithubFile.
        """
        for url, expected_repo, expected_file_path in self.test_urls:
            gh_file = GithubFile(url)
            self.assertEqual(
                gh_file.repo, expected_repo, f"Repo mismatch for URL: {url}"
            )
            self.assertEqual(
                gh_file.file_path,
                expected_file_path,
                f"File path mismatch for URL: {url}",
            )

    @patch("thunderbird.github.requests.get")
    def test_github_download_mocked(self, mock_get):
        """
        Test that the downloader correctly updates the status and timestamp in the Downloadgh_file.
        """
        # Setup mock response
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.content = b"Test content"
        mock_response.json.return_value = [
            {"commit": {"committer": {"date": "2023-01-01T12:00:00Z"}}}
        ]
        self.check_downloader()

    def test_github_download(self):
        if not self.inPublicCI():
            self.check_downloader()

    def check_downloader(self):
        """
        check the GithubDownloader for my urls
        """
        urls = [url for url, _, _ in self.test_urls]
        downloader = GithubDownloader(self.target_dir, urls)
        downloader.download_files()

        debug = self.debug
        debug = True
        if debug:
            for url, gh_file in downloader.file_map.items():
                print(json.dumps(asdict(gh_file), indent=2, default=str))

        for url, repo, file_path in self.test_urls:
            gh_file = downloader.file_map[url]
            self.assertIsInstance(gh_file, GithubFile)
            self.assertEqual(gh_file.repo, repo)
            self.assertEqual(gh_file.file_path, file_path)
            self.assertIn("✅", gh_file.status_msg)
            self.assertIsInstance(gh_file.timestamp, datetime)
