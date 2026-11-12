import asyncio

import pytest

from app.db import Database
from app.gemini_client import GeminiClient, GeminiRateLimited
from app.service import ChatError, HelpdeskService

pytestmark = pytest.mark.anyio

Q1 = "What is the minimum score needed to pass the course and get a Verified Certificate?"
Q3 = "how much do i need to score to pass dpm-101?"


async def test_exact_repeat_uses_cache(make_service, fake):
    svc = make_service(fake)
    r1 = await svc.ask(Q1)
    r2 = await svc.ask(Q1)
    assert (r1.served_from, r2.served_from, r2.cache_type) == ("gemini", "cache", "exact")
    assert len(fake.calls) == 1
    st = svc.db.stats()
    assert (st["total_questions"], st["api_calls"], st["cache_hits"]) == (2, 1, 1)


async def test_paraphrase_reuses_faq_answer(make_service, fake):
    svc = make_service(fake)
    await svc.ask(Q1)
    r = await svc.ask(Q3)
    assert r.served_from == "cache" and r.cache_type == "faq"
    assert len(fake.calls) == 1
    assert fake.calls[0]["question"].startswith("What is the minimum score")  # canonical wording


async def test_different_numbers_not_merged(make_service, fake):
    svc = make_service(fake)
    await svc.ask("Is 50% enough to pass?")
    await svc.ask("Is 60% enough to pass?")
    assert len(fake.calls) == 2


async def test_unknown_sources_are_filtered(make_service, fake):
    r = await make_service(fake).ask(Q1)
    assert r.sources == ["03_grading_policy_v2.txt"]


async def test_concurrent_identical_questions_share_one_call(make_service, fake):
    fake.delay = 0.05
    svc = make_service(fake)
    results = await asyncio.gather(*[svc.ask(Q1, request_id=f"r{i}") for i in range(5)])
    assert len(fake.calls) == 1
    assert sorted(r.served_from for r in results).count("coalesced") == 4
    st = svc.db.stats()
    assert (st["api_calls"], st["cache_hits"], st["coalesced"]) == (1, 4, 4)


async def test_same_request_id_is_idempotent(make_service, fake):
    fake.delay = 0.05
    svc = make_service(fake)
    a, b = await asyncio.gather(svc.ask(Q1, request_id="dup1"), svc.ask(Q1, request_id="dup1"))
    assert len(fake.calls) == 1 and a.answer == b.answer
    assert [a.duplicate, b.duplicate].count(True) == 1
    st = svc.db.stats()
    assert st["total_questions"] == 1 and st["duplicates_suppressed"] == 1
    # a late repeat inside the TTL also returns the stored result
    c = await svc.ask(Q1, request_id="dup1")
    assert c.duplicate and len(fake.calls) == 1


async def test_request_id_reuse_with_other_question_rejected(make_service, fake):
    svc = make_service(fake)
    await svc.ask(Q1, request_id="x1")
    with pytest.raises(ChatError) as e:
        await svc.ask("When is the Capstone Product Case due?", request_id="x1")
    assert e.value.status_code == 409


async def test_errors_are_not_cached_and_recovery_works(make_service, fake):
    svc = make_service(fake)
    fake.errors = [GeminiRateLimited("429")]
    with pytest.raises(ChatError) as e:
        await svc.ask(Q1)
    assert e.value.status_code == 429 and "busy" in e.value.message
    assert svc.db.stats()["cached_answers"] == 0 and svc.db.stats()["errors"] == 1
    r = await svc.ask(Q1)                       # same question works once the API recovers
    assert r.served_from == "gemini" and len(fake.calls) == 2
    assert (await svc.ask(Q1)).served_from == "cache"


async def test_followup_uses_history_and_is_not_cached(make_service, fake):
    svc = make_service(fake)
    first = await svc.ask("When is the Capstone Product Case due?")
    cid = first.conversation_id
    await svc.ask("And what if I miss it?", conversation_id=cid)
    await svc.ask("And what if I miss it?", conversation_id=cid)
    followups = fake.calls[1:]
    assert len(followups) == 2                              # never served from cache
    assert followups[0]["history"][0][0] == "When is the Capstone Product Case due?"
    assert svc.db.stats()["cached_answers"] == 2            # exact + faq key of first question only


async def test_standalone_question_inside_conversation_still_cacheable(make_service, fake):
    svc = make_service(fake)
    r = await svc.ask(Q1)
    again = await svc.ask("When is the Capstone Product Case due?", conversation_id=r.conversation_id)
    again2 = await svc.ask("When is the Capstone Product Case due?")
    assert again.served_from == "gemini" and again2.served_from == "cache"


async def test_validation_errors(make_service, fake):
    svc = make_service(fake)
    for bad in ("", "   ", "x" * 501):
        with pytest.raises(ChatError) as e:
            await svc.ask(bad)
        assert e.value.status_code == 400
    assert svc.db.stats()["total_questions"] == 0 and not fake.calls


async def test_cache_and_counters_persist_across_restart(settings, docs, fake):
    s1 = HelpdeskService(settings, Database(settings.db_path), docs, fake)
    await s1.ask(Q1)
    s2 = HelpdeskService(settings, Database(settings.db_path), docs, fake)
    r = await s2.ask(Q1)
    assert r.served_from == "cache" and len(fake.calls) == 1
    assert s2.db.stats()["total_questions"] == 2


async def test_missing_api_key_gives_friendly_error(settings, docs):
    from dataclasses import replace
    s = replace(settings, gemini_api_key="")
    svc = HelpdeskService(s, Database(s.db_path), docs, GeminiClient(s))
    with pytest.raises(ChatError) as e:
        await svc.ask(Q1)
    assert e.value.status_code == 503 and e.value.code == "not_configured"
    assert svc.db.stats()["api_calls"] == 0 and svc.db.stats()["cached_answers"] == 0


async def test_new_docs_version_invalidates_cache(settings, docs, fake):
    from dataclasses import replace
    svc = HelpdeskService(settings, Database(settings.db_path), docs, fake)
    await svc.ask(Q1)
    new_docs = replace(docs, version="different")
    svc2 = HelpdeskService(settings, Database(settings.db_path), new_docs, fake)
    assert (await svc2.ask(Q1)).served_from == "gemini"
