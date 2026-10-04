import json
from pathlib import Path

import pytest

from iverilog_ai.ai.local_api_profile import LocalApiProfile, load_local_api_profile, read_key_file


def test_profile_loads_metadata_and_reads_current_key_only_when_requested(tmp_path):
    key_file = tmp_path / "key.txt"
    profile_file = tmp_path / "profile.json"
    profile_file.write_text(json.dumps({"endpoint": "https://api.example", "model": "test",
                                        "api_key_file": str(key_file), "max_output_tokens": 8192}))
    profile = load_local_api_profile(profile_file)
    assert profile is not None
    assert not key_file.exists()
    key_file.write_text("\ufefffirst-secret\n", encoding="utf-8")
    assert profile.key_for("https://api.example/") == "first-secret"
    key_file.write_text("rotated-secret", encoding="utf-8")
    assert profile.key_for("https://api.example") == "rotated-secret"
    assert "secret" not in profile.model_dump_json()


def test_profile_never_reads_key_for_another_destination(tmp_path):
    profile = LocalApiProfile(endpoint="https://api.example", model="test", api_key_file=str(tmp_path / "absent.txt"))
    for destination in ["https://other.example", "https://api.example.evil.invalid", "http://api.example", "https://api.example/other"]:
        assert profile.key_for(destination) == ""
    with pytest.raises(FileNotFoundError):
        profile.key_for("https://api.example")


@pytest.mark.parametrize("endpoint", ["http://api.example", "https://user:secret@api.example", "https://api.example?key=secret"])
def test_unsafe_profile_endpoint_is_refused(tmp_path, endpoint):
    with pytest.raises(ValueError):
        LocalApiProfile(endpoint=endpoint, model="test", api_key_file=str(tmp_path / "key.txt"))


@pytest.mark.parametrize("content", ["", "secret\nsecond-line", "x" * 8193])
def test_invalid_key_file_does_not_echo_contents(tmp_path, content):
    path = tmp_path / "key.txt"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        read_key_file(path)
    if content:
        assert content not in str(caught.value)


def test_missing_profile_is_optional(tmp_path):
    assert load_local_api_profile(tmp_path / "missing.json") is None
