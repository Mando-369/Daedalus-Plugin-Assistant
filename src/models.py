"""
Daedalus Plugin Assistant - Database Models
SQLite schema for structured plugin metadata.
"""

import sqlite3
import os
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import SQLITE_DB_PATH, DATA_DIR


def get_db():
    """Get a database connection with WAL mode for concurrent reads."""
    conn = sqlite3.connect(str(SQLITE_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables and indexes."""
    os.makedirs(str(DATA_DIR), exist_ok=True)
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
    -- Main plugin table
    CREATE TABLE IF NOT EXISTS plugins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        display_name TEXT,              -- cleaned/friendly name
        developer TEXT,                 -- e.g. 'FabFilter', 'Universal Audio'
        is_own_plugin INTEGER DEFAULT 0, -- 1 if user's own development plugin
        own_brand TEXT,                 -- e.g. 'MyDSP', 'My Brand'

        -- Format & location
        format TEXT,                    -- 'AU' or 'VST3'
        file_name TEXT,                 -- original filename
        install_scope TEXT,             -- 'system' or 'user'
        file_path TEXT,                 -- full path to plugin

        -- Classification
        plugin_type TEXT,               -- 'instrument' or 'effect'
        category TEXT,                  -- primary: EQ, Compressor, Reverb, Synth, etc.
        subcategory TEXT,               -- secondary: Parametric EQ, Graphic EQ, etc.
        subtype TEXT,                   -- clone, emulation, original, utility
        emulation_of TEXT,              -- what hardware it emulates (if applicable)

        -- Detailed info
        description TEXT,               -- what the plugin does
        specialty TEXT,                 -- special/hidden strengths
        best_used_for TEXT,             -- ideal use cases
        character TEXT,                 -- sonic character: warm, clean, aggressive, transparent, etc.
        signal_chain_position TEXT,     -- where in the chain: first, last, insert, bus, master

        -- Tags for flexible searching
        tags TEXT,                      -- comma-separated tags
        notes TEXT,                     -- personal notes

        -- Metadata
        classification_confidence TEXT, -- 'high', 'medium', 'low', 'unclassified'
        needs_review INTEGER DEFAULT 0, -- 1 if auto-classified and needs human review
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),

        UNIQUE(file_name, format, install_scope)
    );

    -- Categories reference table
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,      -- e.g. 'EQ', 'Compressor'
        parent_category TEXT,           -- for hierarchy: 'Dynamics' -> 'Compressor'
        description TEXT
    );

    -- Preset categories
    INSERT OR IGNORE INTO categories (name, parent_category, description) VALUES
        -- Dynamics
        ('Compressor', 'Dynamics', 'Dynamic range compression'),
        ('Limiter', 'Dynamics', 'Peak limiting and loudness maximizing'),
        ('Gate', 'Dynamics', 'Noise gate / expander'),
        ('De-esser', 'Dynamics', 'Sibilance reduction'),
        ('Transient Shaper', 'Dynamics', 'Attack/sustain manipulation'),
        ('Expander', 'Dynamics', 'Dynamic range expansion'),
        ('Multiband Dynamics', 'Dynamics', 'Frequency-dependent dynamics processing'),

        -- EQ & Filtering
        ('EQ', 'EQ & Filtering', 'Equalization'),
        ('Dynamic EQ', 'EQ & Filtering', 'Frequency-dependent dynamic EQ'),
        ('Filter', 'EQ & Filtering', 'Resonant/static filters'),
        ('Tilt EQ', 'EQ & Filtering', 'Tilt/balance EQ'),

        -- Time-based
        ('Reverb', 'Time-based', 'Reverberation'),
        ('Delay', 'Time-based', 'Echo and delay effects'),
        ('Chorus', 'Time-based', 'Chorus modulation'),
        ('Flanger', 'Time-based', 'Flanging effect'),
        ('Phaser', 'Time-based', 'Phase shifting effect'),

        -- Distortion & Saturation
        ('Saturation', 'Distortion & Saturation', 'Harmonic saturation / warmth'),
        ('Distortion', 'Distortion & Saturation', 'Hard clipping / distortion'),
        ('Clipper', 'Distortion & Saturation', 'Waveform clipping'),
        ('Tape Emulation', 'Distortion & Saturation', 'Tape machine emulation'),
        ('Tube Emulation', 'Distortion & Saturation', 'Vacuum tube emulation'),
        ('Amp Sim', 'Distortion & Saturation', 'Guitar/bass amplifier simulation'),

        -- Spatial
        ('Stereo', 'Spatial', 'Stereo width/imaging'),
        ('Panner', 'Spatial', 'Panning and spatial positioning'),
        ('Mid-Side', 'Spatial', 'Mid/side processing'),
        ('Immersive', 'Spatial', 'Surround/3D audio'),

        -- Modulation
        ('Modulation', 'Modulation', 'General modulation effects'),
        ('Tremolo', 'Modulation', 'Amplitude modulation'),
        ('Vibrato', 'Modulation', 'Pitch modulation'),
        ('Ring Mod', 'Modulation', 'Ring modulation'),
        ('Rotary', 'Modulation', 'Leslie/rotary speaker emulation'),

        -- Pitch & Time
        ('Pitch Correction', 'Pitch & Time', 'Auto-tune style pitch correction'),
        ('Pitch Shifter', 'Pitch & Time', 'Pitch shifting / harmonizing'),
        ('Time Stretch', 'Pitch & Time', 'Time stretching'),
        ('Vocoder', 'Pitch & Time', 'Vocoding'),

        -- Instruments
        ('Synthesizer', 'Instruments', 'Virtual synthesizer'),
        ('Sampler', 'Instruments', 'Sample playback instrument'),
        ('Drum Machine', 'Instruments', 'Drum/percussion synthesis or sampling'),
        ('Electric Piano', 'Instruments', 'Electric piano emulation'),
        ('Organ', 'Instruments', 'Organ emulation'),
        ('Acoustic Piano', 'Instruments', 'Acoustic piano'),
        ('String Machine', 'Instruments', 'String ensemble emulation'),

        -- Mastering
        ('Mastering Suite', 'Mastering', 'All-in-one mastering chain'),
        ('Loudness Meter', 'Mastering', 'LUFS/loudness measurement'),
        ('Maximizer', 'Mastering', 'Loudness maximizing'),

        -- Utility & Analysis
        ('Analyzer', 'Utility & Analysis', 'Spectrum/metering/analysis'),
        ('Channel Strip', 'Utility & Analysis', 'Combined EQ + dynamics strip'),
        ('Utility', 'Utility & Analysis', 'Gain, phase, routing, etc.'),
        ('Console Emulation', 'Utility & Analysis', 'Mixing console emulation'),
        ('Monitor', 'Utility & Analysis', 'Monitoring/reference tools'),

        -- Restoration
        ('De-noise', 'Restoration', 'Noise reduction'),
        ('De-reverb', 'Restoration', 'Reverb removal'),
        ('De-click', 'Restoration', 'Click/pop removal'),
        ('Restoration Suite', 'Restoration', 'Multi-purpose audio restoration'),

        -- Creative
        ('Creative FX', 'Creative', 'Experimental/creative effects'),
        ('Lofi', 'Creative', 'Lo-fi / degradation effects'),
        ('Granular', 'Creative', 'Granular processing'),
        ('Glitch', 'Creative', 'Glitch / stutter effects'),
        ('Multi-FX', 'Creative', 'Multi-effect processor');

    -- Full-text search index
    CREATE VIRTUAL TABLE IF NOT EXISTS plugins_fts USING fts5(
        name, display_name, developer, category, subcategory,
        description, specialty, best_used_for, character, tags, notes,
        content='plugins',
        content_rowid='id'
    );

    -- Triggers to keep FTS in sync
    CREATE TRIGGER IF NOT EXISTS plugins_ai AFTER INSERT ON plugins BEGIN
        INSERT INTO plugins_fts(rowid, name, display_name, developer, category, subcategory,
            description, specialty, best_used_for, character, tags, notes)
        VALUES (new.id, new.name, new.display_name, new.developer, new.category, new.subcategory,
            new.description, new.specialty, new.best_used_for, new.character, new.tags, new.notes);
    END;

    CREATE TRIGGER IF NOT EXISTS plugins_ad AFTER DELETE ON plugins BEGIN
        INSERT INTO plugins_fts(plugins_fts, rowid, name, display_name, developer, category, subcategory,
            description, specialty, best_used_for, character, tags, notes)
        VALUES ('delete', old.id, old.name, old.display_name, old.developer, old.category, old.subcategory,
            old.description, old.specialty, old.best_used_for, old.character, old.tags, old.notes);
    END;

    CREATE TRIGGER IF NOT EXISTS plugins_au AFTER UPDATE ON plugins BEGIN
        INSERT INTO plugins_fts(plugins_fts, rowid, name, display_name, developer, category, subcategory,
            description, specialty, best_used_for, character, tags, notes)
        VALUES ('delete', old.id, old.name, old.display_name, old.developer, old.category, old.subcategory,
            old.description, old.specialty, old.best_used_for, old.character, old.tags, old.notes);
        INSERT INTO plugins_fts(rowid, name, display_name, developer, category, subcategory,
            description, specialty, best_used_for, character, tags, notes)
        VALUES (new.id, new.name, new.display_name, new.developer, new.category, new.subcategory,
            new.description, new.specialty, new.best_used_for, new.character, new.tags, new.notes);
    END;

    -- Indexes
    CREATE INDEX IF NOT EXISTS idx_plugins_category ON plugins(category);
    CREATE INDEX IF NOT EXISTS idx_plugins_developer ON plugins(developer);
    CREATE INDEX IF NOT EXISTS idx_plugins_type ON plugins(plugin_type);
    CREATE INDEX IF NOT EXISTS idx_plugins_is_own ON plugins(is_own_plugin);
    CREATE INDEX IF NOT EXISTS idx_plugins_needs_review ON plugins(needs_review);
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at {SQLITE_DB_PATH}")


if __name__ == "__main__":
    init_db()
