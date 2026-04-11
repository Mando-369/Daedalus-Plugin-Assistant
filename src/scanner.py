"""
Plugin Scanner - Inventories all audio plugins from configured directories.
Deduplicates AU/VST3 pairs and detects own plugins.
"""

import os
import plistlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import PLUGIN_SCAN_DIRS, SCANNER_SKIP_EXTENSIONS, SCANNER_SKIP_PATTERNS, OWN_PLUGIN_BRANDS


def clean_plugin_name(filename: str, extension: str) -> str:
    """Extract clean plugin name from filename."""
    name = filename
    if name.endswith(extension):
        name = name[: -len(extension)]
    # Remove common suffixes
    for suffix in [" x64", "ZL x64", "FLAT x64", "FLATZL x64"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _make_display_name(raw_name: str, plist_display: str = None) -> str:
    """Convert a raw plugin name into a human-readable display name.

    If plist_display is provided (from AudioComponents name, after the ": "),
    use that directly -- it's the developer's own chosen display name.
    Otherwise, clean up the raw filename heuristically.
    """
    # Prefer the plist-provided display name (developer's own naming)
    if plist_display:
        return plist_display.strip()

    # Fallback: clean up raw filename
    name = raw_name

    # Replace underscores with spaces
    name = name.replace("_", " ")

    # Capitalize each word, but preserve acronyms and model numbers
    words = name.split()
    result = []
    for w in words:
        if any(c.isupper() for c in w) and len(w) > 1:
            result.append(w)
        elif w.islower():
            result.append(w.capitalize())
        else:
            result.append(w)
    name = " ".join(result)

    # Fix common audio acronyms
    for acronym in ["LA-2A", "LA-3A", "API", "SSL", "EQ", "VCA", "FET",
                     "ATR", "VT", "HP", "LP", "DSP"]:
        name = re.sub(rf'\b{re.escape(acronym)}\b', acronym, name, flags=re.IGNORECASE)
    name = re.sub(r'\bla2a\b', 'LA-2A', name, flags=re.IGNORECASE)
    name = re.sub(r'\bla3a\b', 'LA-3A', name, flags=re.IGNORECASE)

    return name.strip()


_AU_TYPE_MAP = {
    "aufx": "effect",
    "aumf": "effect",      # music effect (effect with MIDI input)
    "aumi": "effect",      # MIDI processor
    "aumu": "instrument",  # music device / instrument
    "augn": "instrument",  # generator
}


def _extract_metadata_from_plist(bundle_path: str, fmt: str) -> dict:
    """Extract developer + plugin_type from plugin bundle Info.plist.

    Returns dict with 'developer' and 'plugin_type' keys (values may be None).
    """
    result = {"developer": None, "plugin_type": None, "plist_display_name": None}
    try:
        plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
        if not os.path.isfile(plist_path):
            return result

        with open(plist_path, "rb") as f:
            plist = plistlib.load(f)

        # --- Developer extraction ---

        # Priority 1: AudioComponents name (AU only, format "Developer: Plugin Name")
        if fmt == "AU":
            audio_components = plist.get("AudioComponents", [])
            if audio_components and isinstance(audio_components, list):
                ac = audio_components[0]
                ac_name = ac.get("name", "")
                if ": " in ac_name:
                    developer, plugin_display = ac_name.split(": ", 1)
                    developer = developer.strip()
                    if len(developer) >= 2:
                        result["developer"] = developer
                    if plugin_display.strip():
                        result["plist_display_name"] = plugin_display.strip()

                # Extract plugin_type from AU type code
                au_type = ac.get("type", "")
                if au_type in _AU_TYPE_MAP:
                    result["plugin_type"] = _AU_TYPE_MAP[au_type]

        # Priority 2: NSHumanReadableCopyright
        if not result["developer"]:
            copyright_str = plist.get("NSHumanReadableCopyright", "")
            if copyright_str:
                dev = _clean_copyright(copyright_str)
                if dev and len(dev) >= 2:
                    result["developer"] = dev

        # Priority 3: CFBundleIdentifier (com.DeveloperName.PluginName)
        if not result["developer"]:
            bundle_id = plist.get("CFBundleIdentifier", "")
            if bundle_id:
                parts = bundle_id.split(".")
                if len(parts) >= 3:
                    raw = parts[1]
                    if len(raw) >= 2 and raw.lower() not in (
                        "vst3", "au", "plugin", "audio",
                    ):
                        dev = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", raw)
                        dev = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", dev)
                        result["developer"] = dev.strip()

        return result
    except Exception:
        return result


def _clean_copyright(text: str) -> str | None:
    """Clean a copyright string to extract the developer name."""
    s = text.strip()
    # Remove copyright symbols and common prefixes
    s = re.sub(r"^[\s\u00a9\u00ae\u2122(cC)©®™]+", "", s)
    s = re.sub(r"^Copyright\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\(c\)\s*", "", s, flags=re.IGNORECASE)
    # Remove year patterns (2010-2025, 2024, etc.)
    s = re.sub(r"\b\d{4}\s*[-–]\s*\d{4}\b", "", s)
    s = re.sub(r"\b\d{4}\b", "", s)
    # Remove trailing boilerplate
    s = re.sub(r"\.\s*All rights reserved\.?", "", s, flags=re.IGNORECASE)
    s = re.sub(r"All rights reserved\.?", "", s, flags=re.IGNORECASE)
    # Clean up whitespace and punctuation
    s = re.sub(r"\s*[-–—.]+\s*$", "", s)
    s = re.sub(r"^\s*[-–—.]+\s*", "", s)
    s = s.strip(" .,;:-–—")
    return s if s else None


def detect_own_plugin(name: str) -> tuple[bool, str | None]:
    """Check if a plugin is one of the user's own development plugins."""
    for brand, patterns in OWN_PLUGIN_BRANDS.items():
        for pattern in patterns:
            # Match by prefix (handles versioned names like Angelizer_FAUST_10)
            if name.startswith(pattern) or name == pattern:
                return True, brand
    return False, None


def should_skip(filename: str) -> bool:
    """Check if a file should be skipped (non-plugin files in AU dirs)."""
    ext = os.path.splitext(filename)[1].lower()
    if ext in SCANNER_SKIP_EXTENSIONS:
        return True
    for pattern in SCANNER_SKIP_PATTERNS:
        if pattern.lower() in filename.lower():
            return True
    return False


def scan_plugins() -> list[dict]:
    """
    Scan all configured directories and return a list of discovered plugins.
    Each plugin is a dict with: name, display_name, file_name, format, scope,
    file_path, is_own_plugin, own_brand.
    """
    plugins = []
    seen = set()  # for deduplication within same format

    for scan_dir in PLUGIN_SCAN_DIRS:
        dir_path = scan_dir["path"]
        fmt = scan_dir["format"]
        scope = scan_dir["scope"]
        ext = scan_dir["extension"]

        if not os.path.isdir(dir_path):
            print(f"  [SKIP] Directory not found: {dir_path}")
            continue

        print(f"  [SCAN] {dir_path} ({fmt})")

        for entry in sorted(os.listdir(dir_path)):
            if should_skip(entry):
                continue

            full_path = os.path.join(dir_path, entry)

            # Only process actual plugin bundles
            if not entry.endswith(ext):
                # Also check if it's a directory that IS a bundle (macOS bundles are dirs)
                if os.path.isdir(full_path) and not entry.endswith(ext):
                    continue
                if not entry.endswith(ext):
                    continue

            name = clean_plugin_name(entry, ext)
            dedup_key = (name.lower(), fmt, scope)

            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            is_own, own_brand = detect_own_plugin(name)
            meta = _extract_metadata_from_plist(full_path, fmt)

            display_name = _make_display_name(name, meta.get("plist_display_name"))

            plugins.append({
                "name": name,
                "display_name": display_name,
                "file_name": entry,
                "format": fmt,
                "install_scope": scope,
                "file_path": full_path,
                "is_own_plugin": is_own,
                "own_brand": own_brand,
                "developer": meta["developer"],
                "plugin_type": meta["plugin_type"],
            })

    # Cross-format metadata propagation:
    # AU has the richest metadata (developer + plugin_type).
    # Propagate to VST3 versions of the same plugin.
    _cross_reference_metadata(plugins)

    print(f"\n  Total plugins found: {len(plugins)}")
    unique_names = set(p["name"].lower() for p in plugins)
    print(f"  Unique plugin names: {len(unique_names)}")
    print(f"  Own plugins detected: {sum(1 for p in plugins if p['is_own_plugin'])}")
    fmts = {}
    for p in plugins:
        fmts[p["format"]] = fmts.get(p["format"], 0) + 1
    print(f"  Formats: {fmts}")

    return plugins


def _cross_reference_metadata(plugins: list[dict]):
    """Propagate AU metadata (developer, plugin_type, display_name) to VST3."""
    # Build lookup from AU plugins (richest metadata)
    au_metadata = {}
    for p in plugins:
        if p["format"] == "AU":
            key = p["name"].lower()
            au_metadata[key] = {
                "developer": p.get("developer"),
                "plugin_type": p.get("plugin_type"),
                "display_name": p.get("display_name"),
            }

    # Propagate to non-AU plugins missing metadata
    propagated = 0
    for p in plugins:
        if p["format"] == "AU":
            continue
        key = p["name"].lower()
        if key in au_metadata:
            au = au_metadata[key]
            if not p.get("developer") and au.get("developer"):
                p["developer"] = au["developer"]
                propagated += 1
            if not p.get("plugin_type") and au.get("plugin_type"):
                p["plugin_type"] = au["plugin_type"]
            # Always prefer AU display name (from plist)
            if au.get("display_name") and au["display_name"] != p.get("display_name"):
                p["display_name"] = au["display_name"]

    if propagated:
        print(f"  Cross-referenced {propagated} plugins from AU metadata")


if __name__ == "__main__":
    print("Scanning plugin directories...\n")
    results = scan_plugins()
    print(f"\nSample entries:")
    for p in results[:10]:
        own = f" [{p['own_brand']}]" if p["is_own_plugin"] else ""
        print(f"  {p['name']} ({p['format']}, {p['install_scope']}){own}")
