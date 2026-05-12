# SETUP.md: User Onboarding & Requirements

This document outlines the non-code steps required to make `reconcile-core` functional on your system.

## 1. Prerequisites (Infrastructure)

Ensure the following tools are installed and available in your `$PATH`:

*   **`uv`**: Fast Python package manager.
    *   *Arch Linux:* `sudo pacman -S uv`
*   **`gws`**: Google Workspace CLI.
    *   *Action:* Install via your preferred method and ensure the binary is named `gws`.
*   **Python 3.14+**: The project runtime.

## 2. Authentication & Authorization

You do **not** need a personal API key. `reconcile-core` leverages your existing CLI authentication.

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

## 4. First-Run Guide

1.  **Sync Environment**: Ensure dependencies are locked and the project is installed in editable mode.
    ```bash
    uv sync
    ```
2.  **Test Run (Dry Run)**: Preview changes without writing to Google Contacts or your local map.
    ```bash
    uv run python -m reconcile_core.main path/to/your/Connections.csv --dry-run
    ```
3.  **Active Reconciliation**: Apply changes and map identities.
    ```bash
    uv run python -m reconcile_core.main path/to/your/Connections.csv
    ```

## 5. Persistence Note
Your identity mappings and audit logs are stored locally in SQLite:
*   **Default Path**: `$XDG_DATA_HOME/reconcile-core/identities.db` (usually `~/.local/share/reconcile-core/identities.db`).
*   Deleting this file will force the tool to re-identify all contacts (though `gws` data on Google's side will remain).
