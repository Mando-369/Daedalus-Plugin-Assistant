"""
Plugin Scanner - Inventories all audio plugins from configured directories.
Deduplicates AU/VST3 pairs and detects own plugins.
"""

import os
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

            plugins.append({
                "name": name,
                "display_name": name,
                "file_name": entry,
                "format": fmt,
                "install_scope": scope,
                "file_path": full_path,
                "is_own_plugin": is_own,
                "own_brand": own_brand,
            })

    # Deduplicate across formats: if same plugin exists as AU + VST3, keep both
    # but link them conceptually (they'll share the same clean name)
    print(f"\n  Total plugins found: {len(plugins)}")

    # Count unique names
    unique_names = set(p["name"].lower() for p in plugins)
    print(f"  Unique plugin names: {len(unique_names)}")
    print(f"  Own plugins detected: {sum(1 for p in plugins if p['is_own_plugin'])}")

    return plugins


if __name__ == "__main__":
    print("Scanning plugin directories...\n")
    results = scan_plugins()
    print(f"\nSample entries:")
    for p in results[:10]:
        own = f" [{p['own_brand']}]" if p["is_own_plugin"] else ""
        print(f"  {p['name']} ({p['format']}, {p['install_scope']}){own}")
