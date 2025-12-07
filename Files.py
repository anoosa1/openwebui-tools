"""
title: WebDAV File Manager
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.0
license: GPLv3
description: Manage files and directories on a WebDAV server (Nextcloud, OwnCloud, etc.). Features include file search (RFC 5323), read/write, and directory management.
"""

import requests
import json
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class Tools:
    class Valves(BaseModel):
        WEBDAV_BASE_URL: str = Field(
            default="", description="Base URL for WebDAV files (e.g. https://nextcloud.com/remote.php/dav/files/user/)"
        )
        USERNAME: str = Field(default="", description="DAV Username")
        PASSWORD: str = Field(default="", description="DAV Password or App Password")
        MAX_RETRIES: int = Field(default=3, description="Retry attempts for connection failures.")

    def __init__(self):
        self.valves = self.Valves()

    def _get_auth(self):
        return (self.valves.USERNAME, self.valves.PASSWORD)

    def _join_url(self, base, path):
        return base.rstrip('/') + '/' + path.lstrip('/')

    def _handle_response(self, response, success_codes=[200, 201, 204, 207]):
        if response.status_code in success_codes:
            return f"Success: {response.status_code}"
        try:
            return f"Error {response.status_code}: {response.text}"
        except:
            return f"Error {response.status_code}"

    def _request(self, method: str, url: str, **kwargs):
        if not url: return "Error: WEBDAV_BASE_URL is not configured."
        try:
            retry_strategy = Retry(
                total=self.valves.MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "PROPFIND", "MKCOL", "COPY", "MOVE", "SEARCH"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            with requests.Session() as http:
                http.mount("https://", adapter)
                http.mount("http://", adapter)
                return http.request(method, url, auth=self._get_auth(), **kwargs)
        except Exception as e:
            class Dummy:
                status_code = 503
                text = str(e)
            return Dummy()

    # --- FILE OPERATIONS ---

    def list_files(self, path: str = "") -> str:
        """
        List files and directories at the given path.
        :param path: The directory path to list (relative to base URL). Leave empty for root.
        :return: A list of file and directory names found at the location.
        """
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("PROPFIND", url, headers={"Depth": "1"})
        
        if response.status_code >= 400: return f"Error: {response.status_code} - {response.text}"
        
        try:
            root = ET.fromstring(response.content)
            files = []
            ns = {'d': 'DAV:'}
            for r in root.findall('.//d:response', ns):
                href = unquote(r.find('.//d:href', ns).text)
                is_dir = r.find('.//d:resourcetype/d:collection', ns) is not None
                name = href.rstrip('/').split('/')[-1]
                if name: files.append(f"{'[DIR]' if is_dir else '[FILE]'} {name}")
            return "\n".join(files)
        except Exception as e: return f"Exception: {str(e)}"

    def create_directory(self, path: str) -> str:
        """
        Create a new directory.
        :param path: The path of the new directory to create.
        :return: Success message or error code.
        """
        return self._handle_response(self._request("MKCOL", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [201])

    def delete_directory(self, path: str) -> str:
        """
        Delete a directory.
        :param path: The path of the directory to delete.
        :return: Success message or error code.
        """
        return self._handle_response(self._request("DELETE", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [204])

    def create_file(self, path: str, content: str) -> str:
        """
        Create a new file with text content.
        :param path: The path where the file should be created (including filename).
        :param content: The text content to write to the file.
        :return: Success message or error code.
        """
        return self._handle_response(self._request("PUT", self._join_url(self.valves.WEBDAV_BASE_URL, path), data=content.encode('utf-8')), [201, 204])

    def delete_file(self, path: str) -> str:
        """
        Delete a file.
        :param path: The path of the file to delete.
        :return: Success message or error code.
        """
        return self._handle_response(self._request("DELETE", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [204])

    def read_file(self, path: str) -> str:
        """
        Read the content of a text file.
        :param path: The path of the file to read.
        :return: The content of the file as a string.
        """
        response = self._request("GET", self._join_url(self.valves.WEBDAV_BASE_URL, path))
        return response.text if response.status_code == 200 else f"Error: {response.status_code}"

    def read_json_file(self, path: str) -> str:
        """
        Read a JSON file and return its content formatted as a string.
        :param path: The path of the JSON file to read.
        :return: A JSON string representation of the file content.
        """
        try: return json.dumps(json.loads(self.read_file(path)), indent=2)
        except: return "Error: Invalid JSON"

    def write_json_file(self, path: str, data: str) -> str:
        """
        Write data to a JSON file.
        :param path: The path where the JSON file should be saved.
        :param data: The JSON string data to write.
        :return: Success message or error code.
        """
        try: return self.create_file(path, json.dumps(json.loads(data), indent=2))
        except: return "Error: Invalid JSON input"

    def copy_file(self, src: str, dest: str) -> str:
        """
        Copy a file from one location to another.
        :param src: The source file path.
        :param dest: The destination file path.
        :return: Success message or error code.
        """
        headers = {"Destination": self._join_url(self.valves.WEBDAV_BASE_URL, dest)}
        return self._handle_response(self._request("COPY", self._join_url(self.valves.WEBDAV_BASE_URL, src), headers=headers), [201, 204])

    def move_file(self, src: str, dest: str) -> str:
        """
        Move a file from one location to another.
        :param src: The source file path.
        :param dest: The destination file path.
        :return: Success message or error code.
        """
        headers = {"Destination": self._join_url(self.valves.WEBDAV_BASE_URL, dest)}
        return self._handle_response(self._request("MOVE", self._join_url(self.valves.WEBDAV_BASE_URL, src), headers=headers), [201, 204])

    def copy_directory(self, src: str, dest: str) -> str:
        """
        Copy a directory and its contents.
        :param src: The source directory path.
        :param dest: The destination directory path.
        :return: Success message or error code.
        """
        return self.copy_file(src, dest)

    def move_directory(self, src: str, dest: str) -> str:
        """
        Move a directory and its contents.
        :param src: The source directory path.
        :param dest: The destination directory path.
        :return: Success message or error code.
        """
        return self.move_file(src, dest)

    def is_file(self, path: str) -> str:
        """
        Check if a path exists and is a file.
        :param path: The path to check.
        :return: 'True' if it is a file, 'False' otherwise.
        """
        return self._check_type(path, False)
    
    def is_directory(self, path: str) -> str:
        """
        Check if a path exists and is a directory.
        :param path: The path to check.
        :return: 'True' if it is a directory, 'False' otherwise.
        """
        return self._check_type(path, True)

    def _check_type(self, path, expect_col):
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        resp = self._request("PROPFIND", url, headers={"Depth": "0"})
        if resp.status_code >= 400: return "False"
        try:
            root = ET.fromstring(resp.content)
            is_col = root.find('.//d:resourcetype/d:collection', {'d': 'DAV:'}) is not None
            return str(is_col == expect_col)
        except: return "False"

    def search_files(self, query: str) -> str:
        """
        Search for files matching a query string.
        :param query: The partial filename to search for.
        :return: A list of matching file paths.
        """
        file_url = self.valves.WEBDAV_BASE_URL
        root_url = file_url.split("/files/")[0] + "/" if file_url and "/files/" in file_url else file_url
        xml_q = f"""<?xml version="1.0" encoding="UTF-8"?><d:searchrequest xmlns:d="DAV:"><d:basicsearch><d:select><d:prop><d:displayname/></d:prop></d:select><d:from><d:scope><d:href>{{}}</d:href><d:depth>infinity</d:depth></d:scope></d:from><d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>%{query}%</d:literal></d:like></d:where></d:basicsearch></d:searchrequest>"""
        
        def do_search(u, s): return self._request("SEARCH", u, data=xml_q.format(s), headers={"Content-Type": "text/xml"})
        
        resp = do_search(file_url, file_url)
        if resp.status_code in [501, 404, 405] and root_url != file_url: resp = do_search(root_url, file_url)
        
        if resp.status_code >= 400:
            files = self.list_files("")
            return "\n".join([l for l in files.split('\n') if query.lower() in l.lower()]) if "Error" not in files else f"Search Error: {resp.status_code}"
            
        try:
            root = ET.fromstring(resp.content)
            return "\n".join([unquote(r.find('.//d:href', {'d':'DAV:'}).text) for r in root.findall('.//d:response', {'d':'DAV:'})]) or "No matches."
        except Exception as e: return str(e)

# Usage
# files = tools.list_files("Documents/Projects")
# tools.create_directory("Documents/NewProject")
# tools.delete_directory("Documents/OldProject")
# tools.create_file("notes.txt", "Meeting notes content here.")
# tools.delete_file("notes.txt")
# content = tools.read_file("config.txt")
# json_data = tools.read_json_file("settings.json")
# tools.write_json_file("settings.json", '{"theme": "dark"}')
# tools.copy_file("source.txt", "backup/source_copy.txt")
# tools.move_file("source.txt", "archive/source.txt")
# tools.copy_directory("images", "backup/images")
# tools.move_directory("temp_images", "images")
# is_file = tools.is_file("notes.txt")
# is_dir = tools.is_directory("Documents")
# search_results = tools.search_files("report")
