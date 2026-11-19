import json
from pathlib import Path

import numpy as np

from hub.dashboard import providers as p
from hub.storage import NotesRepo, TranscriptsRepo, connect, norm_tags
from hub.transcription import engine


def test_notes_repo(tmp_path):
    r = NotesRepo(connect(tmp_path / "t.db"))
    f = r.add_folder("Pro")
    sub = r.add_folder("Clients", f)
    a = r.create(f, "Réunion")
    b = r.create(None, "Courses")
    r.save(a, "Réunion lundi", "<p>budget</p>", "budget 2027")
    r.set_tags(a, "Travail; urgent, travail")
    r.set_pinned(b, True)
    assert r.get(a).tags == "travail, urgent"
    assert [x["id"] for x in r.search()] == [b, a]  # épinglée d'abord
    assert [x["id"] for x in r.search("budget")] == [a]
    assert [x["id"] for x in r.search(tag="urgent")] == [a]
    assert [x["id"] for x in r.search(folder_id=None, all_folders=False)] == [b]
    assert r.all_tags() == ["travail", "urgent"]
    r.delete_folder(f)  # cascade sous-dossier, note conservée
    assert r.folders() == [] and r.get(a).folder_id is None
    assert sub


def test_norm_tags():
    assert norm_tags(" A, b;a ,, ") == "a, b"


def test_transcripts_repo(tmp_path):
    r = TranscriptsRepo(connect(tmp_path / "t.db"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x")
    t = r.create("Enr", str(wav), 3.2)
    r.update(t, text="bonjour", language="fr", audio_path="ignored")
    assert r.get(t)["text"] == "bonjour" and r.get(t)["audio_path"] == str(wav)
    assert len(r.list("bonj")) == 1
    r.delete(t)
    assert not wav.exists() and r.get(t) is None


def test_wav_roundtrip(tmp_path):
    audio = (np.sin(np.linspace(0, 100, 16000)) * 0.5).astype(np.float32).reshape(-1, 1)
    engine.write_wav(tmp_path / "s.wav", audio)
    back = engine.read_wav(tmp_path / "s.wav")
    assert back.shape == (16000,) and np.allclose(back, audio.reshape(-1), atol=1e-3)


def test_parse_anthropic():
    u = p.Usage("x")
    p.parse_anthropic_usage([{"data": [{"starting_at": "2026-11-01T00:00:00Z", "results": [
        {"model": "claude-opus-4-8", "uncached_input_tokens": 10, "output_tokens": 5,
         "cache_read_input_tokens": 2,
         "cache_creation": {"ephemeral_5m_input_tokens": 1, "ephemeral_1h_input_tokens": 3}}]}]}], u)
    p.parse_anthropic_cost([{"data": [{"starting_at": "2026-11-01T00:00:00Z",
                                       "results": [{"amount": "123.5"}]}]}], u)
    assert u.total() == {"input": 10, "output": 5, "cache_read": 2, "cache_write": 4}
    assert abs(u.total_cost() - 1.235) < 1e-9


def test_parse_openai():
    u = p.Usage("x")
    p.parse_openai_usage([{"data": [{"start_time": 1761955200, "results": [
        {"model": "gpt-5", "input_tokens": 100, "input_cached_tokens": 40, "output_tokens": 7,
         "num_model_requests": 3}]}]}], u)
    p.parse_openai_cost([{"data": [{"start_time": 1761955200,
                                    "results": [{"amount": {"value": 0.42, "currency": "usd"}}]}]}], u)
    assert u.by_model()["gpt-5"] == {"input": 60, "output": 7, "cache_read": 40, "requests": 3}
    assert list(u.by_day()) == ["2025-11-01"] and u.total_cost() == 0.42


def test_claude_code_logs(tmp_path):
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    line = {"timestamp": ts, "requestId": "r1", "message": {
        "id": "m1", "model": "claude-sonnet", "usage": {
            "input_tokens": 3, "output_tokens": 9, "cache_read_input_tokens": 1,
            "cache_creation_input_tokens": 2}}}
    d = tmp_path / "proj"
    d.mkdir()
    (d / "s.jsonl").write_text("\n".join([json.dumps(line)] * 2 + ["garbage"]))
    u = p.read_claude_code(30, tmp_path)
    assert u.total() == {"input": 3, "output": 9, "cache_read": 1, "cache_write": 2, "requests": 1}
    assert p.read_claude_code(30, Path(tmp_path / "absent")).total() == {}
