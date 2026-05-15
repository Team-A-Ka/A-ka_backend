def test_duplicate_completed_passes_hit_count_to_notion(monkeypatch):
    from app.tasks import knowledge_tasks as kt

    async def fake_check_duplicate_hit_count(video_id, user_id):
        assert video_id == "video123456"
        assert user_id == 9
        return {
            "knowledge_id": "00000000-0000-0000-0000-000000000001",
            "hit_count": 4,
            "status": "COMPLETED",
            "duplicate": True,
            "counted": True,
            "title": "Saved video",
            "summary": "Saved summary",
            "category": "Backend",
        }

    captured = {}

    def fake_save_summary_to_user_notion(**kwargs):
        captured.update(kwargs)
        return {
            "id": "row-id",
            "url": "https://notion.so/row",
            "action": "updated_hit_count",
        }

    monkeypatch.setattr(kt, "check_duplicate_hit_count", fake_check_duplicate_hit_count)
    monkeypatch.setattr(kt, "save_summary_to_user_notion", fake_save_summary_to_user_notion)

    response = kt.run_core_pipeline_task(
        "https://www.youtube.com/watch?v=video123456",
        "video123456",
        9,
    )

    assert response["status"] == "duplicate_hit_count_updated_in_notion"
    assert response["hit_count"] == 4
    assert captured["hit_count"] == 4
    assert captured["category"] == "Backend"
