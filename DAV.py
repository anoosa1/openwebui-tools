"""
title: DAV (WebDAV, CalDAV, CardDAV)
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.0
license: GPLv3
description: A comprehensive tool for OpenWebUI to manage files, calendars, and contacts using WebDAV, CalDAV, and CardDAV protocols.
"""

import requests
import json
import xml.etree.ElementTree as ET
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Union
from pydantic import BaseModel, Field

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

    # =========================================================================
    # WEBDAV MODULE
    # =========================================================================

    def list_files(self, path: str = "") -> str:
        """
        List files and directories at the given path using WebDAV PROPFIND.
        """
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        headers = {"Depth": "1"}
        try:
            response = requests.request("PROPFIND", url, auth=self._get_auth(), headers=headers)
            if response.status_code >= 400:
                return f"Error listing files: {response.status_code}"
            
            # Parse XML
            root = ET.fromstring(response.content)
            files = []
            ns = {'d': 'DAV:'}
            for response_node in root.findall('.//d:response', ns):
                href = response_node.find('.//d:href', ns).text
                res_type = response_node.find('.//d:resourcetype', ns)
                is_dir = res_type.find('.//d:collection', ns) is not None
                name = href.rstrip('/').split('/')[-1]
                if name: # Skip empty (root)
                    files.append(f"{'[DIR]' if is_dir else '[FILE]'} {name}")
            return "\n".join(files)
        except Exception as e:
            return f"Exception listing files: {str(e)}"

    def create_directory(self, path: str) -> str:
        """Create a new directory at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = requests.request("MKCOL", url, auth=self._get_auth())
        return self._handle_response(response, [201])

    def delete_directory(self, path: str) -> str:
        """Delete a directory at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = requests.delete(url, auth=self._get_auth())
        return self._handle_response(response, [204])

    def create_file(self, path: str, content: str) -> str:
        """Create a new file with text content at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = requests.put(url, data=content.encode('utf-8'), auth=self._get_auth())
        return self._handle_response(response, [201, 204])

    def delete_file(self, path: str) -> str:
        """Delete a file at the specified path."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = requests.delete(url, auth=self._get_auth())
        return self._handle_response(response, [204])

    def read_file(self, path: str) -> str:
        """Read the content of a text file."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, path)
        response = requests.get(url, auth=self._get_auth())
        if response.status_code == 200:
            return response.text
        return f"Error reading file: {response.status_code}"

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
        response = requests.request("COPY", url, headers=headers, auth=self._get_auth())
        return self._handle_response(response, [201, 204])

    def move_file(self, source_path: str, dest_path: str) -> str:
        """Move a file from source to destination."""
        url = self._join_url(self.valves.WEBDAV_BASE_URL, source_path)
        dest_url = self._join_url(self.valves.WEBDAV_BASE_URL, dest_path)
        headers = {"Destination": dest_url}
        response = requests.request("MOVE", url, headers=headers, auth=self._get_auth())
        return self._handle_response(response, [201, 204])

    def copy_directory(self, source_path: str, dest_path: str) -> str:
        """Copy a directory (and all contents) from source to destination."""
        # COPY on a collection with Depth: infinity is the default behavior for WebDAV
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
        response = requests.request("PROPFIND", url, auth=self._get_auth(), headers=headers)
        if response.status_code >= 400:
            return "False (Not found or error)"
        
        root = ET.fromstring(response.content)
        ns = {'d': 'DAV:'}
        res_type = root.find('.//d:resourcetype', ns)
        is_collection = res_type.find('.//d:collection', ns) is not None
        
        return str(is_collection == expect_collection)

    def search_files(self, query: str) -> str:
        """
        Search for files containing the query string using WebDAV SEARCH (RFC 5323).
        If the server does not support SEARCH, this might fail.
        """
        url = self.valves.WEBDAV_BASE_URL
        # Constructing a basic DASL search query
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
                        <d:href>{url}</d:href>
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
        response = requests.request("SEARCH", url, data=xml_query, auth=self._get_auth(), headers=headers)
        
        if response.status_code >= 400:
            return f"Search failed (Server might not support RFC 5323): {response.status_code}"

        try:
            root = ET.fromstring(response.content)
            ns = {'d': 'DAV:'}
            results = []
            for response_node in root.findall('.//d:response', ns):
                href = response_node.find('.//d:href', ns).text
                results.append(href)
            return "\n".join(results) if results else "No matches found."
        except:
            return "Error parsing search results."

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
        Get events in a time range. Dates must be YYYYMMDDThhmmssZ (e.g., 20231001T000000Z).
        Default start is now.
        """
        if not start:
            start = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        if not end:
            # Default to 30 days ahead
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
        response = requests.request("REPORT", self.valves.CALDAV_URL, data=xml_query, auth=self._get_auth(), headers=headers)
        
        return self._extract_calendar_data(response)

    def get_all_events(self) -> str:
        """Get all events from the calendar."""
        # Using PROPFIND with Depth 1 to get all files, then we usually filter for .ics
        # Or better, a basic calendar-query without time-range
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
        response = requests.request("REPORT", self.valves.CALDAV_URL, data=xml_query, auth=self._get_auth(), headers=headers)
        return self._extract_calendar_data(response)

    def _extract_calendar_data(self, response):
        if response.status_code >= 400:
            return f"Error fetching events: {response.status_code}"
        
        try:
            root = ET.fromstring(response.content)
            # Namespaces are tricky in CalDAV responses, usually C: is caldav and D: is DAV
            # We search recursively for calendar-data
            events = []
            for node in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data"):
                events.append(self.parse_ics_data(node.text))
            return str(events)
        except Exception as e:
            return f"Error parsing XML: {str(e)}"

    def new_event(self, summary: str, start_time: str, end_time: str) -> str:
        """
        Create a new event. Times format: YYYYMMDDTHHMMSS (local) or with Z for UTC.
        """
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
        response = requests.put(url, data=ics_content, auth=self._get_auth(), headers={"Content-Type": "text/calendar"})
        return self._handle_response(response, [201, 204])

    def delete_event(self, filename: str) -> str:
        """Delete an event by its filename (e.g. uuid.ics)."""
        url = self._join_url(self.valves.CALDAV_URL, filename)
        response = requests.delete(url, auth=self._get_auth())
        return self._handle_response(response)

    def search_events(self, query: str) -> str:
        """
        Fetches all events and filters them (case-insensitive) based on the query string.
        Checks Summary, Description, Location.
        """
        all_events_str = self.get_all_events()
        # all_events_str is a string representation of a list of dicts (roughly)
        # It's cleaner to re-fetch or parse properly, but for the tool:
        import ast
        try:
            events = ast.literal_eval(all_events_str)
            matches = []
            query_lower = query.lower()
            for event_str in events:
                # event_str is a json string inside the list
                event = json.loads(event_str)
                # Check values
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
                key_raw = parts[0].split(";")[0] # remove params like EMAIL;TYPE=HOME
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
        response = requests.put(url, data=vcf_content, auth=self._get_auth(), headers={"Content-Type": "text/vcard"})
        return self._handle_response(response, [201, 204])

    def delete_contact(self, filename: str) -> str:
        """Delete a contact by filename."""
        url = self._join_url(self.valves.CARDDAV_URL, filename)
        response = requests.delete(url, auth=self._get_auth())
        return self._handle_response(response)

    def search_contacts(self, query: str) -> str:
        """
        Fetches all contacts and searches for the query string in any field.
        """
        # CardDAV usually uses REPORT with addressbook-query, but getting all and filtering is easier for generic support
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
        # Note: Some servers accept PROPFIND Depth 1 on addressbook too. Trying addressbook-query first.
        headers = {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}
        response = requests.request("REPORT", self.valves.CARDDAV_URL, data=xml_query, auth=self._get_auth(), headers=headers)
        
        if response.status_code >= 400:
            return f"Error fetching contacts: {response.status_code}"

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
