"""
Base template classes for document generation.
"""

from typing import Any
from pydantic import BaseModel, Field


class TemplateSection(BaseModel):
    """A section within a document template."""

    name: str = Field(..., description="Section name/header")
    required: bool = Field(default=True, description="Whether section is required")
    order: int = Field(..., description="Order in document")
    content_template: str = Field(..., description="Template text with placeholders")
    placeholders: list[str] = Field(default_factory=list, description="Placeholder variables")


class DocumentTemplate(BaseModel):
    """Template for a legal document type."""

    document_type: str = Field(..., description="Document type key")
    document_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Template description")
    sections: list[TemplateSection] = Field(default_factory=list, description="Document sections")
    required_context: list[str] = Field(default_factory=list, description="Required context fields")

    def render(self, context: dict[str, Any]) -> str:
        """
        Render the template with provided context.

        Args:
            context: Dictionary of values to fill placeholders

        Returns:
            Rendered document text
        """
        output = []

        for section in sorted(self.sections, key=lambda s: s.order):
            section_content = section.content_template

            # Replace placeholders
            for placeholder in section.placeholders:
                value = context.get(placeholder, f"[{placeholder.upper()}]")
                section_content = section_content.replace(
                    f"{{{placeholder}}}", str(value)
                )

            output.append(section_content)

        return "\n\n".join(output)

    def get_missing_context(self, context: dict[str, Any]) -> list[str]:
        """
        Get list of missing required context fields.

        Args:
            context: Provided context

        Returns:
            List of missing field names
        """
        missing = []
        for field in self.required_context:
            if field not in context or context[field] is None:
                missing.append(field)
        return missing
