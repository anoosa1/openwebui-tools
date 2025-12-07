"""
title: DAV (WebDAV, CalDAV, CardDAV)
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.3
license: GPLv3
description: A comprehensive tool for OpenWebUI to manage files, calendars, and contacts using WebDAV, CalDAV, and CardDAV.
"""

import requests
import json
import xml.etree.ElementTree as ET
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Union
from urllib.parse import unquote
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class Tools:
    class Valves(BaseModel):
        WEBDAV_BASE_URL: str = Field(
            default="", description="Base URL for WebDAV files (e.g. https://nextcloud.com/remote.php/dav/files/user/)"
        )
        CALDAV_URL: str = Field(
            default="", description="URL for the specific Calendar (e.g. .../calendars/user/personal/)"
        )
        CARDDAV_URL: str = Field(
            default="", description="URL for the specific Address Book (e.g. .../addressbooks/users/user/contacts/)"
        )
        USERNAME: str = Field(default="", description="DAV Username")
        PASSWORD: str = Field(default="", description="DAV Password or App Password")
        MAX_RETRIES: int = Field(default=3, description="Number of times to retry connecting if the server is unreachable.")

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
        """
        Wrapper for requests to handle retries and validation.
        """
        # 1. Validation: Check if URL is configured
        if not url:
            class ConfigErrorResponse:
                status_code = 400
                text = "Error: Configuration missing. Please set the URL (WEBDAV_BASE_URL, CALDAV_URL, or CARDDAV_URL) in the Tool Settings (Valves)."
                content = text.encode('utf-8')
            return ConfigErrorResponse()

        # 2. Connection Logic
        try:
            retry_strategy = Retry(
                total=self.valves.MAX_RETRIES,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "PROPFIND", "MKCOL", "COPY", "MOVE", "REPORT", "SEARCH"]
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            
            with requests.Session() as http:
                http.mount("https://", adapter)
                http.mount("http://", adapter)
                return http.request(method, url, auth=self._get_auth(), **kwargs)

        except Exception as e:
            class DummyResponse:
                status_code = 503
                text = f"Connection failed after {self.valves.MAX_RETRIES} retries. details: {str(e)}"
                content = text.encode('utf-8')
            return DummyResponse()

    # =========================================================================
    # WEBDAV MODULE
    # =========================================================================

    def list_files(self, path: str = "") -> str:
        """
        List files and directories at the given path using WebDAV PROPFIND.
        """
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        headers = {"Depth": "1"}
        
        response = self._request("PROPFIND", url, headers=headers)
        
        if response.status_code >= 400:
            return f"Error listing files: {response.status_code} - {response.text}"
        
        try:
            root = ET.fromstring(response.content)
            files = []
            ns = {'d': 'DAV:'}
            for response_node in root.findall('.//d:response', ns):
                href = response_node.find('.//d:href', ns).text
                res_type = response_node.find('.//d:resourcetype', ns)
                is_dir = res_type.find('.//d:collection', ns) is not None
                name = href.rstrip('/').split('/')[-1]
                # Decode URL encoded names
                name = unquote(name)
                if name: 
                    files.append(f"{'[DIR]' if is_dir else '[FILE]'} {name}")
            return "\n".join(files)
        except Exception as e:
            return f"Exception listing files: {str(e)}"

    def create_directory(self, path: str) -> str:
        """Create a new directory at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("MKCOL", url)
        return self._handle_response(response, [201])

    def delete_directory(self, path: str) -> str:
        """Delete a directory at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("DELETE", url)
        return self._handle_response(response, [204])

    def create_file(self, path: str, content: str) -> str:
        """Create a new file with text content at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("PUT", url, data=content.encode('utf-8'))
        return self._handle_response(response, [201, 204])

    def delete_file(self, path: str) -> str:
        """Delete a file at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("DELETE", url)
        return self._handle_response(response, [204])

    def read_file(self, path: str) -> str:
        """Read the content of a text file."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = self._request("GET", url)
        if response.status_code == 200:
            return response.text
        return f"Error reading file: {response.status_code} - {response.text}"

    def read_json_file(self, path: str) -> str:
        """Read a JSON file and return its content as a stringified dictionary."""
        content = self.read_file(path)
        if content.startswith("Error"):
            return content
        try:
            data = json.loads(content)
            return json.dumps(data, indent=2)
        except json.JSONDecodeError:
            return "Error: File content is not valid JSON."

    def write_json_file(self, path: str, data: str) -> str:
        """Write a JSON string to a file."""
        try:
            # Validate JSON before writing
            json_obj = json.loads(data)
            content = json.dumps(json_obj, indent=2)
            return self.create_file(path, content)
        except json.JSONDecodeError:
            return "Error: Input data is not valid JSON."

    def copy_file(self, source_path: str, dest_path: str) -> str:
        """Copy a file from source to destination."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, source_path)
        dest_url = self._join_url(self.valves.WEBDAV_BASE_URL, dest_path)
        headers = {"Destination": dest_url}
        response = self._request("COPY", url, headers=headers)
        return self._handle_response(response, [201, 204])

    def move_file(self, source_path: str, dest_path: str) -> str:
        """Move a file from source to destination."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, source_path)
        dest_url = self._join_url(self.valves.WEBDAV_BASE_URL, dest_path)
        headers = {"Destination": dest_url}
        response = self._request("MOVE", url, headers=headers)
        return self._handle_response(response, [201, 204])

    def copy_directory(self, source_path: str, dest_path: str) -> str:
        """Copy a directory (and all contents) from source to destination."""
        return self.copy_file(source_path, dest_path)

    def move_directory(self, source_path: str, dest_path: str) -> str:
        """Move a directory from source to destination."""
        return self.move_file(source_path, dest_path)

    def is_file(self, path: str) -> str:
        """Check if a path exists and is a file."""
        return self._check_resource_type(path, expect_collection=False)

    def is_directory(self, path: str) -> str:
        """Check if a path exists and is a directory."""
        return self._check_resource_type(path, expect_collection=True)

    def _check_resource_type(self, path, expect_collection):
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        headers = {"Depth": "0"}
        response = self._request("PROPFIND", url, headers=headers)
        if response.status_code >= 400:
            return "False (Not found or error)"
        
        try:
            root = ET.fromstring(response.content)
            ns = {'d': 'DAV:'}
            res_type = root.find('.//d:resourcetype', ns)
            is_collection = res_type.find('.//d:collection', ns) is not None
            return str(is_collection == expect_collection)
        except:
            return "False (Error parsing)"

    def search_files(self, query: str) -> str:
        """
        Search for files containing the query string using WebDAV SEARCH (RFC 5323).
        Automatically handles Nextcloud 501 errors by attempting search at Root DAV URL.
        """
        # 1. Determine URLs
        file_url = self.valves.WEBDAV_BASE_URL
        # specific logic to find the root DAV url for Nextcloud (remove /files/user)
        if file_url and "/files/" in file_url:
            root_url = file_url.split("/files/")[0] + "/"
        else:
            root_url = file_url

        # 2. Define the Search Helper
        def perform_search(target_url, search_scope):
            xml_query = f"""<?xml version="1.0" encoding="UTF-8"?>
            <d:searchrequest xmlns:d="DAV:">
                <d:basicsearch>
                    <d:select>
                        <d:prop>
                            <d:displayname/>
                        </d:prop>
                    </d:select>
                    <d:from>
                        <d:scope>
                            <d:href>{search_scope}</d:href>
                            <d:depth>infinity</d:depth>
                        </d:scope>
                    </d:from>
                    <d:where>
                        <d:like>
                            <d:prop>
                                <d:displayname/>
                            </d:prop>
                            <d:literal>%{query}%</d:literal>
                        </d:like>
                    </d:where>
                </d:basicsearch>
            </d:searchrequest>
            """
            headers = {"Content-Type": "text/xml"}
            return self._request("SEARCH", target_url, data=xml_query, headers=headers)

        # 3. Attempt Search on the configured File URL first
        response = perform_search(file_url, file_url)

        # 4. Fallback: If 501 (Not Implemented) or 404/405, try the Root DAV URL
        if response.status_code in [501, 404, 405] and root_url != file_url:
            # Search against ROOT, but scope to FILE URL
            response = perform_search(root_url, file_url)

        # 5. Process Response
        if response.status_code >= 400:
             # Final Fallback: Manual client-side filtering
            try:
                # If server search fails, list root files and filter (Depth 1 only)
                all_files = self.list_files("") 
                if "Error" in all_files: return f"Search failed: {response.status_code} - {response.text}"
                
                lines = all_files.split('\n')
                filtered = [line for line in lines if query.lower() in line.lower()]
                return "\n".join(filtered) if filtered else "No matches found (Client-side fallback)."
            except:
                return f"Search failed: {response.status_code} - {response.text}"

        try:
            root = ET.fromstring(response.content)
            ns = {'d': 'DAV:'}
            results = []
            for response_node in root.findall('.//d:response', ns):
                href = response_node.find('.//d:href', ns).text
                # Decode URL-encoded filenames (e.g. %20 -> space)
                readable_name = unquote(href)
                results.append(readable_name)
            return "\n".join(results) if results else "No matches found."
        except Exception as e:
            return f"Error parsing search results: {str(e)}"

    # =========================================================================
    # CALDAV MODULE
    # =========================================================================

    def parse_ics_data(self, ics_text: str) -> str:
        """Parses raw ICS text to return a readable summary."""
        lines = ics_text.splitlines()
        data = {}
        for line in lines:
            if ":" in line:
                key, val = line.split(":", 1)
                if key in ["SUMMARY", "DTSTART", "DTEND", "DESCRIPTION", "LOCATION"]:
                    data[key] = val
        return json.dumps(data)

    def get_events(self, start: str = None, end: str = None) -> str:
        """
        Get events in a time range. Dates must be YYYYMMDDThhmmssZ.
        """
        if not start:
            start = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        if not end:
            from datetime import timedelta
            end = (datetime.now() + timedelta(days=30)).strftime("%Y%m%dT%H%M%SZ")

        xml_query = f"""
        <c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
            <d:prop>
                <d:getetag />
                <c:calendar-data />
            </d:prop>
            <c:filter>
                <c:comp-filter name="VCALENDAR">
                    <c:comp-filter name="VEVENT">
                        <c:time-range start="{start}" end="{end}"/>
                    </c:comp-filter>
                </c:comp-filter>
            </c:filter>
        </c:calendar-query>
        """
        headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
        response = self._request("REPORT", self.valves.CALDAV_URL, data=xml_query, headers=headers)
        
        return self._extract_calendar_data(response)

    def get_all_events(self) -> str:
        """Get all events from the calendar."""
        xml_query = """
        <c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
            <d:prop>
                <d:getetag />
                <c:calendar-data />
            </d:prop>
            <c:filter>
                <c:comp-filter name="VCALENDAR">
                    <c:comp-filter name="VEVENT" />
                </c:comp-filter>
            </c:filter>
        </c:calendar-query>
        """
        headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
        response = self._request("REPORT", self.valves.CALDAV_URL, data=xml_query, headers=headers)
        return self._extract_calendar_data(response)

    def _extract_calendar_data(self, response):
        if response.status_code >= 400:
            return f"Error fetching events: {response.status_code} - {response.text}"
        
        try:
            root = ET.fromstring(response.content)
            events = []
            for node in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data"):
                events.append(self.parse_ics_data(node.text))
            return str(events)
        except Exception as e:
            return f"Error parsing XML: {str(e)}"

    def new_event(self, summary: str, start_time: str, end_time: str) -> str:
        """Create a new event."""
        uid = str(uuid.uuid4())
        ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//OpenWebUI//Tool//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{datetime.now().strftime("%Y%m%dT%H%M%SZ")}
DTSTART:{start_time}
DTEND:{end_time}
SUMMARY:{summary}
END:VEVENT
END:VCALENDAR"""
        
        url = self._join_url(self.valves.CALDAV_URL, f"{uid}.ics")
        response = self._request("PUT", url, data=ics_content, headers={"Content-Type": "text/calendar"})
        return self._handle_response(response, [201, 204])

    def delete_event(self, filename: str) -> str:
        """Delete an event by its filename."""
        url = self._join_url(self.valves.CALDAV_URL, filename)
        response = self._request("DELETE", url)
        return self._handle_response(response)

    def search_events(self, query: str) -> str:
        """Fetches all events and filters them (case-insensitive)."""
        all_events_str = self.get_all_events()
        import ast
        try:
            events = ast.literal_eval(all_events_str)
            matches = []
            query_lower = query.lower()
            for event_str in events:
                event = json.loads(event_str)
                if any(query_lower in str(v).lower() for v in event.values()):
                    matches.append(event)
            return str(matches)
        except:
            return "Error processing events for search."

    # =========================================================================
    # CARDDAV MODULE
    # =========================================================================

    def parse_vcf_data(self, vcf_text: str) -> str:
        """Parses raw VCF text to return key contact info."""
        lines = vcf_text.splitlines()
        data = {}
        for line in lines:
            if ":" in line:
                parts = line.split(":", 1)
                key_raw = parts[0].split(";")[0]
                val = parts[1]
                if key_raw in ["FN", "EMAIL", "TEL", "N", "ORG"]:
                    if key_raw not in data:
                        data[key_raw] = val
                    else:
                        data[key_raw] += f", {val}"
        return json.dumps(data)

    def new_contact(self, fn: str, email: str, tel: str = "") -> str:
        """Create a new contact."""
        uid = str(uuid.uuid4())
        vcf_content = f"""BEGIN:VCARD
VERSION:3.0
PRODID:-//OpenWebUI//Tool//EN
UID:{uid}
FN:{fn}
EMAIL:{email}
TEL:{tel}
END:VCARD"""
        
        url = self._join_url(self.valves.CARDDAV_URL, f"{uid}.vcf")
        response = self._request("PUT", url, data=vcf_content, headers={"Content-Type": "text/vcard"})
        return self._handle_response(response, [201, 204])

    def delete_contact(self, filename: str) -> str:
        """Delete a contact by filename."""
        url = self._join_url(self.valves.CARDDAV_URL, filename)
        response = self._request("DELETE", url)
        return self._handle_response(response)

    def search_contacts(self, query: str) -> str:
        """Fetches all contacts and searches for the query string."""
        xml_query = """
        <c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav">
            <d:prop>
                <d:getetag />
                <c:address-data />
            </d:prop>
            <c:filter>
                <c:prop-filter name="FN"/> 
            </c:filter>
        </c:addressbook-query>
        """
        headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
        response = self._request("REPORT", self.valves.CARDDAV_URL, data=xml_query, headers=headers)
        
        if response.status_code >= 400:
            return f"Error fetching contacts: {response.status_code} - {response.text}"

        try:
            root = ET.fromstring(response.content)
            matches = []
            query_lower = query.lower()
            
            for node in root.findall(".//{urn:ietf:params:xml:ns:carddav}address-data"):
                vcf_text = node.text
                if query_lower in vcf_text.lower():
                    matches.append(self.parse_vcf_data(vcf_text))
            
            return str(matches) if matches else "No contacts found matching query."
        except Exception as e:
            return f"Error parsing contacts: {str(e)}"
