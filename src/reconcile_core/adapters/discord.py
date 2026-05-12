import json
from pathlib import Path
from collections.abc import Generator
from ..models import StandardContact, SocialHandle
from ..interfaces import BaseAdapter

class DiscordAdapter(BaseAdapter):
    def extract(self, file_path: Path) -> Generator[StandardContact, None, None]:
        """
        Extract contacts from Discord Data Package (relationships.json).
        Relationships type mapping:
        1: Friend
        2: Blocked
        3: Incoming Friend Request
        4: Outgoing Friend Request
        """
        if not file_path.exists():
            return

        try:
            with open(file_path, mode='r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return

        if not isinstance(data, list):
            return

        for entry in data:
            # We only reconcile active friends (type 1)
            if entry.get("type") != 1:
                continue
            
            user_data = entry.get("user", {})
            source_id = user_data.get("id") # Discord Snowflake ID
            username = user_data.get("username")
            discriminator = user_data.get("discriminator")
            
            if not source_id or not username:
                continue

            # Handle Discord's transition to unique usernames (discriminator '0' or missing)
            if discriminator and discriminator != "0":
                handle_str = f"{username}#{discriminator}"
            else:
                handle_str = username
            
            yield StandardContact(
                source_id=source_id,
                display_name=handle_str,
                handles=[SocialHandle(platform="discord", username=handle_str, is_im=True)]
            )
