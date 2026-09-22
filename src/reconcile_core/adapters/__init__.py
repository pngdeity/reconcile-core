from .linkedin import LinkedInAdapter
from .discord import DiscordAdapter
from .matrix import MatrixAdapter
from .generic_csv import GenericCSVAdapter

__all__ = ["LinkedInAdapter", "DiscordAdapter", "MatrixAdapter", "GenericCSVAdapter"]

# Platform name -> adapter class. The unified CLI resolves `--platform` here.
ADAPTER_CLASSES = {
    "linkedin": LinkedInAdapter,
    "discord": DiscordAdapter,
    "matrix": MatrixAdapter,
    "generic": GenericCSVAdapter,
}
