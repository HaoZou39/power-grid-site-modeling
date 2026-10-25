"""The same conditional transitions must hold on SQLite and PostgreSQL."""

import os
from uuid import uuid4

import pytest

from backend.app.infrastructure.repository import SQLiteJobRepository


@pytest.fixture(params=["sqlite", "postgres"])
def repository(request, tmp_path):
    if request.param == "sqlite":
        return SQLiteJobRepository(tmp_path / "jobs.db")
    url = os.getenv("TEST_JOB_DATABASE_URL")
    if not url:
        pytest.skip("requires an isolated TEST_JOB_DATABASE_URL")
    from backend.app.infrastructure.postgres_repository import PostgresJobRepository
    return PostgresJobRepository(url)


def test_claim_and_cancellation_are_conditional_on_current_status(repository):
    record = repository.create_job(str(uuid4()), "demo.algorithm", "0", {"scene_name": "database-test"})
    assert repository.start_job(record.id)
    assert not repository.start_job(record.id)
    repository.cancel_job(record.id)
    assert repository.get_job(record.id).status.value == "cancelling"
    assert "database-test" in repository.active_scene_names()
    repository.fail_job(record.id, {"message": "late failure"})
    assert not repository.succeed_job(record.id, {})
    assert repository.get_job(record.id).status.value == "cancelling"
    assert repository.finish_cancel(record.id)
    assert not repository.finish_cancel(record.id)
    assert repository.get_job(record.id).status.value == "cancelled"


def test_terminal_job_cannot_be_restarted_or_cancelled(repository):
    record = repository.create_job(str(uuid4()), "demo.algorithm", "0", {})
    assert repository.start_job(record.id)
    assert repository.succeed_job(record.id, {"data": {"complete": True}})
    before = repository.get_job(record.id)
    repository.cancel_job(record.id)
    repository.fail_job(record.id, {"message": "late failure"})
    assert not repository.start_job(record.id)
    assert repository.get_job(record.id) == before


def test_late_progress_cannot_overwrite_cancelling_or_terminal_stage(repository):
    record = repository.create_job(str(uuid4()), "demo.algorithm", "0", {})
    repository.start_job(record.id)
    repository.cancel_job(record.id)
    before = repository.get_job(record.id)
    repository.update_progress(record.id, .8, "late-stage", "late message")
    assert repository.get_job(record.id) == before
    repository.finish_cancel(record.id)
    before = repository.get_job(record.id)
    repository.update_progress(record.id, .9, "another-stage", "late message")
    assert repository.get_job(record.id) == before


def test_success_commits_custom_terminal_stage_with_the_result(repository):
    record = repository.create_job(str(uuid4()), "demo.algorithm", "0", {})
    repository.start_job(record.id)
    assert repository.succeed_job(record.id, {"data":{"terminal_stage":"ready","message":"scene ready"}})
    result = repository.get_job(record.id)
    assert result.stage == "ready" and result.message == "scene ready" and result.progress == 1
