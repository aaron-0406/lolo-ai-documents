"""
Learning Override Utility - Detects and removes contradicting instructions.

This module provides functionality to analyze default instructions against
learnings/rules and remove any default instructions that contradict the learnings.
Uses an LLM for semantic analysis of contradictions.
"""

import re
from langchain_core.messages import HumanMessage
from loguru import logger

from app.config import settings
from app.utils.llm_worker import submit_to_worker


class LearningOverrideAnalyzer:
    """
    Analyzes and removes default instructions that contradict learnings.
    Uses Haiku for fast semantic analysis.
    """

    def __init__(self):
        # No LLM instance needed - using worker
        pass

    async def detect_contradictions(
        self,
        default_instructions: list[str],
        learnings: str,
    ) -> list[int]:
        """
        Usa el LLM para detectar qué instrucciones por defecto contradicen las lecciones.

        Args:
            default_instructions: Lista de instrucciones por defecto
            learnings: Las lecciones/reglas del estudio

        Returns:
            Lista de índices de instrucciones que deben eliminarse
        """
        if not default_instructions or not learnings:
            return []

        # Construir el prompt para el análisis
        instructions_text = "\n".join(
            f"{i}: {inst}" for i, inst in enumerate(default_instructions)
        )

        analysis_prompt = f"""Analiza si alguna de las INSTRUCCIONES POR DEFECTO contradice las REGLAS DEL ESTUDIO.

INSTRUCCIONES POR DEFECTO:
{instructions_text}

REGLAS DEL ESTUDIO:
{learnings}

Responde SOLO con los números de las instrucciones que CONTRADICEN las reglas, separados por coma.
Si una instrucción dice algo diferente o opuesto a lo que dice una regla, es una contradicción.
Si no hay contradicciones, responde: NINGUNA

Ejemplos de contradicciones:
- Instrucción dice "incluir X" pero regla dice "no incluir X" → CONTRADICCIÓN
- Instrucción dice "numerar" pero regla dice "sin numeración" → CONTRADICCIÓN
- Instrucción dice "separar secciones" pero regla dice "unificar secciones" → CONTRADICCIÓN

Respuesta (solo números o NINGUNA):"""

        try:
            # Use worker with Haiku for fast analysis
            llm_response = await submit_to_worker(
                messages=[HumanMessage(content=analysis_prompt)],
                model=settings.claude_model_fast,  # Haiku
                max_tokens=500,
                estimated_output_tokens=100,
            )

            result = llm_response.message.content.strip().upper()

            if "NINGUNA" in result or not result:
                return []

            # Extraer los números de la respuesta
            numbers = re.findall(r'\d+', result)
            indices = [int(n) for n in numbers if int(n) < len(default_instructions)]

            if indices:
                logger.info(f"[OVERRIDE] Contradicciones detectadas en instrucciones: {indices}")

            return indices

        except Exception as e:
            logger.error(f"[OVERRIDE] Error detectando contradicciones: {e}")
            return []

    async def remove_conflicting_instructions(
        self,
        prompt: str,
        custom_instructions: str | None,
    ) -> str:
        """
        Elimina las instrucciones por defecto que contradicen las lecciones.
        Usa el LLM para detectar contradicciones semánticamente.

        Args:
            prompt: El prompt completo
            custom_instructions: Las lecciones/instrucciones personalizadas

        Returns:
            Prompt modificado con las instrucciones contradictorias eliminadas
        """
        if not custom_instructions:
            return prompt

        # Encontrar la sección INSTRUCCIONES POR DEFECTO
        section_match = re.search(
            r'(## INSTRUCCIONES POR DEFECTO\n)(.*?)(\n---|\n\n##|\Z)',
            prompt,
            flags=re.DOTALL
        )

        if not section_match:
            return prompt

        section_header = section_match.group(1)
        section_content = section_match.group(2)
        section_end = section_match.group(3)

        # Separar en líneas individuales (instrucciones)
        lines = [line for line in section_content.split('\n') if line.strip()]

        if not lines:
            return prompt

        # Detectar contradicciones usando el LLM
        contradicting_indices = await self.detect_contradictions(lines, custom_instructions)

        if not contradicting_indices:
            logger.info("[OVERRIDE] No se detectaron contradicciones")
            return prompt

        # Filtrar las líneas que contradicen
        filtered_lines = []
        for i, line in enumerate(lines):
            if i in contradicting_indices:
                logger.info(f"[OVERRIDE] Eliminando instrucción contradictoria: '{line.strip()[:60]}...'")
            else:
                filtered_lines.append(line)

        # Reconstruir la sección
        new_section_content = '\n'.join(filtered_lines)
        new_section = section_header + new_section_content + section_end

        # Reemplazar en el prompt
        modified_prompt = prompt[:section_match.start()] + new_section + prompt[section_match.end():]

        # Limpiar líneas vacías múltiples
        modified_prompt = re.sub(r'\n{3,}', '\n\n', modified_prompt)

        return modified_prompt


# Instancia global para reutilizar
learning_override_analyzer = LearningOverrideAnalyzer()
