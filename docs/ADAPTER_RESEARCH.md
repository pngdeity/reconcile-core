# ADAPTER_RESEARCH.md: Identity Provider Integration (May 2026)

This document provides technical specifications and research findings for implementing new data adapters in `reconcile-core`.

> **Status (2026-09-21): research only.** None of these adapters are implemented
> yet. Scheduling is tracked by `docs/adr/0004-p1-delivery-roadmap.md` (C6).

---

## 1. Facebook (Meta Graph API v25.0)

### Retrieval Method: API
*   **Endpoint:** `GET /v25.0/me/friends`
*   **Authentication:** OAuth 2.0 (User Access Token)
*   **Required Scopes:** `user_friends`, `public_profile`
*   **2026 Constraints:**
    *   **Mutual Use Policy:** Only returns friends who have *also* authorized the same application.
    *   **App Review:** Requires Meta App Review for live production access.
*   **Developer Tip:** For MVP-level reconciliation, a manual export of "Information About You" -> "Friends and Followers" (JSON/HTML) from Facebook Settings is more effective for comprehensive lists.

---

## 2. GitHub (REST API v3)

### Retrieval Method: API
*   **Endpoint:** `GET /user/following`
*   **Authentication:** Personal Access Token (PAT) or OAuth 2.0
*   **Required Scopes:** `user:follow` (read-only)
*   **2026 Constraints:**
    *   **Rate Limits:** 5,000 requests per hour for authenticated users.
    *   **Pagination:** Uses Link headers for navigation; default is 30 users per page.
*   **Developer Tip:** Use the `X-GitHub-Api-Version: 2022-11-28` header for stability.

---

## 3. X.com (formerly Twitter - v2 API)

### Retrieval Method: API
*   **Endpoint:** `GET /2/users/me/following`
*   **Authentication:** OAuth 2.0 with PKCE (User Context)
*   **Required Scopes:** `follows.read`, `users.read`
*   **2026 Pricing:**
    *   **Pay-Per-Use:** ~$0.005 - $0.010 per request.
    *   **Rate Limit:** 15 requests per 15-minute window (User level).
*   **Developer Tip:** Ensure you capture the `pagination_token` from the `meta` object to handle lists larger than 100 users.

---

## 4. Telegram (MTProto / User API)

### Retrieval Method: MTProto (User Session)
*   **Method:** `contacts.getContacts`
*   **Authentication:** `api_id`, `api_hash`, and a valid User Session (phone number + SMS code).
*   **Library Recommendation:** `Telethon` (Python)
*   **2026 Constraints:**
    *   **Privacy:** Usernames are only returned if the contact has set one and their privacy settings allow discovery.
    *   **Flood Waits:** Tightened in 2026; importing or fetching 5,000+ contacts rapidly will trigger a multi-hour backoff.
*   **Developer Tip:** The Bot API *cannot* see a user's contact list; you must implement an MTProto client.

---

## 5. Summary Recommendation for Adapters

| Provider | Best Source | Complexity | Reliability |
| :--- | :--- | :--- | :--- |
| **Facebook** | Manual JSON Export | High (Manual) | High |
| **GitHub** | API (`/following`) | Low | High |
| **X.com** | API (`/following`) | Medium | High (Paid) |
| **Telegram** | MTProto API | High | Medium |
