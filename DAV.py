"""
title: DAV (WebDAV, CalDAV, CardDAV)
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.4
license: GPLv3
description: A comprehensive tool for OpenWebUI to manage files, calendars, and contacts using WebDAV, CalDAV, and CardDAV. Version 1.4 adds full read/edit access to all contact and event fields.
"""

import requests
import json
import xml.etree.ElementTree as ET
import uuid
import re
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
        """Wrapper for requests to handle retries and validation."""
        if not url:
            class ConfigErrorResponse:
                status_code = 400
                text = "Error: Configuration missing. Please set the URL (WEBDAV_BASE_URL, CALDAV_URL, or CARDDAV_URL) in the Tool Settings (Valves)."
                content = text.encode('utf-8')
            return ConfigErrorResponse()

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
    # HELPERS
    # =========================================================================

    def _unfold_lines(self, text: str) -> List[str]:
        """Unfolds lines (VCF/ICS line folding: lines starting with space are continuations)."""
        lines = text.splitlines()
        unfolded = []
        for line in lines:
            if line.startswith(" ") or line.startswith("\t"):
                if unfolded:
                    unfolded[-1] += line[1:]
            else:
                unfolded.append(line)
        return unfolded

    def _parse_dav_text(self, text: str) -> str:
        """Generic parser for VCF/ICS that returns ALL fields."""
        lines = self._unfold_lines(text)
        data = {}
        
        for line in lines:
            if ":" in line:
                # Split Key and Value
                # Handle grouping (e.g. item1.EMAIL:...) -> remove group
                parts = line.split(":", 1)
                key_part = parts[0]
                value = parts[1]
                
                # Clean Key (remove parameters like ;TYPE=HOME)
                key_raw = key_part.split(";")[0]
                
                # Remove grouping prefix if present (item1.ADR -> ADR)
                if "." in key_raw:
                    key_raw = key_raw.split(".")[-1]

                # Store
                if key_raw not in data:
                    data[key_raw] = value
                else:
                    # Handle multiple values (e.g. multiple emails)
                    if isinstance(data[key_raw], list):
                        data[key_raw].append(value)
                    else:
                        data[key_raw] = [data[key_raw], value]
        
        return json.dumps(data)

    def _apply_edits(self, original_text: str, updates: Dict[str, str]) -> str:
        """
        Smartly edits a VCF/ICS file.
        1. Keeps lines that are NOT being updated (preserves photos, binary, etc).
        2. Removes lines for keys that ARE being updated.
        3. Appends the new values.
        """
        lines = self._unfold_lines(original_text)
        new_lines = []
        
        # Keys to remove (normalized)
        keys_to_update = set(updates.keys())
        
        for line in lines:
            if ":" in line:
                key_part = line.split(":", 1)[0]
                key_raw = key_part.split(";")[0] # remove params
                if "." in key_raw: key_raw = key_raw.split(".")[-1] # remove group
                
                # If this line's key is in our update list, SKIP it (we will replace it)
                if key_raw in keys_to_update:
                    continue
            
            # Keep line if not being updated
            new_lines.append(line)
        
        # Insert new values before the END tag
        end_tag = new_lines.pop() if new_lines and new_lines[-1].startswith("END:") else "END:VCARD"
        
        for key, value in updates.items():
            # Handle list of values for a single key
            if isinstance(value, list):
                for v in value:
                     new_lines.append(f"{key}:{v}")
            else:
                new_lines.append(f"{key}:{value}")
                
        new_lines.append(end_tag)
        return "\n".join(new_lines)

    # =========================================================================
    # WEBDAV MODULE (Files)
    # =========================================================================

    def list_files(self, path: str = "") -> str:
        """List files and directories."""
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

    def create_directory(self, path: str) -> str: return self._handle_response(self._request("MKCOL", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [201])
    def delete_directory(self, path: str) -> str: return self._handle_response(self._request("DELETE", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [204])
    def create_file(self, path: str, content: str) -> str: return self._handle_response(self._request("PUT", self._join_url(self.valves.WEBDAV_BASE_URL, path), data=content.encode('utf-8')), [201, 204])
    def delete_file(self, path: str) -> str: return self._handle_response(self._request("DELETE", self._join_url(self.valves.WEBDAV_BASE_URL, path)), [204])
    
    def read_file(self, path: str) -> str:
        response = self._request("GET", self._join_url(self.valves.WEBDAV_BASE_URL, path))
        return response.text if response.status_code == 200 else f"Error: {response.status_code}"

    def read_json_file(self, path: str) -> str:
        c = self.read_file(path)
        try: return json.dumps(json.loads(c), indent=2)
        except: return "Error: Invalid JSON"

    def write_json_file(self, path: str, data: str) -> str:
        try: return self.create_file(path, json.dumps(json.loads(data), indent=2))
        except: return "Error: Invalid JSON input"

    def copy_file(self, src: str, dest: str) -> str: return self._handle_response(self._request("COPY", self._join_url(self.valves.WEBDAV_BASE_URL, src), headers={"Destination": self._join_url(self.valves.WEBDAV_BASE_URL, dest)}), [201, 204])
    def move_file(self, src: str, dest: str) -> str: return self._handle_response(self._request("MOVE", self._join_url(self.valves.WEBDAV_BASE_URL, src), headers={"Destination": self._join_url(self.valves.WEBDAV_BASE_URL, dest)}), [201, 204])
    
    def search_files(self, query: str) -> str:
        """Search files (RFC 5323)."""
        file_url = self.valves.WEBDAV_BASE_URL
        root_url = file_url.split("/files/")[0] + "/" if file_url and "/files/" in file_url else file_url
        
        xml_q = f"""<?xml version="1.0" encoding="UTF-8"?><d:searchrequest xmlns:d="DAV:"><d:basicsearch><d:select><d:prop><d:displayname/></d:prop></d:select><d:from><d:scope><d:href>{{}}</d:href><d:depth>infinity</d:depth></d:scope></d:from><d:where><d:like><d:prop><d:displayname/></d:prop><d:literal>%{query}%</d:literal></d:like></d:where></d:basicsearch></d:searchrequest>"""
        
        def do_search(u, s): return self._request("SEARCH", u, data=xml_q.format(s), headers={"Content-Type": "text/xml"})
        
        resp = do_search(file_url, file_url)
        if resp.status_code in [501, 404, 405] and root_url != file_url: resp = do_search(root_url, file_url)
        
        if resp.status_code >= 400:
            # Fallback
            files = self.list_files("")
            return "\n".join([l for l in files.split('\n') if query.lower() in l.lower()]) if "Error" not in files else f"Search Error: {resp.status_code}"
            
        try:
            root = ET.fromstring(resp.content)
            return "\n".join([unquote(r.find('.//d:href', {'d':'DAV:'}).text) for r in root.findall('.//d:response', {'d':'DAV:'})]) or "No matches."
        except Exception as e: return str(e)

    # =========================================================================
    # CALDAV MODULE
    # =========================================================================

    def get_events(self, start: str = None, end: str = None) -> str:
        """Get events in range (YYYYMMDDThhmmssZ)."""
        if not start: start = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        if not end: 
            from datetime import timedelta
            end = (datetime.now() + timedelta(days=30)).strftime("%Y%m%dT%H%M%SZ")
            
        xml = f"""<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag /><c:calendar-data /></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"""
        return self._extract_calendar_data(self._request("REPORT", self.valves.CALDAV_URL, data=xml, headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}))

    def get_all_events(self) -> str:
        xml = """<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag /><c:calendar-data /></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT" /></c:comp-filter></c:filter></c:calendar-query>"""
        return self._extract_calendar_data(self._request("REPORT", self.valves.CALDAV_URL, data=xml, headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"}))

    def _extract_calendar_data(self, response):
        if response.status_code >= 400: return f"Error: {response.status_code}"
        try:
            root = ET.fromstring(response.content)
            # Use the new generic parser for every event found
            return str([self._parse_dav_text(node.text) for node in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data")])
        except Exception as e: return str(e)

    def read_event(self, filename: str) -> str:
        """Reads a specific event file and returns all fields as JSON."""
        url = self._join_url(self.valves.CALDAV_URL, filename)
        response = self._request("GET", url)
        if response.status_code != 200: return f"Error: {response.status_code}"
        return self._parse_dav_text(response.text)

    def edit_event(self, filename: str, updates_json: str) -> str:
        """
        Edit an event. 
        Args:
            filename: The UID.ics filename.
            updates_json: JSON string of fields to update (e.g. '{"SUMMARY": "New Title", "DESCRIPTION": "Notes"}').
        """
        url = self._join_url(self.valves.CALDAV_URL, filename)
        
        # 1. Get Existing
        response = self._request("GET", url)
        if response.status_code != 200: return f"Error reading event: {response.status_code}"
        original_text = response.text

        # 2. Apply Edits
        try:
            updates = json.loads(updates_json)
            new_content = self._apply_edits(original_text, updates)
        except Exception as e:
            return f"Error processing updates: {str(e)}"

        # 3. Save
        put_resp = self._request("PUT", url, data=new_content.encode('utf-8'), headers={"Content-Type": "text/calendar"})
        return self._handle_response(put_resp, [201, 204])

    def new_event(self, summary: str, start: str, end: str) -> str:
        uid = str(uuid.uuid4())
        content = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//AI Tool//EN\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART:{start}\nDTEND:{end}\nSUMMARY:{summary}\nEND:VEVENT\nEND:VCALENDAR"
        return self._handle_response(self._request("PUT", self._join_url(self.valves.CALDAV_URL, f"{uid}.ics"), data=content, headers={"Content-Type": "text/calendar"}), [201, 204])

    def delete_event(self, filename: str) -> str:
        return self._handle_response(self._request("DELETE", self._join_url(self.valves.CALDAV_URL, filename)))

    def search_events(self, query: str) -> str:
        all_ev = self.get_all_events()
        try:
            # Basic text search on the JSON string representation
            events = [json.loads(e) for e in eval(all_ev)]
            return json.dumps([e for e in events if any(query.lower() in str(v).lower() for v in e.values())])
        except: return "Search Error"

    # =========================================================================
    # CARDDAV MODULE
    # =========================================================================

    def read_contact(self, filename: str) -> str:
        """Reads a specific contact file and returns ALL fields as JSON."""
        url = self._join_url(self.valves.CARDDAV_URL, filename)
        response = self._request("GET", url)
        if response.status_code != 200: return f"Error: {response.status_code}"
        return self._parse_dav_text(response.text)

    def edit_contact(self, filename: str, updates_json: str) -> str:
        """
        Edit a contact.
        Args:
            filename: The UID.vcf filename.
            updates_json: JSON string of fields to update (e.g. '{"FN": "New Name", "EMAIL": "new@mail.com"}').
        """
        url = self._join_url(self.valves.CARDDAV_URL, filename)
        
        # 1. Get Existing
        response = self._request("GET", url)
        if response.status_code != 200: return f"Error reading contact: {response.status_code}"
        original_text = response.text

        # 2. Apply Edits
        try:
            updates = json.loads(updates_json)
            new_content = self._apply_edits(original_text, updates)
        except Exception as e:
            return f"Error processing updates: {str(e)}"

        # 3. Save
        put_resp = self._request("PUT", url, data=new_content.encode('utf-8'), headers={"Content-Type": "text/vcard"})
        return self._handle_response(put_resp, [201, 204])

    def new_contact(self, fn: str, email: str, tel: str = "") -> str:
        uid = str(uuid.uuid4())
        content = f"BEGIN:VCARD\nVERSION:3.0\nPRODID:-//AI Tool//EN\nUID:{uid}\nFN:{fn}\nEMAIL:{email}\nTEL:{tel}\nEND:VCARD"
        return self._handle_response(self._request("PUT", self._join_url(self.valves.CARDDAV_URL, f"{uid}.vcf"), data=content, headers={"Content-Type": "text/vcard"}), [201, 204])

    def delete_contact(self, filename: str) -> str:
        return self._handle_response(self._request("DELETE", self._join_url(self.valves.CARDDAV_URL, filename)))

    def search_contacts(self, query: str) -> str:
        xml = """<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag /><c:address-data /></d:prop><c:filter><c:prop-filter name="FN"/></c:filter></c:addressbook-query>"""
        resp = self._request("REPORT", self.valves.CARDDAV_URL, data=xml, headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
        if resp.status_code >= 400: return f"Error: {resp.status_code}"
        try:
            root = ET.fromstring(resp.content)
            # Use generic parser to search all fields
            matches = []
            q = query.lower()
            for node in root.findall(".//{urn:ietf:params:xml:ns:carddav}address-data"):
                data = self._parse_dav_text(node.text)
                if q in data.lower(): matches.append(data)
            return str(matches) if matches else "No matches."
        except Exception as e: return str(e)
