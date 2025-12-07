"""
title: CalDAV Calendar & Tasks
author: Anas Sherif
email: anas@asherif.xyz
date: 2025-12-07
version: 1.0
license: GPLv3
description: Manage Events and Tasks (VTODO) via CalDAV. Supports creating, editing, completing tasks, and full time-range queries.
"""

import requests
import json
import xml.etree.ElementTree as ET
import uuid
from datetime import datetime
from typing import List, Dict
from pydantic import BaseModel, Field
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class Tools:
    class Valves(BaseModel):
        CALDAV_URL: str = Field(
            default="", description="URL for the specific Calendar (e.g. .../calendars/user/personal/)"
        )
        USERNAME: str = Field(default="", description="DAV Username")
        PASSWORD: str = Field(default="", description="DAV Password or App Password")
        MAX_RETRIES: int = Field(default=3, description="Retry attempts.")

    def __init__(self):
        self.valves = self.Valves()

    def _get_auth(self): return (self.valves.USERNAME, self.valves.PASSWORD)
    def _join_url(self, base, path): return base.rstrip('/') + '/' + path.lstrip('/')

    def _request(self, method: str, url: str, **kwargs):
        if not url: return "Error: CALDAV_URL is not configured."
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
        
        end_tag = "END:VEVENT" if "BEGIN:VEVENT" in original else "END:VTODO"
        final_lines, inserted = [], False
        for l in new_lines:
            if l.strip() == end_tag and not inserted:
                for k, v in updates.items():
                    if isinstance(v, list):
                        for i in v: final_lines.append(f"{k}:{i}")
                    else: final_lines.append(f"{k}:{v}")
                inserted = True
            final_lines.append(l)
        return "\n".join(final_lines)

    # --- EVENTS ---

    def get_events(self, start: str = None, end: str = None) -> str:
        """
        Get events within a specific time range.
        :param start: Start date in YYYYMMDDThhmmssZ format (optional, defaults to now).
        :param end: End date in YYYYMMDDThhmmssZ format (optional, defaults to +30 days).
        :return: A list of events found in the specified range.
        """
        if not start: start = datetime.now().strftime("%Y%m%dT%H%M%SZ")
        if not end: 
            from datetime import timedelta
            end = (datetime.now() + timedelta(days=30)).strftime("%Y%m%dT%H%M%SZ")
        xml = f"""<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag /><c:calendar-data /></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>"""
        return self._extract(self._request("REPORT", self.valves.CALDAV_URL, data=xml, headers={"Depth":"1", "Content-Type":"application/xml; charset=utf-8"}))

    def get_all_events(self) -> str:
        """
        Get all events from the calendar.
        :return: A list of all calendar events.
        """
        xml = """<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag /><c:calendar-data /></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT" /></c:comp-filter></c:filter></c:calendar-query>"""
        return self._extract(self._request("REPORT", self.valves.CALDAV_URL, data=xml, headers={"Depth":"1", "Content-Type":"application/xml; charset=utf-8"}))

    def new_event(self, summary: str, start: str, end: str) -> str:
        """
        Create a new calendar event.
        :param summary: The title/summary of the event.
        :param start: Start time in YYYYMMDDThhmmssZ format.
        :param end: End time in YYYYMMDDThhmmssZ format.
        :return: Success message or error code.
        """
        uid = str(uuid.uuid4())
        c = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//AI Tool//EN\nBEGIN:VEVENT\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nDTSTART:{start}\nDTEND:{end}\nSUMMARY:{summary}\nEND:VEVENT\nEND:VCALENDAR"
        return self._handle_response(self._request("PUT", self._join_url(self.valves.CALDAV_URL, f"{uid}.ics"), data=c, headers={"Content-Type":"text/calendar"}))

    def read_event(self, filename: str) -> str:
        """
        Read the full details of a specific event.
        :param filename: The filename (UID.ics) of the event.
        :return: The full content of the event in JSON format.
        """
        resp = self._request("GET", self._join_url(self.valves.CALDAV_URL, filename))
        return self._parse_dav(resp.text) if resp.status_code == 200 else f"Error: {resp.status_code}"

    def edit_event(self, filename: str, updates_json: str) -> str:
        """
        Edit an existing event.
        :param filename: The filename (UID.ics) of the event.
        :param updates_json: A JSON string of fields to update (e.g. {"SUMMARY": "New Title"}).
        :return: Success message or error code.
        """
        url = self._join_url(self.valves.CALDAV_URL, filename)
        orig = self._request("GET", url)
        if orig.status_code != 200: return "Error reading event"
        try: new_c = self._apply_edits(orig.text, json.loads(updates_json))
        except Exception as e: return str(e)
        return self._handle_response(self._request("PUT", url, data=new_c.encode('utf-8'), headers={"Content-Type":"text/calendar"}))

    def delete_event(self, filename: str) -> str:
        """
        Delete an event.
        :param filename: The filename (UID.ics) of the event to delete.
        :return: Success message or error code.
        """
        return self._handle_response(self._request("DELETE", self._join_url(self.valves.CALDAV_URL, filename)))

    def search_events(self, query: str) -> str:
        """
        Search for events matching a query.
        :param query: The text to search for within event fields.
        :return: A list of matching events.
        """
        all_ev = self.get_all_events()
        try: return json.dumps([e for e in eval(all_ev) if any(query.lower() in str(v).lower() for v in json.loads(e).values())])
        except: return "Search Error"

    # --- TASKS ---

    def get_tasks(self) -> str:
        """
        Get all tasks (VTODO items).
        :return: A list of all tasks from the calendar.
        """
        xml = """<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag /><c:calendar-data /></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VTODO" /></c:comp-filter></c:filter></c:calendar-query>"""
        return self._extract(self._request("REPORT", self.valves.CALDAV_URL, data=xml, headers={"Depth":"1", "Content-Type":"application/xml; charset=utf-8"}))

    def new_task(self, summary: str, due: str = "") -> str:
        """
        Create a new task.
        :param summary: The summary/title of the task.
        :param due: Due date in YYYYMMDDThhmmssZ format (optional).
        :return: Success message or error code.
        """
        uid = str(uuid.uuid4())
        d = f"\nDUE:{due}" if due else ""
        c = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//AI Tool//EN\nBEGIN:VTODO\nUID:{uid}\nDTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}\nSUMMARY:{summary}\nSTATUS:NEEDS-ACTION{d}\nEND:VTODO\nEND:VCALENDAR"
        return self._handle_response(self._request("PUT", self._join_url(self.valves.CALDAV_URL, f"{uid}.ics"), data=c, headers={"Content-Type":"text/calendar"}))

    def edit_task(self, filename: str, updates_json: str) -> str:
        """
        Edit a task.
        :param filename: The filename (UID.ics) of the task.
        :param updates_json: A JSON string of fields to update.
        :return: Success message or error code.
        """
        return self.edit_event(filename, updates_json)
    
    def complete_task(self, filename: str) -> str:
        """
        Mark a task as completed.
        :param filename: The filename (UID.ics) of the task.
        :return: Success message or error code.
        """
        return self.edit_task(filename, json.dumps({"STATUS": "COMPLETED", "PERCENT-COMPLETE": "100"}))

    def delete_task(self, filename: str) -> str:
        """
        Delete a task.
        :param filename: The filename (UID.ics) of the task.
        :return: Success message or error code.
        """
        return self.delete_event(filename)

    def _extract(self, resp):
        if resp.status_code >= 400: return f"Error: {resp.status_code}"
        try:
            root = ET.fromstring(resp.content)
            return str([self._parse_dav(n.text) for n in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data")])
        except Exception as e: return str(e)

# Usage
# events = tools.get_events(start="20251201T000000Z", end="20251231T235959Z")
# all_events = tools.get_all_events()
# tools.new_event("Team Meeting", "20251208T090000Z", "20251208T100000Z")
# details = tools.read_event("12345-uuid.ics")
# tools.edit_event("12345-uuid.ics", '{"SUMMARY": "Rescheduled Meeting"}')
# tools.delete_event("12345-uuid.ics")
# search_result = tools.search_events("Project Launch")
# tasks = tools.get_tasks()
# tools.new_task("Buy groceries", due="20251208T180000Z")
# tools.edit_task("task-uuid.ics", '{"DESCRIPTION": "Milk, Eggs, Bread"}')
# tools.complete_task("task-uuid.ics")
# tools.delete_task("task-uuid.ics")
