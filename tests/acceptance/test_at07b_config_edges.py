"""Tests for ConfigStore default paths, recent directory deduplication, and legacy ConfigManager properties."""

import pytest
from pathlib import Path
from src.config import ConfigStore, ConfigManager, AppSettings
from src.models import AnchorRecord


def test_at07_3_recent_output_dir_deduplication():
    """Verify add_recent_output_dir normalizes, prepends, and caps recent directories."""
    store = ConfigStore(state_path=Path("dummy_state.json"))
    settings = AppSettings()
    
    # Add multiple folders
    store.add_recent_output_dir(settings, "C:/Downloads/Videos")
    store.add_recent_output_dir(settings, "C:/Downloads/Other")
    store.add_recent_output_dir(settings, "C:/downloads/videos")  # Case-insensitive duplicate
    
    assert len(settings.recent_output_dirs) == 2
    assert "videos" in settings.recent_output_dirs[0].lower()


def test_at07_4_config_manager_adapter_properties(tmp_path):
    """Verify ConfigManager compatibility adapter accessors and mutators."""
    manager = ConfigManager(storage_dir=str(tmp_path))
    
    manager.selected_profile_name = "test-prof"
    manager.save_directory = str(tmp_path / "SaveDir")
    manager.last_anchor_tweet_id = "555123"
    manager.last_anchor_author = "author_x"
    
    assert manager.selected_profile_name == "test-prof"
    assert manager.save_directory == str(tmp_path / "SaveDir")
    assert manager.last_anchor_tweet_id == "555123"
    assert manager.last_anchor_author == "author_x"

    manager.save_config()
    manager.save_state()

    # Clear anchor via manager
    manager.update_anchor(None)
    assert manager.last_anchor_tweet_id is None
