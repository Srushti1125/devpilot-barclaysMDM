from app.core.exceptions import AIEngineError
from app.domain.models import ChatMessage, User
from app.repositories.audit_repo import AuditRepository
from app.repositories.chat_repo import ChatRepository
from app.services.ai_engine import AIEngineClient


class ChatService:
    def __init__(
        self,
        chat_repo: ChatRepository,
        audit_repo: AuditRepository,
        ai_client: AIEngineClient,
    ):
        self.chat_repo = chat_repo
        self.audit_repo = audit_repo
        self.ai_client = ai_client

    async def send_message(self, project_id: str, message: str, user: User) -> dict:
        previous = self.chat_repo.latest_for_project(project_id, 10)
        history_text = "\n".join(
            f"{row.role.upper()}: {row.content}" for row in reversed(previous)
        )
        request_text = f"Conversation history:\n{history_text}\n\nUser question:\n{message}"
        result = await self.ai_client.generate(project_id, "conversational", request_text)
        output = result.get("output")
        if not isinstance(output, dict):
            raise AIEngineError("AI engine returned an invalid conversational response")
        answer = output.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise AIEngineError("AI engine returned an invalid conversational response")

        self.chat_repo.add_turn(ChatMessage(
            id=self.chat_repo.new_id(),
            project_id=project_id,
            user_id=user.id,
            role="user",
            content=message,
        ))
        self.chat_repo.add_turn(ChatMessage(
            id=self.chat_repo.new_id(),
            project_id=project_id,
            user_id=user.id,
            role="assistant",
            content=answer,
        ))
        self.audit_repo.record(
            user.id,
            "project.chat",
            "project",
            project_id,
            {"model_used": result.get("model_used"), "prompt_version": result.get("prompt_version")},
        )
        self.chat_repo.commit()
        return {
            "answer": answer,
            "sources": output.get("sources", []),
            "eval_score": result.get("eval_score"),
        }

    def history(self, project_id: str, limit: int) -> list[dict]:
        rows = self.chat_repo.latest_for_project(project_id, limit)
        return [
            {"role": row.role, "content": row.content, "created_at": row.created_at}
            for row in reversed(rows)
        ]
