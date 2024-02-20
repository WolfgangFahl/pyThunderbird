#!/usr/bin/env python3
"""
A script to download files from GitHub, preserving the original commit dates.

Created on 2023-12-12

@author: wf

Usage:
python github.py <profile_directory> <url1> <url2> ...
"""
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

import requests


@dataclass
class GithubFile:
    """
    Data class to hold the details for each github file.

    Attributes:
        url (str): The URL to the file.
        repo (str): The repository name.
        file_path (str): The relative path of the file.
        status_msg (Optional[str]): A status message regarding the download.
        timestamp (Optional[datetime]): The timestamp of the last commit.
        timestamp_iso (Optional[str]): timestamp in iso format
    """

    url: str
    repo: str = field(init=False)
    branch: str = field(init=False)
    file_path: str = field(init=False)
    raw_url: str = field(init=False)
    status_msg: Optional[str] = None
    timestamp: Optional[datetime] = None
    timestamp_iso: Optional[str] = None  # ISO format timestamp

    def __post_init__(self):
        """
        Post-initialization to parse the URL and construct the raw URL for downloading the file.
        """
        pattern = r"https://github\.com/(?P<repo>[^/]+/[^/]+)/blob/(?P<branch>[^/]+)/(?P<file_path>.+)"
        match = re.match(pattern, self.url)
        if match:
            self.repo = match.group("repo")
            self.branch = match.group("branch")
            self.file_path = match.group("file_path")
            self.raw_url = f"https://raw.githubusercontent.com/{self.repo}/{self.branch}/{self.file_path}"
        else:
            raise ValueError(f"URL does not match expected format: {self.url}")

    def to_json(self):
        """Converts the me to JSON."""
        return json.dumps(asdict(self), default=str)

    def get_commit_date(self) -> Optional[str]:
        """
        Gets the last commit date of my file from GitHub
        and sets my timestamp accordingly

        """
        api_url = (
            f"https://api.github.com/repos/{self.repo}/commits?path={self.file_path}"
        )
        response = requests.get(api_url)
        if response.status_code == 200:
            commits = response.json()
            commit = commits[0]["commit"]["committer"]["date"]
            self.timestamp = datetime.strptime(commit, "%Y-%m-%dT%H:%M:%SZ")
            self.timestamp_iso = self.timestamp.isoformat()
        else:
            msg = f"can't access commit date for {self.repo}:{self.file_path}"
            self.add_msg(msg)
            self.timestamp = None

    def set_file_timestamp(self, target_dir: str):
        """Sets the file's timestamp based on the commit date."""
        if self.timestamp and isinstance(self.timestamp, datetime):
            mod_time = self.timestamp.timestamp()
            local_path = os.path.join(target_dir, self.file_path)
            if os.path.isfile(local_path):
                os.utime(local_path, (mod_time, mod_time))

    def add_msg(self, msg):
        if self.status_msg is None:
            self.status_msg = ""
            delim = ""
        else:
            delim = "\n"
        self.status_msg = f"{self.status_msg}{delim}{msg}"


class GithubDownloader:
    """Downloader for github files with timestamp preservation."""

    def __init__(self, target_dir: str, urls: List[str]) -> None:
        """
        Initializes the GithubDownloader with a target directory and a dictionary mapping URLs to repositories.

        Args:
            target_dir: The directory where files will be downloaded.
            urls: A dictionary of URLs to their corresponding repositories.
        """
        self.target_dir = target_dir
        os.makedirs(target_dir, exist_ok=True)
        self.file_map = {}
        for url in urls:
            self.file_map[url] = GithubFile(url)

    def download_files(self) -> None:
        """Downloads all files based on the prepared download gh_fileurations."""
        for _url, gh_file in self.file_map.items():
            self.download_file(gh_file)

    def download_file(self, gh_file: GithubFile) -> None:
        """
        Downloads a file based on the provided download gh_fileuration.

        Args:
            gh_file(GithubFile): the download url, repo,filepath etc
        """
        response = requests.get(gh_file.raw_url)
        checkmark = "✅" if response.status_code == 200 else "❌"
        status_str = "successful" if response.status_code == 200 else "failed"
        gh_file.add_msg(f"{checkmark} Download {status_str}")

        if response.status_code == 200:
            local_path = os.path.join(self.target_dir, gh_file.file_path)
            # Create parent directory if it doesn't exist
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            with open(local_path, "wb") as file:
                file.write(response.content)
            gh_file.get_commit_date()
            gh_file.set_file_timestamp(self.target_dir)

    def set_file_timestamp(self, filepath: str, timestamp: str) -> None:
        """Sets the file's timestamp.

        Args:
            filepath: The path to the local file.
            timestamp: The timestamp string in ISO format.
        """
        timestamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
        mod_time = timestamp.timestamp()
        os.utime(filepath, (mod_time, mod_time))

    @classmethod
    def from_args(cls, args: list) -> "GithubDownloader":
        """
        Creates an instance of GithubDownloader from command line arguments.

        Args:
            args: A list of command line arguments.

        Returns:
            An instance of GithubDownloader.

        Raises:
            ValueError: If insufficient arguments are provided.
        """
        if len(args) < 2:
            raise ValueError("Insufficient arguments. Expected at least 2 arguments.")
        target_dir = args[0]
        urls = args[1:]
        return cls(target_dir, urls)


def main():
    """
    Main function to run the script.
    """
    downloader = GithubDownloader.from_args(sys.argv[1:])
    downloader.download_files()


if __name__ == "__main__":
    main()
