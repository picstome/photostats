"""Photo Stats — photo metadata analyzer."""

__version__ = "1.0.0"

#: What people call it in the settings file and on the command line. Kept
#: short and stable: this string is a key, and changing it resets everyone's
#: saved preferences rather than migrating them.
APP_NAME = "Photo Stats"
APP_SLUG = "photostats"
ORG_NAME = "picstome"
ORG_DOMAIN = "picstome.com"

#: Who makes it, shown in the window title and the about box.
AUTHOR = "Picstome.com"
AUTHOR_URL = "https://picstome.com"

#: Where the source lives and the builds are published. The monthly update
#: check asks this repository's Releases API for the latest tag, so moving the
#: project means changing one string.
REPO_SLUG = "picstome/photostats"


def display_name() -> str:
    """The full product name: 'Photo Stats by Picstome.com'."""
    return f"{APP_NAME} by {AUTHOR}"


__all__ = ["__version__", "APP_NAME", "APP_SLUG", "ORG_NAME", "ORG_DOMAIN",
           "AUTHOR", "AUTHOR_URL", "REPO_SLUG", "display_name"]
