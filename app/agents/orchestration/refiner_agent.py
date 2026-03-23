"""
RefinerAgent - Conversational document refinement via chat.
Uses synchronous (non-streaming) approach for reliability with job system.
Supports both informational responses and document edits.
"""

import re
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger
from pydantic import BaseModel

from app.config import settings
from app.prompts.refiner import REFINER_SYSTEM_PROMPT
from app.utils.llm_worker import submit_to_worker
from app.services.token_reporter import (
    init_token_usage_async,
    accumulate_tokens_async,
    mark_operation_completed_async,
)


class RefineTokenTrackingContext(BaseModel):
    """Context for immediate token tracking in refine operations."""
    session_id: str
    job_id: Optional[str] = None
    judicial_case_file_id: int
    document_type: str
    customer_id: int
    customer_has_bank_id: int
    created_by_customer_user_id: int


class RefinerAgent:
    """
    Conversational document refinement agent.
    Can answer questions about the case/laws OR modify the document.
    Uses Sonnet via LLM worker for high-quality responses.
    """

    def __init__(self):
        pass

    async def refine(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
        custom_instructions: Optional[str] = None,
        token_tracking: Optional[RefineTokenTrackingContext] = None,
    ) -> dict[str, Any]:
        """
        Process user feedback - either answer questions or modify document.

        Args:
            current_draft: Current document draft
            feedback: User's message/question/request
            context: Case file context
            chat_history: Previous chat messages
            custom_instructions: Optional learning rules to apply
            token_tracking: Optional context for immediate token tracking

        Returns:
            Dictionary with response_type, new_draft (if edit), and explanation
        """
        # Initialize token tracking record if context provided
        token_record_id: Optional[int] = None
        if token_tracking:
            token_record_id = await init_token_usage_async(
                session_id=token_tracking.session_id,
                judicial_case_file_id=token_tracking.judicial_case_file_id,
                document_type=token_tracking.document_type,
                operation_type="REFINE",
                model_used=settings.claude_model,
                customer_id=token_tracking.customer_id,
                customer_has_bank_id=token_tracking.customer_has_bank_id,
                created_by_customer_user_id=token_tracking.created_by_customer_user_id,
                job_id=token_tracking.job_id,
            )
            if token_record_id:
                logger.info(f"[TokenTracking] Initialized record {token_record_id} for REFINE")

        try:
            messages = self._build_messages(
                current_draft, feedback, context, chat_history, custom_instructions
            )

            # Use worker with Sonnet for high-quality responses
            llm_response = await submit_to_worker(
                messages=messages,
                model=settings.claude_model,  # Sonnet
                max_tokens=8000,
                estimated_output_tokens=4000,
            )

            input_tokens = llm_response.token_usage.input_tokens
            output_tokens = llm_response.token_usage.output_tokens

            # IMMEDIATE TOKEN TRACKING: Accumulate after Claude call
            if token_record_id and (input_tokens > 0 or output_tokens > 0):
                await accumulate_tokens_async(token_record_id, input_tokens, output_tokens)

            # Parse the response and include token usage
            result = self._parse_response(llm_response.message.content)

            # Add token usage to result
            result["token_usage"] = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": llm_response.token_usage.model,
            }
            result["token_record_id"] = token_record_id

            # Mark operation as completed successfully
            if token_record_id:
                await mark_operation_completed_async(token_record_id, success=True)
                logger.info(f"[TokenTracking] Marked record {token_record_id} as completed")

            return result

        except Exception as e:
            # Mark operation as failed if we have a token record
            if token_record_id:
                await mark_operation_completed_async(token_record_id, success=False)
                logger.info(f"[TokenTracking] Marked record {token_record_id} as failed")
            raise

    def _build_messages(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
        custom_instructions: Optional[str] = None,
    ) -> list:
        """Build the message list for the LLM."""
        # Start with system prompt
        system_prompt = REFINER_SYSTEM_PROMPT

        # Add custom instructions (learnings) to system prompt if provided
        if custom_instructions:
            system_prompt += f"""

## INSTRUCCIONES ADICIONALES DEL ESTUDIO
{custom_instructions}
"""

        messages = [SystemMessage(content=system_prompt)]

        # Add initial context with document
        case_number = context.get("case_number", "N/A")
        client_name = context.get("client_name", "N/A")

        context_message = f"""CONTEXTO DEL EXPEDIENTE:
- Número de expediente: {case_number}
- Cliente/Demandado: {client_name}

DOCUMENTO ACTUAL:
{current_draft}
"""
        messages.append(HumanMessage(content=context_message))

        # Add summarized chat history (last 6 messages max, excluding current)
        # This prevents the LLM from seeing full previous responses and mixing them
        history_to_use = chat_history[:-1] if chat_history else []
        history_to_use = history_to_use[-6:]  # Limit to last 6 messages (3 exchanges)

        if history_to_use:
            # Build a single context message with summarized history
            history_summary = self._summarize_history(history_to_use)
            if history_summary:
                messages.append(HumanMessage(content=f"[HISTORIAL - solo referencia, NO repetir estas respuestas]\n{history_summary}\n[FIN HISTORIAL]"))
                # Add a simple AI acknowledgment to maintain conversation flow
                messages.append(AIMessage(content="Entendido. Responderé solo al siguiente mensaje."))

        # Add current feedback - this is what we need to respond to
        messages.append(HumanMessage(content=f"[MENSAJE ACTUAL - responder SOLO a esto]\n{feedback}"))

        return messages

    def _summarize_history(self, history: list[dict[str, Any]]) -> str:
        """
        Summarize chat history to key facts only.
        This prevents the LLM from seeing full responses and mixing them.
        """
        if not history:
            return ""

        summaries = []
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "user":
                # Keep user messages short
                short_content = content[:150] + "..." if len(content) > 150 else content
                summaries.append(f"Usuario: {short_content}")
            else:
                # Summarize AI responses to just the key action/fact
                summary = self._extract_ai_summary(content)
                summaries.append(f"Asistente: {summary}")

        return "\n".join(summaries)

    def _extract_ai_summary(self, ai_response: str) -> str:
        """
        Extract a brief summary from an AI response.
        Reduces full explanations to key facts only.
        """
        # If very short, keep as is
        if len(ai_response) <= 100:
            return ai_response

        # Try to extract just the first sentence or key action
        lines = ai_response.split("\n")
        first_line = lines[0].strip()

        # Common patterns to detect and summarize
        if "he agregado" in ai_response.lower():
            return "[Realizó un cambio al documento]"
        elif "he actualizado" in ai_response.lower():
            return "[Actualizó el documento]"
        elif "he eliminado" in ai_response.lower():
            return "[Eliminó contenido del documento]"
        elif "listo" in first_line.lower()[:20]:
            return "[Confirmó cambio realizado]"
        elif "?" in ai_response[-50:]:
            # Ends with a question, likely informational
            return "[Dio explicación informativa]"
        else:
            # Just return a truncated first line
            return first_line[:80] + "..." if len(first_line) > 80 else first_line

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

    def _clean_draft(self, draft: str) -> str:
        """Remove any learning rules that accidentally got included in the draft."""
        if not draft:
            return draft

        # Patterns to remove
        patterns_to_remove = [
            r"\[INSTRUCCIONES DE ESTILO[^\]]*\][\s\S]*?\[FIN INSTRUCCIONES DE ESTILO\]",
            r"##?\s*REGLAS\s+(DEL\s+ESTUDIO|INTERNAS)[\s\S]*?(?=\n##|\n\n[A-ZÁÉÍÓÚ]|\Z)",
            r"##?\s*INSTRUCCIONES\s+ADICIONALES[\s\S]*?(?=\n##|\n\n[A-ZÁÉÍÓÚ]|\Z)",
        ]

        cleaned = draft
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        # Clean up extra whitespace
        cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned)
        return cleaned.strip()

    def _parse_response(self, content: str) -> dict[str, Any]:
        """Parse the response into structured data."""
        # Extract response type
        response_type = self._extract_section(content, "tipo_respuesta")
        if not response_type:
            # Fallback: check if document tag exists to determine type
            has_document = "<documento>" in content
            response_type = "edit" if has_document else "informational"
        else:
            response_type = response_type.strip().lower()

        # Extract explanation (always present)
        explanation = self._extract_section(content, "explicacion")
        if not explanation:
            # Fallback: use content before document tag or entire content
            if "<documento>" in content:
                explanation = content.split("<documento>")[0].strip()
                # Clean up any XML tags
                explanation = re.sub(r"<[^>]+>", "", explanation).strip()
            else:
                # Use the entire content, cleaning XML tags
                explanation = re.sub(r"<[^>]+>[^<]*</[^>]+>", "", content)
                explanation = re.sub(r"<[^>]+>", "", explanation).strip()

        if not explanation:
            explanation = "He procesado tu solicitud."

        # Extract document only if it's an edit response
        new_draft = None
        changes = []
        has_document_changes = False

        if response_type == "edit":
            new_draft = self._extract_section(content, "documento")
            if new_draft:
                # Clean any learning rules that accidentally got included
                new_draft = self._clean_draft(new_draft)
                changes_text = self._extract_section(content, "cambios")
                changes = self._parse_changes(changes_text)
                has_document_changes = True
            else:
                # If marked as edit but no document, treat as informational
                response_type = "informational"
                logger.warning("Response marked as edit but no document found, treating as informational")

        return {
            "response_type": response_type,
            "new_draft": new_draft,  # None for informational responses
            "changes": changes,
            "explanation": explanation,
            "has_document_changes": has_document_changes,
        }
