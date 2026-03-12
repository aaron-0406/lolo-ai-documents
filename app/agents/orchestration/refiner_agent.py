"""
RefinerAgent - Refines documents via chat with SSE streaming support.
Integrates with the learning system to extract and apply learnings.
"""

import re
from typing import Any, AsyncGenerator, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.config import settings
from app.prompts.refiner import REFINER_SYSTEM_PROMPT
from app.services.learning_service import (
    learning_extractor,
    learning_backend,
    learning_applier,
    effectiveness_detector,
    ExtractedLearning,
    StoredLearning,
)


class RefinerAgent:
    """
    Refines documents based on user feedback.
    Maintains conversation context for incremental changes.
    Supports SSE streaming for real-time token delivery.
    Extracts learnings from user feedback for future use.
    """

    def __init__(self):
        self.llm = ChatAnthropic(
            model=settings.claude_model,
            max_tokens=8000,
            api_key=settings.anthropic_api_key,
            streaming=True,
        )

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

        response = await self.llm.ainvoke(messages)
        return self._parse_response(response.content)

    async def refine_stream(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Refine the document with SSE streaming.

        Yields chunks with types:
        - token: Individual tokens of the response
        - draft: Updated document draft (when complete)
        - changes: List of changes made

        Args:
            current_draft: Current document draft
            feedback: User's feedback/request
            context: Case file context
            chat_history: Previous chat messages

        Yields:
            Dict with type and content
        """
        messages = self._build_messages(
            current_draft, feedback, context, chat_history
        )

        full_response = ""
        in_document = False
        in_changes = False
        document_content = ""
        changes_content = ""

        try:
            async for chunk in self.llm.astream(messages):
                # Extract text from chunk
                if hasattr(chunk, "content"):
                    token = chunk.content
                else:
                    continue

                if not token:
                    continue

                full_response += token

                # Track document and changes sections
                if "<documento>" in full_response and not in_document:
                    in_document = True
                if "</documento>" in full_response and in_document:
                    in_document = False
                    # Extract complete document
                    document_content = self._extract_section(
                        full_response, "documento"
                    )
                    yield {"type": "draft", "content": document_content}

                if "<cambios>" in full_response and not in_changes:
                    in_changes = True
                if "</cambios>" in full_response and in_changes:
                    in_changes = False
                    # Extract changes
                    changes_content = self._extract_section(
                        full_response, "cambios"
                    )
                    changes_list = self._parse_changes(changes_content)
                    yield {"type": "changes", "content": changes_list}

                # Stream token (only explanation part, not document)
                if not in_document:
                    yield {"type": "token", "content": token}

        except Exception as e:
            logger.error(f"Error in refine_stream: {e}")
            yield {"type": "error", "content": str(e)}

    async def refine_with_learning(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
        document_type: str,
        session_id: Optional[str] = None,
        customer_id: Optional[int] = None,
        case_file_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Refine the document and extract learnings from the feedback.

        This method extends the standard refine() by also extracting
        generalizable learnings from the user's feedback and storing
        them in the backend for future use.

        Args:
            current_draft: Current document draft
            feedback: User's feedback/request
            context: Case file context
            chat_history: Previous chat messages
            document_type: Type of document being refined
            session_id: Optional session ID
            customer_id: Optional customer ID for learning storage
            case_file_id: Optional case file ID
            user_id: Optional user ID who made the correction

        Returns:
            Dictionary with new_draft, changes, explanation, and learnings_extracted
        """
        # First, do the standard refinement
        result = await self.refine(current_draft, feedback, context, chat_history)

        # Then, extract learnings in the background
        learnings_created = []
        if settings.learning_enabled and customer_id:
            try:
                # Extract learnings from the feedback
                learnings = await learning_extractor.extract_learnings(
                    document_type=document_type,
                    user_feedback=feedback,
                    original_text=current_draft,
                    corrected_text=result["new_draft"],
                    document_section=None,  # Could be detected from changes
                )

                # Send learnings to backend
                for learning in learnings:
                    learning_id = await learning_backend.create_learning(
                        customer_id=customer_id,
                        document_type=document_type,
                        learning=learning,
                        source_session_id=session_id,
                        source_case_file_id=case_file_id,
                        created_by_user_id=user_id,
                    )
                    if learning_id:
                        learnings_created.append({
                            "learning_id": learning_id,
                            "instruction_summary": learning.instruction_summary or learning.instruction[:100],
                            "learning_type": learning.learning_type,
                        })

                if learnings_created:
                    logger.info(f"Created {len(learnings_created)} learnings from refinement")

            except Exception as e:
                logger.error(f"Error extracting/storing learnings: {e}")
                # Don't fail the refinement if learning extraction fails

        result["learnings_extracted"] = len(learnings_created)
        result["learnings"] = learnings_created
        return result

    async def refine_stream_with_learning(
        self,
        current_draft: str,
        feedback: str,
        context: dict[str, Any],
        chat_history: list[dict[str, Any]],
        document_type: str,
        session_id: Optional[str] = None,
        customer_id: Optional[int] = None,
        case_file_id: Optional[int] = None,
        user_id: Optional[int] = None,
        applied_learning_ids: Optional[list[str]] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Refine with streaming and extract learnings.

        Yields all the same chunks as refine_stream, plus:
        - learnings: Information about extracted learnings (at the end)
        - effectiveness: Results of effectiveness detection for previously applied learnings

        Args:
            applied_learning_ids: Optional list of learning IDs that were applied
                                  during the original generation (for effectiveness tracking)
        """
        # Track the full draft for learning extraction
        full_draft = ""

        async for chunk in self.refine_stream(current_draft, feedback, context, chat_history):
            if chunk["type"] == "draft":
                full_draft = chunk["content"]
            yield chunk

        # After streaming completes, extract learnings and check effectiveness
        if settings.learning_enabled and customer_id and full_draft:
            try:
                # 1. Detect effectiveness of previously applied learnings
                if applied_learning_ids:
                    try:
                        # Get the applied learnings details
                        applied_learnings = await learning_applier.get_learnings_for_generation(
                            customer_id=customer_id,
                            document_type=document_type,
                        )
                        # Filter to only those that were actually applied
                        applied_learnings = [
                            l for l in applied_learnings
                            if l.learning_id in applied_learning_ids
                        ]

                        if applied_learnings:
                            effectiveness_results = await effectiveness_detector.detect_effectiveness(
                                applied_learnings=applied_learnings,
                                original_text=current_draft,
                                user_feedback=feedback,
                                corrected_text=full_draft,
                            )

                            # Update effectiveness in backend
                            for result in effectiveness_results:
                                learning_id = result.get("learning_id")
                                was_effective = result.get("was_effective", True)
                                # Note: We need the application_id to mark effectiveness
                                # This would require tracking which application record to update
                                logger.info(
                                    f"Learning {learning_id} effectiveness: {was_effective} - {result.get('reason', '')}"
                                )

                            yield {
                                "type": "effectiveness",
                                "content": {
                                    "checked": len(effectiveness_results),
                                    "results": effectiveness_results,
                                }
                            }

                    except Exception as e:
                        logger.error(f"Error detecting effectiveness: {e}")

                # 2. Extract new learnings from this refinement
                logger.info(f"Extracting learnings - customer_id={customer_id}, document_type={document_type}")
                logger.debug(f"Feedback: {feedback[:200]}...")

                learnings = await learning_extractor.extract_learnings(
                    document_type=document_type,
                    user_feedback=feedback,
                    original_text=current_draft,
                    corrected_text=full_draft,
                    document_section=None,
                )

                logger.info(f"Learnings extracted: {len(learnings)}")

                learnings_created = []
                for learning in learnings:
                    learning_id = await learning_backend.create_learning(
                        customer_id=customer_id,
                        document_type=document_type,
                        learning=learning,
                        source_session_id=session_id,
                        source_case_file_id=case_file_id,
                        created_by_user_id=user_id,
                    )
                    if learning_id:
                        learnings_created.append({
                            "learning_id": learning_id,
                            "instruction_summary": learning.instruction_summary or learning.instruction[:100],
                            "learning_type": learning.learning_type,
                        })

                if learnings_created:
                    yield {
                        "type": "learnings",
                        "content": {
                            "count": len(learnings_created),
                            "learnings": learnings_created,
                        }
                    }

            except Exception as e:
                logger.error(f"Error extracting learnings in stream: {e}")

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
