from types import SimpleNamespace

import pytest

from app.core.exceptions import AIEngineError
from app.domain.models import ChatMessage
from app.services.chat_service import ChatService


class FakeChatRepository:
    def __init__(self, history=None):
        self.history_rows = history or []
        self.added = []
        self.commits = 0

    def latest_for_project(self, project_id, limit):
        assert project_id == "project-1"
        assert limit == 10 or limit == 3
        return self.history_rows[:limit]

    @staticmethod
    def new_id():
        return "message-id"

    def add_turn(self, message):
        self.added.append(message)

    def commit(self):
        self.commits += 1


class FakeAuditRepository:
    def __init__(self):
        self.events = []

    def record(self, *args):
        self.events.append(args)


class FakeAIClient:
    def __init__(self, result):
        self.result = result
        self.request = None

    async def generate(self, *args):
        self.request = args
        return self.result


@pytest.mark.asyncio
async def test_chat_service_sends_context_persists_turns_and_audits(dev_user):
    history = [
        ChatMessage(role="assistant", content="Earlier answer"),
        ChatMessage(role="user", content="Earlier question"),
    ]
    chat_repo = FakeChatRepository(history)
    audit_repo = FakeAuditRepository()
    ai_client = FakeAIClient({
        "output": {"answer": "Current answer", "sources": ["spec.md"]},
        "eval_score": 0.94,
        "model_used": "test-model",
        "prompt_version": "conversational_v1",
    })
    service = ChatService(chat_repo, audit_repo, ai_client)

    result = await service.send_message("project-1", "Current question", dev_user)

    assert result == {
        "answer": "Current answer",
        "sources": ["spec.md"],
        "eval_score": 0.94,
    }
    assert ai_client.request[0:2] == ("project-1", "conversational")
    assert "USER: Earlier question\nASSISTANT: Earlier answer" in ai_client.request[2]
    assert ai_client.request[2].endswith("User question:\nCurrent question")
    assert [(message.role, message.content) for message in chat_repo.added] == [
        ("user", "Current question"),
        ("assistant", "Current answer"),
    ]
    assert chat_repo.commits == 1
    assert audit_repo.events[0][1:] == (
        "project.chat",
        "project",
        "project-1",
        {"model_used": "test-model", "prompt_version": "conversational_v1"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [None, {}, {"answer": "  "}, "invalid output", ["invalid output"]],
)
async def test_chat_service_rejects_missing_answer_without_persisting(dev_user, output):
    chat_repo = FakeChatRepository()
    audit_repo = FakeAuditRepository()
    service = ChatService(chat_repo, audit_repo, FakeAIClient({"output": output}))

    with pytest.raises(AIEngineError, match="invalid conversational response"):
        await service.send_message("project-1", "Question", dev_user)

    assert chat_repo.added == []
    assert chat_repo.commits == 0
    assert audit_repo.events == []


def test_chat_history_returns_oldest_first():
    rows = [
        SimpleNamespace(role="assistant", content="Second", created_at="t2"),
        SimpleNamespace(role="user", content="First", created_at="t1"),
    ]
    service = ChatService(FakeChatRepository(rows), FakeAuditRepository(), FakeAIClient({}))

    assert service.history("project-1", 3) == [
        {"role": "user", "content": "First", "created_at": "t1"},
        {"role": "assistant", "content": "Second", "created_at": "t2"},
    ]
