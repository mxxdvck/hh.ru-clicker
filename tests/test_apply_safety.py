"""Regression tests for centralized outbound-application safety."""

import asyncio
import threading
from types import SimpleNamespace

import app.application_ledger as ledger
import app.apply_safety as safety
import app.routes.apply as apply_route
from app import hh_apply, mobile_apply, oauth, storage
from app.config import CONFIG
from app.instances import bot


def _run(coro):
    return asyncio.run(coro)


def _reset_storage_cache():
    with storage._cache_lock:
        storage._cache_applied = {}
        storage._cache_tests = {}
        storage._cache_interviews = {}
        storage._cache_loaded = True


def _enable_test_sends(monkeypatch):
    _reset_storage_cache()
    monkeypatch.setattr(CONFIG, "search_only_mode", False)
    monkeypatch.setattr(CONFIG, "daily_apply_limit", 0)
    monkeypatch.setattr(CONFIG, "hh_daily_limit", 0)
    monkeypatch.setattr(CONFIG, "run_apply_limit", 0)


def test_search_only_blocks_central_reservation(monkeypatch):
    _reset_storage_cache()
    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    decision = safety.reserve_apply("acc", "100", "resume", source="test")
    assert decision.allowed is False
    assert decision.code == "search_only"
    assert not (storage.DATA_DIR / "applications.sqlite3").exists()


def test_search_only_blocks_all_low_level_senders(monkeypatch):
    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    acc = {"name": "acc", "resume_hash": "resume", "cookies": {"_xsrf": "x"}}

    web_result, web_info = _run(hh_apply.send_response_async(acc, "100"))
    q_result, q_info = _run(hh_apply.fill_and_submit_questionnaire(acc, "100"))
    mobile = mobile_apply.submit_response(acc, "100", "resume")
    oauth_result, oauth_info = oauth._oauth_apply(acc, "100")

    assert (web_result, web_info["error_type"]) == ("error", "search_only")
    assert (q_result, q_info["error_type"]) == ("error", "search_only")
    assert mobile["ok"] is False and mobile["error_type"] == "search_only"
    assert (oauth_result, oauth_info["error_type"]) == ("error", "search_only")


def test_manual_submit_search_only_never_reaches_client(monkeypatch):
    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    acc = {"name": "acc", "resume_hash": "resume", "cookies": {"_xsrf": "x"},
           "letter": "", "mode": "web"}
    monkeypatch.setattr(bot, "_get_apply_acc", lambda idx: dict(acc))
    monkeypatch.setattr(bot, "_get_apply_state", lambda idx: None)
    monkeypatch.setattr(apply_route, "get_client",
                        lambda acc: (_ for _ in ()).throw(AssertionError("client reached")))

    result = _run(apply_route.api_apply_submit({"account_idx": 0, "vacancy_id": "100"}))
    assert result["status"] == "blocked"
    assert result["reason"] == "search_only"


def test_daily_limit_counts_legacy_history(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(CONFIG, "daily_apply_limit", 1)
    storage.add_applied("acc", "old", {"at": safety._date_prefix() + "T10:00:00"})
    storage._save_executor.submit(lambda: None).result(timeout=5)

    decision = safety.reserve_apply("acc", "new", "resume", source="test")
    assert decision.allowed is False
    assert decision.code == "daily_limit"
    assert decision.daily_used >= 1


def test_run_limit_counts_successes_and_inflight(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(CONFIG, "run_apply_limit", 2)

    first = safety.reserve_apply("acc", "1", "resume", source="test")
    assert first.allowed
    safety.finalize_apply("acc", "1", "resume", "sent", {}, state=None)
    second = safety.reserve_apply("acc", "2", "resume", source="test")
    assert second.allowed

    third = safety.reserve_apply("acc", "3", "resume", source="test")
    assert third.allowed is False
    assert third.code == "run_limit"
    assert third.run_used == 2


def test_duplicate_and_inflight_are_blocked(monkeypatch):
    _enable_test_sends(monkeypatch)
    first = safety.reserve_apply("acc", "100", "resume", source="test")
    assert first.allowed

    concurrent = safety.reserve_apply("acc", "100", "resume", source="test")
    assert concurrent.allowed is False
    assert concurrent.code == "in_flight"

    safety.finalize_apply("acc", "100", "resume", "sent", {}, state=None)
    duplicate = safety.reserve_apply("acc", "100", "resume", source="test")
    assert duplicate.allowed is False
    assert duplicate.code == "already"


def test_transient_failure_can_be_retried(monkeypatch):
    _enable_test_sends(monkeypatch)
    first = safety.reserve_apply("acc", "100", "resume", source="test")
    assert first.allowed
    safety.finalize_apply("acc", "100", "resume", "error",
                          {"transient": True, "exception": "timeout"}, state=None)

    retry = safety.reserve_apply("acc", "100", "resume", source="retry")
    assert retry.allowed is True


def test_restart_marks_unknown_send_interrupted_and_blocks_retry(monkeypatch):
    _enable_test_sends(monkeypatch)
    first = safety.reserve_apply("acc", "100", "resume", source="test")
    assert first.allowed

    assert ledger.mark_interrupted_startup() == 1
    retry = safety.reserve_apply("acc", "100", "resume", source="retry")
    assert retry.allowed is False
    assert retry.code == "in_flight"
    assert "interrupted" in retry.message


def test_finalize_sent_updates_legacy_storage_and_state_once(monkeypatch):
    _enable_test_sends(monkeypatch)
    state = type("State", (), {
        "sent": 0, "daily_sent": 0, "questionnaire_sent": 0,
        "hh_today_applies": 0,
    })()
    assert safety.reserve_apply("acc", "100", "resume", state=state, source="test").allowed
    safety.finalize_apply("acc", "100", "resume", "sent",
                          {"title": "Vacancy"}, state=state, questionnaire=True)

    assert state.sent == 1
    assert state.daily_sent == 1
    assert state.questionnaire_sent == 1
    assert storage.is_applied("acc", "100") is True
    assert ledger.count_applied_today("acc", safety._date_prefix()) == 1


def test_parallel_reservations_cannot_overshoot_limit(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(CONFIG, "daily_apply_limit", 3)
    results = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker(i):
        barrier.wait()
        decision = safety.reserve_apply("acc", str(100 + i), "resume", source="parallel")
        with results_lock:
            results.append(decision)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    allowed = [item for item in results if item.allowed]
    blocked = [item for item in results if not item.allowed]
    assert len(allowed) == 3
    assert len(blocked) == 7
    assert all(item.code == "daily_limit" for item in blocked)
    assert ledger.count_inflight_today("acc", safety._date_prefix()) == 3


def test_hh_counter_can_close_smaller_local_limit_gap(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(CONFIG, "daily_apply_limit", 50)
    monkeypatch.setattr(CONFIG, "hh_daily_limit", 200)
    state = type("State", (), {"daily_sent": 2, "hh_today_applies": 50})()

    decision = safety.reserve_apply("acc", "100", "resume", state=state, source="test")
    assert decision.allowed is False
    assert decision.code == "daily_limit"
    assert decision.daily_used == 50


def test_search_only_transport_error_releases_reservation(monkeypatch):
    _enable_test_sends(monkeypatch)
    assert safety.reserve_apply("acc", "200", "resume", source="test").allowed
    safety.finalize_apply("acc", "200", "resume", "error",
                          {"error_type": "search_only"}, state=None)
    retry = safety.reserve_apply("acc", "200", "resume", source="retry")
    assert retry.allowed is True


def test_letter_required_error_releases_for_retry(monkeypatch):
    _enable_test_sends(monkeypatch)
    assert safety.reserve_apply("acc", "201", "resume", source="test").allowed
    safety.finalize_apply("acc", "201", "resume", "error",
                          {"error_type": "letter_required"}, state=None)
    retry = safety.reserve_apply("acc", "201", "resume", source="retry")
    assert retry.allowed is True


def test_run_limit_is_scoped_to_explicit_bot_run(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(CONFIG, "run_apply_limit", 1)
    state_a = type("State", (), {"apply_run_id": "run-a", "daily_sent": 0,
                                  "hh_today_applies": 0})()
    state_b = type("State", (), {"apply_run_id": "run-b", "daily_sent": 0,
                                  "hh_today_applies": 0})()
    assert safety.reserve_apply("acc", "301", "resume", state=state_a, source="a").allowed
    safety.finalize_apply("acc", "301", "resume", "sent", {}, state=state_a)
    assert safety.reserve_apply("acc", "302", "resume", state=state_a, source="a").code == "run_limit"
    assert safety.reserve_apply("acc", "302", "resume", state=state_b, source="b").allowed


def test_ledger_quota_transaction_is_atomic_without_process_lock(monkeypatch):
    _enable_test_sends(monkeypatch)
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        result = ledger.reserve_application(
            "atomic", str(500 + i), "resume", "direct", "shared-run",
            date_prefix=safety._date_prefix(), daily_limit=2,
        )
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sum(1 for ok, *_ in results if ok) == 2
    assert sum(1 for ok, reason, *_ in results if not ok and reason == "daily_limit") == 6


def test_applied_at_controls_daily_quota_date(monkeypatch):
    _enable_test_sends(monkeypatch)
    ok, _, _, _ = ledger.reserve_application("acc", "old", "r")
    assert ok
    ledger.mark_application(
        "acc", "old", "r", status="applied",
        applied_at="2000-01-01T12:00:00+03:00",
    )
    assert ledger.count_applied_today("acc", "2000-01-01") == 1
    assert ledger.count_applied_today("acc", safety._date_prefix()) == 0


def test_storage_recovery_can_preserve_original_timestamp(monkeypatch):
    _enable_test_sends(monkeypatch)
    original = "2001-02-03T04:05:06+03:00"
    storage.add_applied("acc", "v-old", {"at": original})
    storage._save_executor.submit(lambda: None).result(timeout=5)
    with storage._cache_lock:
        assert storage._cache_applied["acc"]["v-old"]["at"] == original


def _reconcile_state():
    return SimpleNamespace(
        name="acc", short="a", color="green", acc={"name": "acc"},
        apply_run_id="run-1", daily_date=safety._date_prefix(), daily_sent=0,
    )


def test_reconciliation_confirms_interrupted_vacancy(monkeypatch):
    _enable_test_sends(monkeypatch)
    import app.manager as manager_mod
    ok, _, _, _ = ledger.reserve_application("acc", "v1", "r1")
    assert ok
    assert ledger.mark_interrupted_startup() == 1

    class Client:
        def fetch_negotiations(self, max_pages=5):
            return {"vacancy_ids": ["v1"], "auth_error": False}
        def fetch_negotiations_metadata(self):
            return {}

    monkeypatch.setattr(manager_mod, "get_client", lambda acc: Client())
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr._add_log = lambda *args, **kwargs: None
    state = _reconcile_state()
    result = mgr._reconcile_interrupted_applications(state)
    assert result == {"checked": 1, "recovered": 1, "unresolved": 0}
    assert storage.is_applied("acc", "v1") is True
    assert ledger.list_interrupted("acc") == []


def test_reconciliation_never_retries_unconfirmed_vacancy(monkeypatch):
    _enable_test_sends(monkeypatch)
    import app.manager as manager_mod
    ok, _, _, _ = ledger.reserve_application("acc", "v2", "r1")
    assert ok
    ledger.mark_interrupted_startup()

    class Client:
        def fetch_negotiations(self, max_pages=5):
            return {"vacancy_ids": ["other"], "auth_error": False}
        def fetch_negotiations_metadata(self):
            return {"topics_by_vid": {"other": {}}}

    monkeypatch.setattr(manager_mod, "get_client", lambda acc: Client())
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr._add_log = lambda *args, **kwargs: None
    state = _reconcile_state()
    result = mgr._reconcile_interrupted_applications(state)
    assert result == {"checked": 1, "recovered": 0, "unresolved": 1}
    assert storage.is_applied("acc", "v2") is False
    assert ledger.list_interrupted("acc")[0]["vacancy_id"] == "v2"
    decision = safety.reserve_apply("acc", "v2", "r1", state=state, source="retry")
    assert decision.allowed is False
    assert decision.code == "in_flight"


def test_retry_updates_attempt_timestamp_for_crash_recovery(monkeypatch):
    _enable_test_sends(monkeypatch)
    monkeypatch.setattr(ledger, "_now", lambda: "2000-01-01T12:00:00+03:00")
    ok, _, _, _ = ledger.reserve_application("acc", "retry", "r")
    assert ok
    ledger.mark_application("acc", "retry", "r", status="failed_transient")

    monkeypatch.setattr(ledger, "_now", lambda: "2001-02-03T04:05:06+03:00")
    ok, _, _, _ = ledger.reserve_application("acc", "retry", "r")
    assert ok
    ledger.mark_interrupted_startup()
    row = ledger.list_interrupted("acc")[0]
    assert row["attempted_at"] == "2001-02-03T04:05:06+03:00"


def test_prepare_apply_accounts_generates_letter_per_vacancy(monkeypatch):
    _enable_test_sends(monkeypatch)
    import app.manager as manager_mod
    monkeypatch.setattr(CONFIG, "llm_generate_cover_letter", True)
    monkeypatch.setattr(CONFIG, "llm_use_resume", False)
    monkeypatch.setattr(manager_mod, "fetch_vacancy_details", lambda acc, vid: {})
    calls = []
    def generate(**kwargs):
        calls.append(kwargs["account_key"])
        return "letter:" + kwargs["vacancy_title"]
    monkeypatch.setattr(manager_mod, "generate_llm_cover_letter", generate)

    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr._add_log = lambda *args, **kwargs: None
    state = SimpleNamespace(
        short="a", color="green",
        vacancy_meta={
            "1": {"title": "First", "company": "A"},
            "2": {"title": "Second", "company": "B"},
        },
    )
    acc = {"name": "acc", "letter": "fallback"}
    prepared = mgr._prepare_apply_accounts(state, acc, ["1", "2"])

    assert prepared["1"]["letter"] == "letter:First"
    assert prepared["2"]["letter"] == "letter:Second"
    assert prepared["1"] is not prepared["2"]
    assert acc["letter"] == "fallback"
    assert calls == ["cover:a:1", "cover:a:2"]


def test_manual_resume_after_run_limit_starts_new_run(monkeypatch):
    import app.manager as manager_mod
    old_run = "old-run"
    state = SimpleNamespace(
        paused=True, paused_reason="run_limit", hard_stopped=True,
        limit_exceeded=False, limit_reset_time=None, consecutive_errors=0,
        apply_run_id=old_run, _apply_reconciled_run_id=old_run,
        _state_lock=threading.Lock(), short="a", color="green",
    )
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr.account_states = [state]
    mgr.temp_states = {}
    mgr._add_log = lambda *args, **kwargs: None

    mgr.toggle_account_pause(0)
    assert state.paused is False
    assert state.paused_reason == ""
    assert state.apply_run_id != old_run
    assert state._apply_reconciled_run_id == ""


def test_sync_hh_apply_count_updates_authoritative_state(monkeypatch):
    import app.manager as manager_mod
    state = SimpleNamespace(
        acc={"name": "acc"}, short="a", hh_today_applies=0,
        hh_today_applies_updated="", _state_lock=threading.Lock(),
    )
    monkeypatch.setattr(
        manager_mod, "fetch_negotiations_today_count",
        lambda acc, force=True: {"today": 17, "msk_date": manager_mod._today_msk()},
    )
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    info = mgr._sync_hh_apply_count(state, force=True)
    assert info["today"] == 17
    assert state.hh_today_applies == 17
    assert state.hh_today_applies_updated


def test_transient_apply_error_classifier():
    import app.manager as manager_mod

    assert manager_mod._is_transient_apply_error({"transient": True}) is True
    assert manager_mod._is_transient_apply_error({"exception": "timeout"}) is True
    assert manager_mod._is_transient_apply_error({"http_status": 503}) is True
    assert manager_mod._is_transient_apply_error({"error_code": "unknown"}) is True
    assert manager_mod._is_transient_apply_error({"http_status": 400, "raw": "bad request"}) is False


def test_questionnaire_failure_gets_one_retry_then_blocks(monkeypatch):
    _enable_test_sends(monkeypatch)
    import app.manager as manager_mod

    state = SimpleNamespace(_test_failures={})
    assert safety.reserve_apply("acc", "q1", "resume", source="apply").allowed
    safety.finalize_apply("acc", "q1", "resume", "test", {}, state=None)
    assert safety.reserve_apply("acc", "q1", "resume", source="questionnaire").allowed

    failures, info = manager_mod._questionnaire_failure_attempt(state, "q1", {})
    assert failures == 1 and info["transient"] is True
    safety.finalize_apply("acc", "q1", "resume", "error", info, state=None)
    assert safety.reserve_apply("acc", "q1", "resume", source="retry").allowed

    safety.finalize_apply("acc", "q1", "resume", "test", {}, state=None)
    assert safety.reserve_apply("acc", "q1", "resume", source="questionnaire").allowed
    failures, info = manager_mod._questionnaire_failure_attempt(state, "q1", {})
    assert failures == 2 and info["transient"] is False
    safety.finalize_apply("acc", "q1", "resume", "error", info, state=None)
    blocked = safety.reserve_apply("acc", "q1", "resume", source="third")
    assert blocked.allowed is False
    assert blocked.code == "in_flight"
    assert "failed_permanent" in blocked.message


def test_worker_crash_marks_current_run_interrupted(monkeypatch):
    _enable_test_sends(monkeypatch)
    import app.manager as manager_mod

    state = SimpleNamespace(
        name="acc", short="a", color="green", apply_run_id="worker-run",
        _apply_reconciled_run_id="worker-run", _deleted=False,
        status="applying", status_detail="",
    )
    assert safety.reserve_apply("acc", "crash1", "resume", state=state, source="worker").allowed

    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr._stop_event = threading.Event()
    mgr._add_log = lambda *args, **kwargs: None
    mgr._run_account_worker_inner = lambda idx, current: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setattr(manager_mod.time, "sleep", lambda seconds: setattr(state, "_deleted", True))

    mgr._run_account_worker(0, state)
    interrupted = ledger.list_interrupted("acc")
    assert [row["vacancy_id"] for row in interrupted] == ["crash1"]
    assert state._apply_reconciled_run_id == ""


def test_web_apply_missing_xsrf_is_auth_error(monkeypatch):
    _enable_test_sends(monkeypatch)
    result, info = _run(hh_apply.send_response_async(
        {"name": "acc", "resume_hash": "resume", "cookies": {}}, "100"
    ))
    assert result == "auth_error"
    assert info["error_type"] == "auth_error"


def test_clean_install_uses_conservative_apply_defaults():
    from app.config import Config

    defaults = Config()
    assert defaults.search_only_mode is True
    assert defaults.batch_responses == 1
    assert defaults.response_delay >= 10
    assert defaults.related_vacancies_enabled is False
    assert defaults.hh_ai_letter_first_try is False


def test_search_filter_label_priority_is_deterministic(monkeypatch):
    import app.manager as manager_mod

    monkeypatch.setattr(CONFIG, "filter_low_competition", True)
    monkeypatch.setattr(CONFIG, "filter_agencies", True)
    monkeypatch.setattr(CONFIG, "search_period_days", 7)
    suffix = manager_mod._search_filter_query_suffix()
    assert "&label=low_performance" in suffix
    assert "&label=not_from_agency" not in suffix
    assert "&search_period=7" in suffix


def test_manual_recoverable_errors_release_reservation(monkeypatch):
    _enable_test_sends(monkeypatch)
    for vid, error_type in (
        ("manual-validation", "questionnaire_validation"),
        ("manual-http", "manual_recoverable"),
    ):
        assert safety.reserve_apply("acc", vid, "resume", source="manual").allowed
        status = safety.finalize_apply(
            "acc", vid, "resume", "error", {"error_type": error_type}, state=None
        )
        assert status == "released"
        assert safety.reserve_apply("acc", vid, "resume", source="manual-retry").allowed


def test_ledger_timestamp_uses_moscow_date_independent_of_host_timezone():
    from datetime import datetime, timedelta
    from app import application_ledger as ledger_module

    stamp = datetime.fromisoformat(ledger_module._now())
    assert stamp.utcoffset() == timedelta(hours=3)


def test_search_only_approved_context_is_narrow(monkeypatch):
    from app.apply_mode import set_approved_search_apply

    _reset_storage_cache()
    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    monkeypatch.setattr(CONFIG, "daily_apply_limit", 0)
    monkeypatch.setattr(CONFIG, "hh_daily_limit", 0)
    monkeypatch.setattr(CONFIG, "run_apply_limit", 1)
    set_approved_search_apply(False)

    blocked = safety.reserve_apply("acc", "blocked-1", "resume", source="test")
    assert blocked.allowed is False
    assert blocked.code == "search_only"

    set_approved_search_apply(True)
    try:
        approved = safety.reserve_apply("acc", "approved-1", "resume", source="approved-search")
        assert approved.allowed is True

        other_context_codes = []

        def check_other_thread():
            other_context_codes.append(safety.check_apply_allowed("acc", "other-thread").code)

        thread = threading.Thread(target=check_other_thread)
        thread.start()
        thread.join(timeout=5)
        assert other_context_codes == ["search_only"]

        limited = safety.reserve_apply("acc", "approved-2", "resume", source="approved-search")
        assert limited.allowed is False
        assert limited.code == "run_limit"
    finally:
        safety.finalize_apply(
            "acc", "approved-1", "resume", "error",
            {"transient": True}, state=None,
        )
        set_approved_search_apply(False)


def test_apply_search_results_resumes_exact_existing_queue(monkeypatch):
    import app.manager as manager_mod
    from app.state import AccountState

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    state = AccountState({
        "name": "acc",
        "short": "a",
        "color": "#fff",
        "urls": [],
    })
    state.vacancies_queue = ["101", "102"]
    state.total_vacancies = 2
    state.paused = True
    state.paused_reason = "search_only"
    state.status = "search_only"

    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr.account_states = [state]
    mgr.temp_states = {}
    mgr._add_log = lambda *args, **kwargs: None

    resumed = []
    monkeypatch.setattr(
        "app.ws_manager.ws_manager.resume_account",
        lambda idx: resumed.append(idx),
    )

    assert mgr.apply_search_results(0) is True
    assert state.vacancies_queue == ["101", "102"]
    assert state.total_vacancies == 2
    assert state._apply_search_results_requested is True
    assert state._apply_search_results_ids is None
    assert state.paused is False
    assert state.paused_reason == ""
    assert state.status == "applying"
    assert resumed == [0]

def test_apply_search_results_accepts_only_existing_subset(monkeypatch):
    import app.manager as manager_mod
    from app.state import AccountState

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    state = AccountState({"name": "acc", "short": "a", "color": "#fff", "urls": []})
    state.vacancies_queue = ["101", "102", "103"]
    state.total_vacancies = 3
    state.paused = True
    state.paused_reason = "search_only"
    state.status = "search_only"
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr.account_states = [state]
    mgr.temp_states = {}
    mgr._add_log = lambda *args, **kwargs: None
    monkeypatch.setattr("app.ws_manager.ws_manager.resume_account", lambda idx: None)

    assert mgr.apply_search_results(0, vacancy_ids=["103", "101", "103"]) is True
    assert state.vacancies_queue == ["101", "103"]
    assert state.total_vacancies == 2
    assert state._apply_search_results_ids == ["103", "101"]
    assert state._apply_search_results_requested is True


def test_apply_search_results_rejects_unknown_subset_without_unpausing(monkeypatch):
    import app.manager as manager_mod
    from app.state import AccountState

    monkeypatch.setattr(CONFIG, "search_only_mode", True)
    state = AccountState({"name": "acc", "short": "a", "color": "#fff", "urls": []})
    state.vacancies_queue = ["101", "102"]
    state.total_vacancies = 2
    state.paused = True
    state.paused_reason = "search_only"
    state.status = "search_only"
    mgr = manager_mod.BotManager.__new__(manager_mod.BotManager)
    mgr.account_states = [state]
    mgr.temp_states = {}
    mgr._add_log = lambda *args, **kwargs: None

    assert mgr.apply_search_results(0, vacancy_ids=["101", "999"]) is False
    assert state.vacancies_queue == ["101", "102"]
    assert state._apply_search_results_requested is False
    assert state._apply_search_results_ids is None
    assert state.paused is True
    assert state.paused_reason == "search_only"


def test_application_ledger_status_counts(monkeypatch):
    _enable_test_sends(monkeypatch)

    ok, *_ = ledger.reserve_application("ops", "1", "r", "test", "run")
    assert ok
    ledger.mark_application("ops", "1", "r", status="applied")

    ok, *_ = ledger.reserve_application("ops", "2", "r", "test", "run")
    assert ok
    ledger.mark_application("ops", "2", "r", status="failed_permanent")

    ok, *_ = ledger.reserve_application("ops", "3", "r", "test", "run")
    assert ok

    assert ledger.get_status_counts("ops") == {
        "applied": 1,
        "applying": 1,
        "failed_permanent": 1,
    }
    assert ledger.get_status_counts("another") == {}
