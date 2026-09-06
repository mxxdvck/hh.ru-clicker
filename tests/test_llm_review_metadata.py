from app import storage


def test_interview_persists_phase4_review_metadata():
    storage.upsert_interview(
        "neg-review", "A", llm_reply="draft", llm_sent=False,
        llm_source="llm_review", llm_category="interview",
        llm_review_reason="interview question requires explicit human review",
    )
    rows = storage.get_interviews_list(acc="A", limit=50)
    row = next(item for item in rows if item["neg_id"] == "neg-review")
    assert row["status"] == "draft"
    assert row["llm_source"] == "llm_review"
    assert row["llm_category"] == "interview"
    assert "explicit human review" in row["llm_review_reason"]


def test_sent_reply_can_clear_stale_review_reason():
    storage.upsert_interview("neg-clear", "A", llm_reply="draft", llm_sent=False, llm_review_reason="review")
    storage.upsert_interview("neg-clear", "A", llm_reply="sent", llm_sent=True, replied_msg_id="m1", llm_review_reason="")
    row = next(item for item in storage.get_interviews_list(acc="A", limit=50) if item["neg_id"] == "neg-clear")
    assert row["status"] == "replied"
    assert row["llm_review_reason"] == ""
