from app.services import notion_connection_service as service


class DummyConnection:
    user_id = 9
    access_token = "secret"
    summary_data_source_id = "data-source-id"


def test_existing_notion_row_updates_only_hit_count(monkeypatch):
    calls = []

    monkeypatch.setattr(
        service,
        "ensure_summary_database",
        lambda db, connection, raise_errors: connection,
    )

    def fake_find(self, data_source_id, source_url):
        calls.append(("find", data_source_id, source_url))
        return [{"id": "page-id", "url": "https://notion.so/row"}]

    def fake_update(self, page_id, hit_count):
        calls.append(("update", page_id, hit_count))
        return {"id": page_id, "url": "https://notion.so/row"}

    def fake_create(self, **kwargs):
        raise AssertionError("duplicate Notion rows must not be created")

    monkeypatch.setattr(
        service.NotionService,
        "find_summary_database_items_by_source_url",
        fake_find,
    )
    monkeypatch.setattr(
        service.NotionService,
        "update_summary_database_item_hit_count",
        fake_update,
    )
    monkeypatch.setattr(
        service.NotionService,
        "create_summary_database_item",
        fake_create,
    )

    page = service._create_summary_database_item_for_connection(
        db=None,
        connection=DummyConnection(),
        title="Existing title",
        summary="Existing summary",
        source_url="https://www.youtube.com/watch?v=I2giEjUHe0M",
        category="Backend",
        hit_count=8,
    )

    assert page["_a_ka_action"] == "updated_hit_count"
    assert calls == [
        ("find", "data-source-id", "https://www.youtube.com/watch?v=I2giEjUHe0M"),
        ("update", "page-id", 8),
    ]


def test_existing_duplicate_notion_rows_are_archived(monkeypatch):
    calls = []

    monkeypatch.setattr(
        service,
        "ensure_summary_database",
        lambda db, connection, raise_errors: connection,
    )

    def fake_find(self, data_source_id, source_url):
        calls.append(("find", data_source_id, source_url))
        return [
            {"id": "keep-page-id", "url": "https://notion.so/keep"},
            {"id": "archive-page-id", "url": "https://notion.so/archive"},
        ]

    def fake_update(self, page_id, hit_count):
        calls.append(("update", page_id, hit_count))
        return {"id": page_id, "url": "https://notion.so/keep"}

    def fake_archive(self, page_id):
        calls.append(("archive", page_id))
        return {"id": page_id, "archived": True}

    def fake_create(self, **kwargs):
        raise AssertionError("duplicate Notion rows must not be created")

    monkeypatch.setattr(
        service.NotionService,
        "find_summary_database_items_by_source_url",
        fake_find,
    )
    monkeypatch.setattr(
        service.NotionService,
        "update_summary_database_item_hit_count",
        fake_update,
    )
    monkeypatch.setattr(service.NotionService, "archive_page", fake_archive)
    monkeypatch.setattr(
        service.NotionService,
        "create_summary_database_item",
        fake_create,
    )

    page = service._create_summary_database_item_for_connection(
        db=None,
        connection=DummyConnection(),
        title="Existing title",
        summary="Existing summary",
        source_url="https://www.youtube.com/watch?v=I2giEjUHe0M",
        category="Backend",
        hit_count=8,
    )

    assert page["_a_ka_action"] == "updated_hit_count"
    assert calls == [
        ("find", "data-source-id", "https://www.youtube.com/watch?v=I2giEjUHe0M"),
        ("update", "keep-page-id", 8),
        ("archive", "archive-page-id"),
    ]
