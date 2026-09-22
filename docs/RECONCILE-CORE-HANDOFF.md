# RECONCILE-CORE-HANDOFF.md

> **Status (2026-09-21): partially superseded.** The canonical store maps
> identities through `external_refs` (not `identity_map`), and the project's
> direction and boundaries are settled in `docs/adr/` (ADR-0001–0004). The
> legacy `main.py` Google-API entry was retired (ADR-0003); the adapter registry
> now lives in `adapters/__init__.py`. Where
> this spec and the ADRs disagree, the ADRs win; the per-agent sections below
> are retained as design history.

## 0. Project Vision & Orchestrator Handoff

**Project Name:** `reconcile-core`
**Environment:** Arch Linux, `gws` CLI, Python 3.14+
**Goal:** A modular ETL pipeline to reconcile fragmented social identities (LinkedIn, Discord, etc.) into a pristine Google Contacts master list.
**Primary Principle:** Zero-loss reconciliation. Never blindly overwrite data. Use a deterministic truth hierarchy and provide a CLI interface for user resolution.

### Overarching Functional Goals
*   **Single Source of Truth:** Consolidate fragmented contact data into `contacts.google.com`.
*   **Identity Persistence:** Use a local SQLite database to map disparate platform IDs to a single Google `resourceName`.
*   **CLI-Native:** Leverage the `gws` (Google Workspace CLI) for all Google-side operations.
*   **Privilege Escalation:** Use `doas` only for system-level operations; the application should strictly reside in user-space (`$XDG_CONFIG_HOME`, `$XDG_DATA_HOME`).
*   **Formatting:** PEP 8 compliance, strict type hinting, and comprehensive docstrings.

---

## 1. Agent 1: The Architect (Foundation)

**Core Mission:** Define the immutable type-system and interfaces.
**File Responsibility:** `models.py`, `interfaces.py`

### Specifications
*   **Data Models (`models.py`):**
    *   `SocialHandle`: `platform: str`, `username: str`, `url: Optional[str]`, `is_im: bool`.
    *   `StandardContact`: `source_id: str`, `display_name: str`, `handles: List[SocialHandle]`, `emails: List[str]`, `phones: List[str]`, `urls: List[str]`, `imClients: List[str]`, `raw_metadata: Dict`.
    *   `ReconciliationDiff`: `resource_name: str`, `additions: StandardContact`, `collisions: Dict[str, Tuple[any, any]]`.
*   **Interface Contract (`interfaces.py`):**
    *   `BaseAdapter(ABC)`: Must implement `extract(file_path: Path) -> Generator[StandardContact, None, None]`.
    *   `BasePersistence(ABC)`: Must implement `get_resource_name(platform, source_id)`, `set_mapping(platform, source_id, resource_name)`, and `list_unresolved()`.
        *   **Note (ADR-0001/0002):** the mapping target is now a **store entity** via `external_refs`; a Google `resourceName` is stored as the entity's `google` ref, so one entity can carry many platform identities. The method names are retained.
*   **Constraints:** Use Python 3.14+ type hinting (`dataclasses`). No external dependencies (Standard Library only).

---

## 2. Agent 2: The Librarian (Persistence)

**Core Mission:** Manage the Identity Map and SQLite state.
**File Responsibility:** `database.py`

### Specifications
*   **Schema Design:**
    ```sql
    CREATE TABLE identity_map (
        platform TEXT NOT NULL,
        source_id TEXT NOT NULL,
        google_resource_name TEXT NOT NULL,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (platform, source_id)
    );
    CREATE TABLE audit_log (
        event_time TIMESTAMP,
        resource_name TEXT,
        action TEXT,
        delta TEXT
    );
    ```
*   **Logic Requirements:**
    *   Implement "Fuzzy Match" helper: Before asking the user, check the DB for similar names to suggest a `resource_name`.
    *   Provide a "Reset" method to clear mappings for a specific platform.
*   **Arch Specifics:** Initialize DB locally. Default path should be `$XDG_DATA_HOME/reconcile-core/identities.db` or `~/.config/reconcile-core/identities.db`.
    *   **Superseded (ADR-0001–0003):** `identity_map` was replaced by the canonical store's `external_refs`; the default store is now `$XDG_DATA_HOME/reconcile-core/contacts.db` (ADR-0002); and the fuzzy-match helper moves into store-side identity resolution (ADR-0003, roadmap C2).
*   **Constraints:** Use the `sqlite3` standard library. Ensure methods are idempotent.

---

## 3. Agent 3: The Diplomat (Google/GWS I/O)

**Core Mission:** Wrapper for the `gws` binary and state caching.
**File Responsibility:** `google_adapter.py`, `loader.py`

### Specifications
*   **State Cache / Extraction:**
    *   `fetch_all_contacts()`: Run `gws people list-connections --read-mask "names,emailAddresses,urls,imClients"` or `search-contacts` and cache the result in a local JSON or memory dict to avoid repeated API hits.
    *   `get_contact(resource_name)`: Fetch a single contact, specifically capturing the `etag`.
*   **Update Logic (The Loader):**
    *   Implement a wrapper for `gws people update-contact`. Construct the `--body` JSON carefully.
    *   **Concurrency Control:** Correctly handle `etags` returned by Google to prevent clobbering data.
    *   **Rate Limiting:** Handle `429 Too Many Requests` with exponential backoff.
*   **Constraints:** Verify `gws` is in `$PATH` before execution. Do not use Google Discovery API libraries directly; strictly use `subprocess.run` with `capture_output=True` to keep the environment lean.

---

## 4. Agent 4: The Multilingual (Adapters)

**Core Mission:** Platform-specific extraction logic.
**File Responsibility:** `adapters/*.py`

### Specifications
*   **LinkedIn (`adapters/linkedin.py`):**
    *   Input: `Connections.csv`. Extract `First Name`, `Last Name`, and profile `URL`.
    *   `source_id`: The profile slug from the URL (e.g., `nathan-somers-123`).
*   **Discord (`adapters/discord.py`):**
    *   Input: Discord Data Package (JSON). Parse `relationships.json`, filtering for "Friends."
    *   `source_id`: The Discord Snowflake ID.
*   **Matrix (`adapters/matrix.py`):**
    *   Input: Manual list or Element export.
    *   `source_id`: The full MXID (e.g., `@user:matrix.org`).
*   **Generic CSV (`adapters/generic_csv.py`):**
    *   A fallback parser where users can map arbitrary columns to `StandardContact` fields.

---

## 5. Agent 5: The Judge (Reconciler & UX)

**Core Mission:** The interactive CLI logic.
**File Responsibility:** `reconciler.py`, `cli.py` (`main.py` is being retired — ADR-0003)

### Specifications
*   **The Orchestration Loop:**
    1.  Call **Agent 4** to get proposed data (`ProposedContact`).
    2.  Call **Agent 2** to check DB for `resource_name`.
    3.  If found, call **Agent 3** to get current Google state (`CurrentContact`).
    4.  Generate `Diff` via Collision Logic.
    5.  Present the Diff to the user and, upon confirmation, call **Agent 3** to push `PATCH` to Google.
*   **Collision Logic:**
    *   **Union (Automatic):** For `urls` and `imClients`, append new data to existing lists if `Proposed.handle` not in `Current.handles`. Add to `Diff.additions`.
    *   **Conflict (Manual):** If a name or primary email differs (`Proposed.display_name` != `Current.display_name`), add to `Diff.collisions`. Prompt user for input.
*   **CLI UX:**
    *   Use the `rich` library for tables and color-coded diffs (Green for additions, Yellow for changes).
    *   Interactive Prompt: `[A]pply changes, [S]kip, [M]anually Edit?`.
    *   Support a `--dry-run` flag.

---

## 6. Inter-Agent Dependency Map & Protocol

| Phase | Task / Milestone | Primary Agent | Blocked Agents |
| --- | --- | --- | --- |
| **1: Foundation** | Define `models.py` and `interfaces.py` | 1 (Architect) | 2, 3, 4, 5 |
| **2.a: Environment** | Initialize SQLite schema in `database.py` | 2 (Librarian) | 5 |
| **2.b: Environment** | Implement `gws` wrappers in `loader.py` | 3 (Diplomat) | 5 |
| **2.c: Data Flow** | Build extraction parsers | 4 (Multilingual)| 5 |
| **3: Decision** | Build CLI loop and reconciliation logic | 5 (Judge) | None |

### Overarching Constraints & Instructions
1.  **Strict Isolation:** Do not modify files outside assigned responsibility unless explicitly requested.
2.  **Mocking:** If a dependent component is "PENDING," use a Mock class defined in `interfaces.py` to continue development.
3.  **Error Handling:** All agents must catch `GWSCommandError` (the `gws` wrapper) or `sqlite3.Error` and bubble them up to the CLI for graceful user reporting. If `gws` fails (e.g., no internet), the system must exit without corrupting the SQLite map.
4.  **No PII:** Never hardcode personal contact info in tests or logs. Ensure email addresses and phone numbers are not written to standard log files. Use `test_data/` for sample files.
5.  **Idempotency:** Running the same extraction (e.g., LinkedIn CSV) twice should result in "No changes detected."
