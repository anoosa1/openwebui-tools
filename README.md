# OpenWebUI Tools

This repository contains my tools for OpenWebUI.

## Modules

### 1. Files.py
**Functionality:**
* Manage files and directories on a WebDAV Server.
* **Features:**
    * List, create, and delete directories.
    * Upload (create) and delete files.
    * Read text and JSON files.
    * Copy and move files/directories.
    * **Search:** Supports RFC 5323 server-side searching for files.

### 2. Calendar.py
**Functionality:**
* Manage your Calendar and Tasks.
* **Features:**
    * **Events:** Create, read, update, delete, and search calendar events.
    * **Tasks:** Create new tasks, mark tasks as completed, and edit task details.
    * **Query:** Fetch all events or events within specific time ranges.

### 3. Contacts.py
**Functionality:**
* Manage your address book contacts.
* **Features:**
    * Search for contacts by name or other fields.
    * Create new contacts.
    * Read full contact details (vCard).
    * Edit existing contacts with full field access.

---

### Deprecated
* **`DAV.py`**: This all-in-one module is now **deprecated**. Its functionality has been split into the three modules listed above for better modularity. Doesn't have the latest functionality.
