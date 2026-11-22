"""AT-07: State Persistence & Fault Tolerance Acceptance Tests."""

import pytest
from src.config import ConfigStore, AppSettings
from src.models import AnchorRecord


def test_at07_1_settings_and_anchor_persistence(tmp_path):
    """AT-07.1: Verify atomic persistence and recovery of all settings and anchor bookmark."""
    state_file = tmp_path / "state.json"
    store = ConfigStore(state_path=state_file)
    
    settings = AppSettings(
        last_profile_path="test-release",
        output_dir=str(tmp_path / "Downloads"),
        concurrency=3,
        filename_template="%(id)s.%(ext)s",
        hide_skipped=True,
        last_anchor=AnchorRecord(
            tweet_id="189234109",
            author_handle="testcreator"
        )
    )
    store.save(settings)
    
    # Reload in a new store instance
    store2 = ConfigStore(state_path=state_file)
    loaded = store2.load()
    
    assert loaded.last_profile_path == "test-release"
    assert loaded.output_dir == str(tmp_path / "Downloads")
    assert loaded.concurrency == 3
    assert loaded.filename_template == "%(id)s.%(ext)s"
    assert loaded.hide_skipped is True
    assert loaded.last_anchor is not None
    assert loaded.last_anchor.tweet_id == "189234109"
    assert loaded.last_anchor.author_handle == "testcreator"


def test_at07_2_corrupted_state_recovery(tmp_path):
    """AT-07.2: Recovers safely from malformed state.json by returning default AppSettings without crashing."""
    state_file = tmp_path / "state.json"
    state_file.write_text("{ broken json: [unclosed", encoding="utf-8")
    
    store = ConfigStore(state_path=state_file)
    loaded = store.load()
    
    assert loaded.last_anchor is None
    assert loaded.concurrency == 2
