# SETUP.md: User Onboarding & Requirements

This document outlines the non-code steps required to make `reconcile-core` functional on your system.

## 1. Prerequisites (Infrastructure)

Ensure the following tools are installed and available in your `$PATH`:

*   **`uv`**: Fast Python package manager.
    *   *Arch Linux:* install `uv` from the official repositories with your own package manager (e.g. `pacman -S uv`, requires your privileges).
*   **`gws`** (optional): Google Workspace CLI, needed only to sync with Google
    Contacts (ADR-0003).
    *   *Action:* Install via your preferred method and ensure the binary is named `gws`.
*   **Python 3.14+**: The project runtime.
    *   *uv-managed:* `uv python install 3.14` (recommended, works cross-platform)
    *   *Arch Linux:* install Python via your own package manager (e.g. `pacman -S python`, requires your privileges).

## 2. Authentication & Authorization (Google sync only)

You do **not** need a personal API key. `reconcile-core` leverages your existing CLI authentication. Skip this section unless you are syncing to Google.

1.  **Google Login**: Open your terminal and run the authentication command for `gws`:
    ```bash
    gws auth login
    ```
    *(Note: Follow the browser-based OAuth2 flow to authorize access to your Google Contacts.)*
2.  **Verify Access**: Ensure you can list connections manually:
    ```bash
    gws people list-connections --page-size 1
    ```

## 3. Data Preparation (Identity Exports)

The tool processes offline data archives. You must manually request these from your social platforms:

### LinkedIn
1.  Navigate to **Settings & Privacy** > **Data Privacy** > **"Get a copy of your data"**.
2.  Select **"Want something in particular?"** and check **"Connections"**.
3.  Once the archive arrives (usually within 10 minutes), extract `Connections.csv`.

### Discord
1.  Open Discord, go to **Settings** (gear icon) > **Privacy & Safety**.
2.  Scroll to the bottom and click **"Request all of my Data"**.
3.  Wait for the email from Discord (can take up to 30 days, typically arrives in 1-3 days).
4.  Download the data package and extract it. The file you need is `relationships.json`.

### Matrix (Element)
**Option A — Element export (automatic detection):**
1.  Open Element, go to **Settings** > **Help & About**.
2.  Click **"Export Account Data"** to download a JSON file.
3.  The adapter auto-detects the `m.direct` entries from this export.

**Option B — Manual list (fallback):**
Create a JSON file with the following format:
```json
[
  {"mxid": "@alice:matrix.org", "display_name": "Alice"},
  {"mxid": "@bob:matrix.org"}
]
```
If `display_name` is omitted, the adapter derives it from the MXID.

### Generic CSV
For any source not covered above, create a CSV file with these column headers (case-insensitive):
| Column | Maps To | Required |
|--------|---------|----------|
| `Name` / `Display Name` | `display_name` | **Yes** |
| `Email` | `emails` | No |
| `Phone` | `phones` | No |
| `URL` | `urls` | No |
| `IM` | `imClients` | No |
| Any other columns | `raw_metadata` | No |

If no `Name` column is found, the adapter will raise an error listing the available columns. If no `Email` is present, the adapter derives `source_id` from the display name.

## 4. First-Run Guide

1.  **Sync environment**: install dependencies.
    ```bash
    uv sync
    ```
2.  **Create the store** (repo-local `var/contacts.db` by default).
    ```bash
    uv run python -m reconcile_core migrate
    ```
3.  **Ingest and preview**: load an export, then preview the merge (dry run by
    default — nothing is written to the store).
    ```bash
    uv run python -m reconcile_core ingest path/to/Connections.csv -p linkedin
    uv run python -m reconcile_core reconcile path/to/Connections.csv -p linkedin
    ```
4.  **Apply**: union the additions into the store.
    ```bash
    uv run python -m reconcile_core reconcile path/to/Connections.csv -p linkedin --apply
    ```
5.  **Export a projection**:
    ```bash
    uv run python -m reconcile_core export google-contacts --out out/
    ```

The legacy `python -m reconcile_core.main <file> -p <platform>` loop is
deprecated and only relevant for Google-side updates (ADR-0003).

## 5. Persistence

The canonical store is a local SQLite database:

*   **Default path**: repo-local `var/contacts.db` (git-ignored). Override with
    `--db` or `RECONCILE_CORE_DB`. ADR-0002 sets an XDG default
    (`$XDG_DATA_HOME/reconcile-core/contacts.db`) as the target; until that
    lands, the repo-local path is authoritative.
*   It holds entities, `external_refs` (platform identity → entity), contact
    points, segments, and the audit log. Deleting it drops store-side curation;
    Google-side data is unaffected.
