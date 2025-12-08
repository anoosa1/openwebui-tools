"""
title: CardDAV Contacts
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.2
license: GPLv3
description: Manage Contacts via CardDAV. Search, create, and edit contact details with full field access.
"""

import requests
import json
import xml.etree.ElementTree as ET
import uuid
from typing import List, Dict
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class Tools:
    class Valves(BaseModel):
        CARDDAV_URL: str = Field(
            default="", description="URL for the specific Address Book (e.g. .../addressbooks/users/user/contacts/)"
        )
        USERNAME: str = Field(default="", description="DAV Username")
        PASSWORD: str = Field(default="", description="DAV Password or App Password")
        MAX_RETRIES: int = Field(default=3, description="Retry attempts.")

    def __init__(self):
        self.valves = self.Valves()

    def _get_auth(self): return (self.valves.USERNAME, self.valves.PASSWORD)
    def _join_url(self, base, path): return base.rstrip('/') + '/' + path.lstrip('/')

    def _request(self, method: str, url: str, **kwargs):
        if not url: return "Error: CARDDAV_URL is not configured."
        try:
            retry = Retry(total=self.valves.MAX_RETRIES, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["HEAD", "GET", "PUT", "DELETE", "REPORT"])
            adapter = HTTPAdapter(max_retries=retry)
            with requests.Session() as http:
                http.mount("https://", adapter)
                return http.request(method, url, auth=self._get_auth(), **kwargs)
        except Exception as e:
            class Dummy: status_code=503; text=str(e)
            return Dummy()

    def _handle_response(self, response, success=[200, 201, 204]):
        if response.status_code in success: return f"Success: {response.status_code}"
        return f"Error {response.status_code}: {response.text}"

    # --- PARSING HELPERS ---

    def _unfold(self, text):
        lines, unfolded = text.splitlines(), []
        for l in lines:
            if l.startswith(" ") or l.startswith("\t"): 
                if unfolded: unfolded[-1] += l[1:]
            else: unfolded.append(l)
        return unfolded

    def _parse_dav(self, text):
        lines, data = self._unfold(text), {}
        for l in lines:
            if ":" in l:
                k, v = l.split(":", 1)
                k = k.split(";")[0]
                if k not in data: data[k] = v
                elif isinstance(data[k], list): data[k].append(v)
                else: data[k] = [data[k], v]
        return json.dumps(data)

    def _apply_edits(self, original, updates):
        lines, new_lines = self._unfold(original), []
        keys = set(updates.keys())
        for l in lines:
            k = l.split(":", 1)[0].split(";")[0]
            if k not in keys: new_lines.append(l)
        
        final_lines, inserted = [], False
        for l in new_lines:
            if l.strip() == "END:VCARD" and not inserted:
                for k, v in updates.items():
                    if isinstance(v, list):
                        for i in v: final_lines.append(f"{k}:{i}")
                    else: final_lines.append(f"{k}:{v}")
                inserted = True
            final_lines.append(l)
        return "\n".join(final_lines)

    # --- CONTACT OPERATIONS ---

    def read_contact(self, filename: str) -> str:
        """
        Read full details of a contact.
        :param filename: The filename (UID.vcf) of the contact.
        :return: The full content of the contact in JSON format.
        """
        resp = self._request("GET", self._join_url(self.valves.CARDDAV_URL, filename))
        return self._parse_dav(resp.text) if resp.status_code == 200 else f"Error: {resp.status_code}"

    def new_contact(self, contact_json: str) -> str:
        """
        Create a new contact.
        :param contact_json: JSON string of fields (e.g. {"FN": "Name", "EMAIL": "e@mail.com"}).
        :return: Success message or error code.
        """
        try: data = json.loads(contact_json)
        except: return "Error: Invalid JSON"

        uid = str(uuid.uuid4())
        lines = ["BEGIN:VCARD", "VERSION:3.0", "PRODID:-//AI Tool//EN", f"UID:{uid}"]
        for k, v in data.items():
            if isinstance(v, list):
                for i in v: lines.append(f"{k}:{i}")
            else: lines.append(f"{k}:{v}")
        lines.append("END:VCARD")
        return self._handle_response(self._request("PUT", self._join_url(self.valves.CARDDAV_URL, f"{uid}.vcf"), data="\n".join(lines), headers={"Content-Type":"text/vcard"}))

    def edit_contact(self, filename: str, updates_json: str) -> str:
        """
        Edit an existing contact.
        :param filename: The filename (UID.vcf) of the contact.
        :param updates_json: A JSON string of fields to update (e.g. {"TEL": "1234567890"}).
        :return: Success message or error code.
        """
        url = self._join_url(self.valves.CARDDAV_URL, filename)
        orig = self._request("GET", url)
        if orig.status_code != 200: return "Error reading contact"
        try: new_c = self._apply_edits(orig.text, json.loads(updates_json))
        except Exception as e: return str(e)
        return self._handle_response(self._request("PUT", url, data=new_c.encode('utf-8'), headers={"Content-Type":"text/vcard"}))

    def delete_contact(self, query: str) -> str:
        """
        Delete a contact by searching for it first.
        :param query: The text to search for (e.g. Name). Fails if multiple matches are found.
        :return: Success message or error code.
        """
        # 1. Search
        search_res = self.search_contacts(query)
        if search_res == "No matches.": return "Error: Contact not found."
        
        try:
            # 2. Parse matches
            matches = json.loads(search_res)
            if len(matches) > 1:
                return f"Error: Ambiguous query. Found {len(matches)} matches. Please be more specific."
            
            # 3. Get UID from the single match
            contact = json.loads(matches[0])
            uid = contact.get("UID")
            if not uid: return "Error: Contact data corrupted (No UID)."
            
            # 4. Delete
            return self._handle_response(self._request("DELETE", self._join_url(self.valves.CARDDAV_URL, f"{uid}.vcf")))
        except Exception as e:
            return f"Error processing deletion: {str(e)}"

    def search_contacts(self, query: str) -> str:
        """
        Search for contacts matching a query.
        :param query: The text to search for (e.g. name or email).
        :return: A JSON list of matching contacts (as JSON strings).
        """
        xml = """<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag /><c:address-data /></d:prop><c:filter><c:prop-filter name="FN"/></c:filter></c:addressbook-query>"""
        resp = self._request("REPORT", self.valves.CARDDAV_URL, data=xml, headers={"Depth":"1", "Content-Type":"application/xml; charset=utf-8"})
        if resp.status_code >= 400: return f"Error: {resp.status_code}"
        try:
            root = ET.fromstring(resp.content)
            matches = []
            q = query.lower()
            for node in root.findall(".//{urn:ietf:params:xml:ns:carddav}address-data"):
                data = self._parse_dav(node.text)
                if q in data.lower(): matches.append(data)
            return json.dumps(matches) if matches else "No matches."
        except Exception as e: return str(e)

# Usage
# contact_info = tools.read_contact("uuid.vcf")
# tools.new_contact('{"FN": "Alice Smith", "EMAIL": "alice@example.com", "TEL": "555-0101"}')
# tools.edit_contact("uuid.vcf", '{"TEL": "555-0102", "ORG": "New Company"}')
# tools.delete_contact("Alice Smith")
# results = tools.search_contacts("Alice")
