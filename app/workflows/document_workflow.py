"""
LangGraph workflow for document generation pipeline.
"""

from typing import Annotated, TypedDict, Literal
from langgraph.graph import StateGraph, END
from loguru import logger

from app.models.schemas import CaseContext
from app.agents.orchestration.analyzer_agent import AnalyzerAgent
from app.agents.orchestration.generator_agent import GeneratorAgent
from app.agents.orchestration.refiner_agent import RefinerAgent
from app.services.docx_service import DocxService


class DocumentGenerationState(TypedDict):
    """State shared across all workflow nodes."""

    # Input
    case_file_id: int
    case_context: CaseContext | None
    document_type: str | None
    custom_instructions: str | None
    user_feedback: str | None

    # Processing
    current_draft: str | None
    ai_message: str | None
    agents_executed: list[str]
    validation_results: list[dict]

    # Output
    final_document: bytes | None
    filename: str | None
    error: str | None

    # Control
    step: str
    needs_refinement: bool


class DocumentWorkflow:
    """
    LangGraph workflow for document generation.

    Flow:
    1. Analyze case file → suggest document type
    2. Generate initial draft with specialist + quality pipeline
    3. (Optional) Refine based on user feedback
    4. Finalize and generate DOCX
    """

    def __init__(self):
        self.analyzer = AnalyzerAgent()
        self.generator = GeneratorAgent()
        self.refiner = RefinerAgent()
        self.docx_service = DocxService()
        self.workflow = self._build_workflow()

    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(DocumentGenerationState)

        # Add nodes
        workflow.add_node("analyze", self._analyze_node)
        workflow.add_node("generate", self._generate_node)
        workflow.add_node("refine", self._refine_node)
        workflow.add_node("finalize", self._finalize_node)

        # Set entry point
        workflow.set_entry_point("analyze")

        # Add edges
        workflow.add_edge("analyze", "generate")
        workflow.add_conditional_edges(
            "generate",
            self._should_refine,
            {
                "refine": "refine",
                "finalize": "finalize",
            }
        )
        workflow.add_conditional_edges(
            "refine",
            self._should_continue_refining,
            {
                "refine": "refine",
                "finalize": "finalize",
            }
        )
        workflow.add_edge("finalize", END)

        return workflow.compile()

    async def _analyze_node(
        self,
        state: DocumentGenerationState,
    ) -> DocumentGenerationState:
        """Node 1: Analyze case file and determine document type."""
        logger.info(f"Analyzing case file: {state['case_file_id']}")

        if state.get("error"):
            return state

        try:
            # If document_type already specified, skip analysis
            if state.get("document_type"):
                state["agents_executed"].append("AnalyzerAgent (skipped)")
                state["step"] = "generate"
                return state

            # Run analyzer
            result = await self.analyzer.analyze(state["case_context"])

            if result.has_suggestion:
                state["document_type"] = result.suggestion.document_type
                state["ai_message"] = f"Sugiero generar: {result.suggestion.document_name}. {result.suggestion.reason}"
            else:
                state["error"] = result.no_action_reason.message if result.no_action_reason else "No se puede determinar documento"

            state["agents_executed"].append("AnalyzerAgent")
            state["step"] = "generate"

        except Exception as e:
            logger.error(f"Analyze node failed: {e}")
            state["error"] = str(e)

        return state

    async def _generate_node(
        self,
        state: DocumentGenerationState,
    ) -> DocumentGenerationState:
        """Node 2: Generate document with specialist and quality pipeline."""
        logger.info(f"Generating document: {state['document_type']}")

        if state.get("error"):
            return state

        try:
            result = await self.generator.generate(
                document_type=state["document_type"],
                context=state["case_context"],
                custom_instructions=state.get("custom_instructions"),
            )

            state["current_draft"] = result.draft
            state["ai_message"] = result.ai_message
            state["validation_results"] = result.validation_results
            state["agents_executed"].extend(result.agents_used)
            state["step"] = "refine" if state.get("needs_refinement") else "finalize"

        except Exception as e:
            logger.error(f"Generate node failed: {e}")
            state["error"] = str(e)

        return state

    async def _refine_node(
        self,
        state: DocumentGenerationState,
    ) -> DocumentGenerationState:
        """Node 3: Refine document based on user feedback."""
        logger.info("Refining document with user feedback")

        if state.get("error") or not state.get("user_feedback"):
            return state

        try:
            result = await self.refiner.refine(
                current_draft=state["current_draft"],
                feedback=state["user_feedback"],
                context=state["case_context"].model_dump(),
                chat_history=[],
            )

            state["current_draft"] = result["new_draft"]
            state["ai_message"] = result["explanation"]
            state["agents_executed"].append("RefinerAgent")
            state["user_feedback"] = None  # Clear feedback after processing
            state["step"] = "finalize"

        except Exception as e:
            logger.error(f"Refine node failed: {e}")
            state["error"] = str(e)

        return state

    async def _finalize_node(
        self,
        state: DocumentGenerationState,
    ) -> DocumentGenerationState:
        """Node 4: Generate final DOCX document."""
        logger.info("Finalizing document")

        if state.get("error"):
            return state

        try:
            docx_bytes = await self.docx_service.generate(
                draft=state["current_draft"],
                document_type=state["document_type"],
                context=state["case_context"],
            )

            # Generate filename
            case_number = state["case_context"].case_number.replace("/", "-").replace("\\", "-")
            filename = f"{state['document_type']}_{case_number}.docx"

            state["final_document"] = docx_bytes
            state["filename"] = filename
            state["agents_executed"].append("DocxService")
            state["step"] = "complete"

        except Exception as e:
            logger.error(f"Finalize node failed: {e}")
            state["error"] = str(e)

        return state

    def _should_refine(
        self,
        state: DocumentGenerationState,
    ) -> Literal["refine", "finalize"]:
        """Determine if refinement is needed."""
        if state.get("needs_refinement") and state.get("user_feedback"):
            return "refine"
        return "finalize"

    def _should_continue_refining(
        self,
        state: DocumentGenerationState,
    ) -> Literal["refine", "finalize"]:
        """Determine if more refinement is needed."""
        if state.get("user_feedback"):
            return "refine"
        return "finalize"

    async def run(
        self,
        case_context: CaseContext,
        document_type: str | None = None,
        custom_instructions: str | None = None,
    ) -> DocumentGenerationState:
        """
        Run the complete workflow.

        Args:
            case_context: Case file context
            document_type: Optional document type (skips analysis)
            custom_instructions: Optional custom instructions

        Returns:
            Final workflow state
        """
        initial_state: DocumentGenerationState = {
            "case_file_id": case_context.case_file_id,
            "case_context": case_context,
            "document_type": document_type,
            "custom_instructions": custom_instructions,
            "user_feedback": None,
            "current_draft": None,
            "ai_message": None,
            "agents_executed": [],
            "validation_results": [],
            "final_document": None,
            "filename": None,
            "error": None,
            "step": "analyze",
            "needs_refinement": False,
        }

        return await self.workflow.ainvoke(initial_state)

    async def run_generation_only(
        self,
        case_context: CaseContext,
        document_type: str,
        custom_instructions: str | None = None,
    ) -> dict:
        """
        Run only the generation step (used by /generate endpoint).

        Returns dict with draft and metadata.
        """
        result = await self.generator.generate(
            document_type=document_type,
            context=case_context,
            custom_instructions=custom_instructions,
        )

        return {
            "draft": result.draft,
            "ai_message": result.ai_message,
            "tokens_used": result.tokens_used,
            "agents_used": result.agents_used,
            "validation_results": result.validation_results,
        }
