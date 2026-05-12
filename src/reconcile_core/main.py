import sys
import argparse
import difflib
from pathlib import Path
from typing import Any, Optional
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm

from .database import SQLitePersistence
from .google_adapter import GoogleAdapter, GWSCommandError
from .loader import ContactLoader
from .reconciler import Reconciler
from .adapters.linkedin import LinkedInAdapter
from .models import StandardContact

try:
    from .adapters.discord import DiscordAdapter
except ImportError:
    DiscordAdapter = None  # type: ignore[assignment,misc]
try:
    from .adapters.matrix import MatrixAdapter
except ImportError:
    MatrixAdapter = None  # type: ignore[assignment,misc]
try:
    from .adapters.generic_csv import GenericCSVAdapter
except ImportError:
    GenericCSVAdapter = None  # type: ignore[assignment,misc]

ADAPTER_CLASSES: dict[str, Any] = {"linkedin": LinkedInAdapter}
if DiscordAdapter is not None:
    ADAPTER_CLASSES["discord"] = DiscordAdapter
if MatrixAdapter is not None:
    ADAPTER_CLASSES["matrix"] = MatrixAdapter
if GenericCSVAdapter is not None:
    ADAPTER_CLASSES["generic"] = GenericCSVAdapter

console = Console()

def fuzzy_match_name(target_name: str, contacts: list[StandardContact], threshold: float = 0.85) -> Optional[StandardContact]:
    """Search cached contacts for a similar display name using difflib."""
    best_match = None
    highest_ratio = 0.0
    
    for contact in contacts:
        ratio = difflib.SequenceMatcher(None, target_name.lower(), contact.display_name.lower()).ratio()
        if ratio > highest_ratio:
            highest_ratio = ratio
            best_match = contact
            
    if highest_ratio >= threshold:
        return best_match
    return None

def run_reconciliation(adapter_path: Path, platform: str = "linkedin", dry_run: bool = False):
    persistence = SQLitePersistence()
    google = GoogleAdapter()
    loader = ContactLoader(google)
    reconciler = Reconciler()

    adapter_class = ADAPTER_CLASSES.get(platform)
    if adapter_class is None:
        console.print(f"[red]Platform '{platform}' adapter not available.[/red]")
        sys.exit(1)
    adapter = adapter_class()

    console.print(f"[bold blue]Starting Reconciliation for: {adapter_path} (platform: {platform})[/bold blue]")
    
    try:
        # 1. Fetch current state from Google (with pagination support)
        console.print("Fetching contacts from Google...")
        google_contacts = google.fetch_all_contacts()
    except GWSCommandError as e:
        console.print(f"[red]Error connecting to Google: {e}[/red]")
        sys.exit(1)

    # 2. Extract proposed contacts from the adapter
    count = 0
    for proposed in adapter.extract(adapter_path):
        count += 1
        console.print(f"\n[bold]({count}) Processing: {proposed.display_name}[/bold]")
        
        # 3. Check for existing mapping in the Identity Map
        resource_name = persistence.get_resource_name(platform, proposed.source_id)
        
        if not resource_name:
            # TRY FUZZY MATCH fallback
            potential_match = fuzzy_match_name(proposed.display_name, google_contacts)
            if potential_match:
                console.print(f"[cyan]No exact mapping, but found potential match: {potential_match.display_name} ({potential_match.source_id})[/cyan]")
                if Confirm.ask(f"Link {proposed.display_name} to this Google contact?"):
                    resource_name = potential_match.source_id
                    persistence.set_mapping(platform, proposed.source_id, resource_name)
                    console.print(f"[green]New mapping created: {proposed.source_id} -> {resource_name}[/green]")
            
            if not resource_name:
                console.print(f"[yellow]No mapping found for {proposed.display_name}. Marked as unresolved.[/yellow]")
                persistence.mark_unresolved(platform, proposed.source_id, proposed.display_name)
                continue
            
        current = google.get_contact(resource_name)
        if not current:
            console.print(f"[red]Linked Google contact {resource_name} not found.[/red]")
            continue

        # 4. Generate Diff (Zero-loss comparison with normalization)
        diff = reconciler.reconcile(proposed, current)
        
        if not diff.additions.emails and not diff.additions.urls and not diff.additions.imClients and not diff.additions.phones and not diff.additions.handles and not diff.collisions:
            console.print("[green]No changes needed.[/green]")
            continue

        # 5. Present Diff to User
        table = Table(title=f"Proposed Changes for {current.display_name}")
        table.add_column("Field", style="cyan")
        table.add_column("Current", style="red")
        table.add_column("Proposed/New", style="green")

        for key, vals in diff.collisions.items():
            table.add_row(key, str(vals[0]), str(vals[1]))
        
        if diff.additions.emails:
            table.add_row("Emails (Add)", "", ", ".join(diff.additions.emails))
        if diff.additions.urls:
            table.add_row("URLs (Add)", "", ", ".join(diff.additions.urls))
        if diff.additions.imClients:
            table.add_row("IM Clients (Add)", "", ", ".join(diff.additions.imClients))
        if diff.additions.phones:
            table.add_row("Phones (Add)", "", ", ".join(diff.additions.phones))
        
        console.print(table)

        if dry_run:
            console.print("[yellow]Dry run: Skipping update.[/yellow]")
            continue

        # 6. User Interaction & Execution
        if diff.collisions:
            console.print("[yellow]Conflicts detected. Automatic update of primary fields disabled.[/yellow]")
            if not Confirm.ask("Skip manual conflict resolution and proceed with safe additions only?"):
                continue

        if Confirm.ask(f"Apply changes to {current.display_name}?"):
            try:
                loader.apply_additions(resource_name, current, diff.additions)
                persistence.log_audit(resource_name, "UPDATE", f"Applied {platform} additions via CLI")
                console.print("[green]Successfully updated![/green]")
            except GWSCommandError as e:
                console.print(f"[red]Failed to update: {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="Reconcile social identities with Google Contacts.")
    parser.add_argument("file", help="Path to the contact export file")
    parser.add_argument(
        "-p", "--platform",
        choices=["linkedin", "discord", "matrix", "generic"],
        default="linkedin",
        help="Platform format of the input file (linkedin, discord, matrix, generic)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without applying them")
    args = parser.parse_args()
    
    run_reconciliation(Path(args.file), platform=args.platform, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
