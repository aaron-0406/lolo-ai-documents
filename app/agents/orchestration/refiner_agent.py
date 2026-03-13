"""
RefinerAgent - Refines documents via chat.
Uses synchronous (non-streaming) approach for reliability with job system.
"""

import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.prompts.refiner import REFINER_SYSTEM_PROMPT
from app.utils.llm_worker import submit_to_worker


class RefinerAgent:
    """
    Refines documents based on user feedback.
    Maintains conversation context for incremental changes.
    Uses Sonnet via LLM worker for high-quality refinement.
    """

    def __init__(self):
        pass

    async def refine(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Refine the document based on user feedback (non-streaming).

        Args:
            current_draft: Current document draft
            feedback: User's feedback/request
            context: Case file context
            chat_history: Previous chat messages

        Returns:
            Dictionary with new_draft, changes, and explanation
        """
        messages = self._build_messages(
            current_draft, feedback, context, chat_history
        )

        # Use worker with Sonnet for high-quality refinement
        response = await submit_to_worker(
            messages=messages,
            model=settings.claude_model,  # Sonnet
            max_tokens=8000,
            estimated_output_tokens=4000,
        )
        return self._parse_response(response.content)

    def _build_messages(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> list:
        """Build the message list for the LLM."""
        messages = [SystemMessage(content=REFINER_SYSTEM_PROMPT)]

        # Add initial context
        case_number = context.get("case_number", "N/A")
        client_name = context.get("client_name", "N/A")

        messages.append(HumanMessage(content=f"""CONTEXTO DEL EXPEDIENTE:
- Número: {case_number}
- Cliente: {client_name}

DOCUMENTO ACTUAL:
{current_draft}
"""))

        # Add chat history (excluding current message)
        for msg in chat_history[:-1] if chat_history else []:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                messages.append(AIMessage(content=content))

        # Add current feedback
        messages.append(HumanMessage(content=f"""SOLICITUD DEL USUARIO:
{feedback}

Por favor, modifica el documento según lo solicitado.
Retorna el documento COMPLETO modificado y una breve explicación de los cambios.

Formato de respuesta:

<explicacion>
[Breve explicación de lo que hiciste - máximo 2 oraciones]
</explicacion>

<documento>
[Documento completo modificado]
</documento>

<cambios>
- Cambio 1
- Cambio 2
- Cambio 3
</cambios>
"""))

        return messages

    def _extract_section(self, content: str, tag: str) -> str:
        """Extract content between XML-like tags."""
        pattern = rf"<{tag}>(.*?)</{tag}>"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""

    def _parse_changes(self, changes_text: str) -> list[dict[str, str]]:
        """Parse changes text into a list of change objects."""
        changes = []
        for line in changes_text.split("\n"):
            line = line.strip()
            if line.startswith("-"):
                change_text = line[1:].strip()
                if change_text:
                    changes.append({
                        "section": "Documento",
                        "change": change_text,
                    })
        return changes

    def _parse_response(self, content: str) -> dict[str, Any]:
        """Parse the complete response into structured data."""
        # Extract document
        new_draft = self._extract_section(content, "documento")
        if not new_draft:
            # Fallback: use entire content if no tags found
            new_draft = content

        # Extract changes
        changes_text = self._extract_section(content, "cambios")
        changes = self._parse_changes(changes_text)

        # Extract explanation
        explanation = self._extract_section(content, "explicacion")
        if not explanation:
            explanation = "Cambios aplicados según lo solicitado."

        return {
            "new_draft": new_draft,
            "changes": changes,
            "explanation": explanation,
        }
