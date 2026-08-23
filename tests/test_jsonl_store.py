from trailant import jsonl_store


def test_append_round_trips_unicode_content(tmp_path):
    path = tmp_path / "trails.jsonl"
    record = {"title": "Fix retry logic — now with \U0001F41C emoji and café", "count": 1}
    jsonl_store.append(path, record)

    assert jsonl_store.read_all(path) == [record]


def test_write_all_round_trips_unicode_content(tmp_path):
    path = tmp_path / "trails.jsonl"
    records = [
        {"title": "naïve café résumé"},
        {"title": "emoji \U0001F41C trail"},
    ]
    jsonl_store.write_all(path, records)

    assert jsonl_store.read_all(path) == records
