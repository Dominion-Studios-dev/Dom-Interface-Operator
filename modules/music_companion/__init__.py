"""Music Companion — guitar chord sheets, tabs search, and media transport.

Offline-first chord library for practicing, lightweight DuckDuckGo search for
song tabs, and local media transport control (playerctl / mpd / spotify).

Commands:
    chord <name>            Show a chord diagram (e.g. "chord am7", "chord G")
    chord sheet             List every chord in the local library
    guitar tabs <song>      Search the web for tabs of a song
    play music              Resume/launch local media playback
    pause music             Pause local media playback
    music status            Report current player state

Everything is stdlib-only; HTTP goes through urllib. Media control degrades
gracefully when playerctl/mpd are not installed.
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

from modules.base import BasePlugin

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ── Chord Library ────────────────────────────────────────────────────────────
# frets are ordered low E -> A -> D -> G -> B -> high e.
#   'x' = muted string, '0' = open, digits = fret number.
CHORD_LIBRARY = {
    "g":        {"name": "G major",     "frets": "320003", "notes": "Classic open G."},
    "gm":       {"name": "G minor",     "frets": "355333", "notes": "Barre at 3rd fret."},
    "g7":       {"name": "G7",          "frets": "320001"},
    "gmaj7":    {"name": "Gmaj7",       "frets": "320002", "notes": "Jazzy open G."},
    "gsus4":    {"name": "Gsus4",       "frets": "330013"},
    "a":        {"name": "A major",     "frets": "x02220"},
    "am":       {"name": "A minor",     "frets": "x02210"},
    "a7":       {"name": "A7",          "frets": "x02020"},
    "am7":      {"name": "Am7",         "frets": "x02010"},
    "amaj7":    {"name": "Amaj7",       "frets": "x02120"},
    "asus2":    {"name": "Asus2",       "frets": "x02200"},
    "asus4":    {"name": "Asus4",       "frets": "x02230"},
    "c":        {"name": "C major",     "frets": "x32010"},
    "cm":       {"name": "C minor",     "frets": "x35543", "notes": "Barre at 3rd fret."},
    "c7":       {"name": "C7",          "frets": "x32310"},
    "cmaj7":    {"name": "Cmaj7",       "frets": "x32000"},
    "cadd9":    {"name": "Cadd9",       "frets": "x32033", "notes": "Great practice chord."},
    "d":        {"name": "D major",     "frets": "xx0232"},
    "dm":       {"name": "D minor",     "frets": "xx0231"},
    "d7":       {"name": "D7",          "frets": "xx0212"},
    "dmaj7":    {"name": "Dmaj7",       "frets": "xx0222"},
    "dsus2":    {"name": "Dsus2",       "frets": "xx0230"},
    "dsus4":    {"name": "Dsus4",       "frets": "xx0233"},
    "e":        {"name": "E major",     "frets": "022100"},
    "em":       {"name": "E minor",     "frets": "022000"},
    "e7":       {"name": "E7",          "frets": "020100"},
    "em7":      {"name": "Em7",         "frets": "022030"},
    "emaj7":    {"name": "Emaj7",       "frets": "021100"},
    "esus4":    {"name": "Esus4",       "frets": "022200"},
    "f":        {"name": "F major",     "frets": "133211", "notes": "Barre at 1st fret."},
    "fm":       {"name": "F minor",     "frets": "133111", "notes": "Barre at 1st fret."},
    "f7":       {"name": "F7",          "frets": "131211"},
    "fmaj7":    {"name": "Fmaj7",       "frets": "xx3210"},
    "b":        {"name": "B major",     "frets": "x24442", "notes": "Barre at 2nd fret."},
    "bm":       {"name": "B minor",     "frets": "x24432", "notes": "Barre at 2nd fret."},
    "b7":       {"name": "B7",          "frets": "x21202"},
    "bb":       {"name": "Bb major",    "frets": "x13331", "notes": "Barre at 1st fret."},
    "f#m":      {"name": "F# minor",    "frets": "244222", "notes": "Barre at 2nd fret."},
    "f#":       {"name": "F# major",    "frets": "244322", "notes": "Barre at 2nd fret."},
    "c#m":      {"name": "C# minor",    "frets": "x46654", "notes": "Barre at 4th fret."},
    "eb":       {"name": "Eb major",    "frets": "x68886", "notes": "Barre at 6th fret."},
    "ab":       {"name": "Ab major",    "frets": "466544", "notes": "Barre at 4th fret."},
}

_STRING_LOW_TO_HIGH = "EADGBe"


def render_chord(key: str) -> str:
    """Render a full ASCII fretboard diagram for a chord key."""
    chord = CHORD_LIBRARY[key]
    frets = chord["frets"]
    lines = [f"{chord['name']}   frets (E A D G B e): {frets}"]

    max_fret = 0
    for c in frets:
        if c.isdigit():
            max_fret = max(max_fret, int(c))

    for s in reversed(_STRING_LOW_TO_HIGH):
        idx = _STRING_LOW_TO_HIGH.index(s)
        ch = frets[idx]
        row = f"{s} "
        if ch == "x":
            row += "✗ "
        elif ch == "0":
            row += "○ "
        else:
            row += f"{ch} "
        for f in range(1, max(max_fret, 1) + 1):
            row += "|" + ("─" * 3)
        row += "|"
        lines.append(row)

    if max_fret > 0:
        nut = "   "
        for f in range(1, max_fret + 1):
            nut += f"  {f} "
        lines.insert(1, nut)

    if chord.get("notes"):
        lines.append("")
        lines.append(f"Tip: {chord['notes']}")
    return "\n".join(lines)


def _chord_index() -> str:
    """Plain list of all chords in the library."""
    rows = []
    for key in sorted(CHORD_LIBRARY):
        c = CHORD_LIBRARY[key]
        rows.append(f"{c['name']:<14} {c['frets']}")
    return "Local chord library (" + str(len(CHORD_LIBRARY)) + " chords):\n" + "\n".join(rows)


def _normalize_chord_query(q: str) -> str:
    q = q.strip().lower().replace("major", "").replace("minor", "m").strip()
    if q.endswith("maj"):
        q = q[:-3].strip()
    return q


# ── Media Transport (safe subprocess, no shell) ──────────────────────────────

def _which(*names):
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _run(argv, timeout=5):
    try:
        r = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def _media_state():
    playerctl = _which("playerctl")
    mpc = _which("mpc")
    spotify = shutil.which("flatpak")
    state = {"playerctl": bool(playerctl), "mpc": bool(mpc), "spotify": bool(spotify)}
    status = "no player detected"
    if playerctl:
        code, out = _run([playerctl, "status"])
        if code == 0:
            status = out
    elif mpc:
        code, out = _run([mpc, "status"])
        if code == 0:
            status = out.splitlines()[0] if out else "idle"
    return state, status


def media_play() -> dict:
    playerctl = _which("playerctl")
    mpc = _which("mpc")

    if playerctl:
        code, out = _run([playerctl, "play"])
        if code == 0:
            return {"status": "success", "output": "Playback resumed, Master."}
        code, out = _run([playerctl, "play-pause"])
        if code == 0:
            return {"status": "success", "output": "Playback toggled, Master."}
        return {"status": "error", "output": "playerctl found but no media player is active."}

    if mpc:
        code, out = _run([mpc, "play"])
        if code == 0:
            return {"status": "success", "output": "MPD playback started."}
        return {"status": "error", "output": "MPD is not responding."}

    # No transport control available — offer to launch Spotify.
    if shutil.which("flatpak"):
        subprocess.Popen(
            ["flatpak", "run", "com.spotify.Client"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {
            "status": "success",
            "output": "Launching Spotify, Master. Install 'playerctl' (sudo pacman -S playerctl) for full play/pause transport control.",
        }

    return {"status": "error", "output": "No media player found. Install playerctl (pacman -S playerctl) or mpd."}


def media_pause() -> dict:
    playerctl = _which("playerctl")
    mpc = _which("mpc")

    if playerctl:
        code, out = _run([playerctl, "pause"])
        if code == 0:
            return {"status": "success", "output": "Paused, Master."}
        return {"status": "error", "output": "playerctl found but nothing is playing to pause."}

    if mpc:
        code, out = _run([mpc, "pause"])
        if code == 0:
            return {"status": "success", "output": "MPD paused."}
        return {"status": "error", "output": "MPD is not responding."}

    return {"status": "error", "output": "No media transport tool found. Install playerctl (pacman -S playerctl)."}


def media_status() -> dict:
    state, status = _media_state()
    tools = []
    if state["playerctl"]:
        tools.append("playerctl")
    if state["mpc"]:
        tools.append("mpd/mpc")
    if state["spotify"]:
        tools.append("spotify (flatpak)")
    header = "Detected tools: " + (", ".join(tools) if tools else "none")
    return {"status": "success", "output": f"{header}\nPlayer state: {status}"}


# ── Tab Search (lightweight, no auth) ────────────────────────────────────────

def _ddg_instant(query: str) -> list:
    """DuckDuckGo HTML search (no JS needed). Returns [{title,url,snippet}].

    The instant-answer API rarely has tab data, so this scrapes the
    html.duckduckgo.com results page with a browser UA and decodes the
    /l/?uddg= redirect links back to the real URLs.
    """
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    req = urllib.request.Request(url, headers={
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        page = resp.read().decode("utf-8", "ignore")

    titles = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    snips = re.findall(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', page, re.S)

    import html as _html

    results = []
    for i, (href, title_html) in enumerate(titles):
        title = _html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        if not title:
            continue
        real_url = _decode_uddg(href)
        snippet = ""
        if i < len(snips):
            snippet = _html.unescape(re.sub(r"<[^>]+>", "", snips[i])).strip()
        results.append({"title": title, "url": real_url, "snippet": snippet})
    return results


def _decode_uddg(href: str) -> str:
    """Decode a DuckDuckGo redirect link like //duckduckgo.com/l/?uddg=<url>."""
    m = re.search(r"uddg=([^&]+)", href)
    if m:
        return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def search_tabs(song: str) -> dict:
    results = []
    try:
        from ddgs import DDGS
        raw = DDGS().text(song + " guitar tabs", max_results=5)
        results = [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in raw]
    except Exception:
        pass

    if not results:
        try:
            results = _ddg_instant(song + " guitar tabs")
        except Exception:
            results = []

    if not results:
        return {
            "status": "success",
            "output": (
                "No tab results found for that song (offline or no match), Master.\n\n"
                + _chord_index()
            ),
        }

    out = [f"Tabs for '{song}':"]
    for i, r in enumerate(results[:5], 1):
        out.append(f"{i}. {r['title']}")
        if r.get("url"):
            out.append(f"   {r['url']}")
        if r.get("snippet"):
            out.append(f"   {r['snippet'][:160]}")
    return {"status": "success", "output": "\n".join(out)}


# ── Plugin Entry ─────────────────────────────────────────────────────────────

class Plugin(BasePlugin):
    name = "music_companion"
    triggers = ["guitar tabs", "play music", "pause music", "chord sheet", "music status", "chord"]

    def execute(self, user_input: str) -> dict:
        lower = user_input.lower().strip()

        if lower == "chord sheet" or lower == "chords":
            return {"status": "success", "output": _chord_index()}

        if lower == "music status":
            return media_status()

        if lower == "play music":
            return media_play()

        if lower == "pause music":
            return media_pause()

        chord_m = re.search(r"(?:chord sheet|chord)\s+(.+)", lower)
        if chord_m:
            key = _normalize_chord_query(chord_m.group(1))
            if key in CHORD_LIBRARY:
                return {"status": "success", "output": render_chord(key)}
            return {
                "status": "error",
                "output": f"Chord '{key}' not in the library. Try: chord sheet",
            }

        tabs_m = re.search(r"guitar tabs\s+(.+)", lower)
        if tabs_m:
            return search_tabs(tabs_m.group(1).strip())

        if "tabs" in lower:
            song = lower.replace("tabs", "").strip()
            if song:
                return search_tabs(song)

        return {"status": "error", "output": "Unknown music command. Try: chord G, chord sheet, guitar tabs <song>, play music, pause music, music status"}
