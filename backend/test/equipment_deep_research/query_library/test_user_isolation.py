"""验证 Query 的列表、详情、写操作、后台结果与幂等键按用户隔离。"""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine

from equipment_deep_research.domain.platform_identity import PlatformIdentity, platform_identity
from equipment_deep_research.query_library.models import GeneratedCandidate, QueryNotFoundError, GenerationNotFoundError
from equipment_deep_research.query_library.persistence import QueryLibraryRepository


@contextmanager
def identity(uid, superadmin=False):
    token = platform_identity.set(PlatformIdentity(uid, "tenant-a", superadmin))
    try:
        yield
    finally:
        platform_identity.reset(token)


@pytest.fixture
def repo(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'queries.db'}")
    repository = QueryLibraryRepository(engine)
    yield repository
    engine.dispose()


def create(repo, query="同一研究问题"):
    return repo.create_query(query=query, supplemental_information="", generation_rationale="", source_references=())


def test_same_query_is_private_and_deduplicated_per_user(repo):
    with identity("alice"):
        alice = create(repo)
    with identity("bob"):
        bob = create(repo)
        rows, total = repo.list_queries()
        assert total == 1 and [r.query_id for r in rows] == [bob.query_id]
        assert bob.owner_uid == "bob"
        for operation in (
            lambda: repo.get_query(alice.query_id),
            lambda: repo.update_query(alice.query_id, expected_version=1, query="stolen"),
            lambda: repo.delete_query(alice.query_id),
            lambda: repo.list_revisions(alice.query_id),
            lambda: repo.set_query_status(alice.query_id, status="published"),
        ):
            with pytest.raises(QueryNotFoundError):
                operation()
    with identity("root", True):
        assert repo.list_queries()[1] == 2
        assert repo.get_query(alice.query_id).query == "同一研究问题"
        updated = repo.update_query(
            alice.query_id,
            expected_version=1,
            query="超级管理员代管后的研究问题",
            knowledge_ids=["kb-alice"],
            knowledge_ids_present=True,
        )
        assert updated.owner_uid == "alice"
        assert updated.query == "超级管理员代管后的研究问题"
        assert updated.knowledge_ids == ("kb-alice",)
        repo.delete_query(bob.query_id)
        with pytest.raises(QueryNotFoundError):
            repo.get_query(bob.query_id)


def test_legacy_query_never_becomes_owned_by_first_visitor(repo):
    legacy = create(repo)
    with identity("alice"):
        assert repo.list_queries()[1] == 0
        with pytest.raises(QueryNotFoundError):
            repo.get_query(legacy.query_id)
    with identity("root", True):
        assert repo.get_query(legacy.query_id).owner_uid == ""


def test_generation_idempotency_and_results_inherit_creator(repo):
    def submit():
        return repo.create_generation(
            topic="test",
            supplemental_information="",
            reference_urls=(),
            model_config={},
            requested_count=1,
            idempotency_key="shared-client-key",
        )

    with identity("alice"):
        alice = submit()
        assert submit().generation_id == alice.generation_id
    with identity("bob"):
        bob = submit()
        assert bob.generation_id != alice.generation_id
        assert len(repo.list_generations()) == 1
        for operation in (repo.get_generation, repo.cancel_generation, repo.delete_generation, repo.retry_generation):
            with pytest.raises(GenerationNotFoundError):
                operation(alice.generation_id)
    with identity("root", True):
        cancelled = repo.cancel_generation(bob.generation_id)
        assert cancelled.status == "cancelled" and cancelled.owner_uid == "bob"
        repo.delete_generation(bob.generation_id)
        with pytest.raises(GenerationNotFoundError):
            repo.get_generation(bob.generation_id)
    # Background workers have no HTTP context and still preserve the stored creator.
    repo.claim_generation(alice.generation_id, worker_id="test-worker")
    completed = repo.complete_generation(
        alice.generation_id,
        candidates=(
            GeneratedCandidate(
                coverage_slot="one",
                query="generated result",
                supplemental_information="",
                generation_rationale="",
                source_references=(),
            ),
        ),
        search_queries=(),
        source_references=(),
        provider_snapshot={},
    )
    with identity("alice"):
        assert repo.get_query(completed.result_query_ids[0]).owner_uid == "alice"
    with identity("bob"):
        assert repo.list_queries()[1] == 0
        assert repo.existing_query_texts() == []
