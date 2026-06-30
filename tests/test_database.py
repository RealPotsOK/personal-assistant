from app.database import Database


def test_profile_turn_retention_and_clear(tmp_path):
    database = Database(str(tmp_path / "test.sqlite"), max_turns=2)
    for index in range(3):
        database.add_turn("pc", f"question {index}", f"answer {index}")
    turns = database.recent_turns("pc")
    assert [turn["user_text"] for turn in turns] == ["question 1", "question 2"]
    database.clear_turns("pc")
    assert database.recent_turns("pc") == []
    database.close()


def test_memory_deduplication_relevance_delete_and_limit(tmp_path):
    database = Database(str(tmp_path / "test.sqlite"), max_memories=3)
    first = database.add_memory("pc", "User likes green tea")
    duplicate = database.add_memory("pc", "  User likes green tea ")
    database.add_memory("pc", "User lives in Canada")
    database.add_memory("pc", "User prefers short answers")
    assert first["id"] == duplicate["id"]
    values = database.memories("pc", query="tea", limit=1)
    assert values[0]["content"] == "User likes green tea"
    assert database.delete_memory("pc", values[0]["id"])
    database.add_memory("pc", "User enjoys music")
    assert len(database.memories("pc", limit=100)) == 3
    database.clear_memories("pc")
    assert database.memories("pc") == []
    database.close()


def test_device_pairing_authentication_and_revocation(tmp_path):
    database = Database(str(tmp_path / "test.sqlite"))
    paired = database.create_device(name="Kevin PC")

    assert paired["device_id"].startswith("device_")
    assert paired["device_token"].startswith("pa_")
    assert database.device_count() == 1

    auth = database.authenticate_device(paired["device_token"])
    assert auth["profile_id"] == paired["profile_id"]
    assert auth["device_name"] == "Kevin PC"

    assert database.revoke_device_token(paired["device_token"])
    assert database.authenticate_device(paired["device_token"]) is None
    assert database.device_count() == 0
    database.close()
