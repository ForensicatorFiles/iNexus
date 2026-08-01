"""
Plain-ASCII banner shown on `-h` and `-version`. Deliberately built from
nothing but the Python standard library (raw triple-quoted string +
str.center()) — no figlet/pyfiglet/rich/colorama or any other dependency,
and no ANSI color codes, so it renders identically and safely on every
terminal this tool might run in, including older/restricted ones (a real
possibility in forensic lab environments), when piped/redirected to a
file, and on Windows' default console codepage.
"""
from .constants import TOOL_VERSION

BANNER = r"""
 _  _   _
(_)| \ | |  ___  __  __ _  _  ___
| ||  \| | / _ \ \ \/ /| || |/ __|
| || |\  ||  __/  >  < | |_| |\__ \
|_||_| \_| \___| /_/\_\ \__,_||___/"""

TAGLINE = "iOS Forensic Artifact & Location Correlator"


def banner_text():
    """
    Returns the full banner block (art + tagline + version line) as one
    string, each line centered to the art's own width. No terminal-width
    detection — this deliberately doesn't call shutil.get_terminal_size()
    (which can raise or return a bogus value on some CI/redirected-output
    environments); a fixed width keyed off the art itself is simpler and
    always correct.
    """
    width = max(len(line) for line in BANNER.splitlines())
    lines = [BANNER]
    lines.append(TAGLINE.center(width))
    lines.append(f"v{TOOL_VERSION}".center(width))
    return "\n".join(lines)
