"""
Context formatting utilities for AI agents.
"""

from datetime import datetime
from typing import Any


def format_extracted_documents(
    documents: list[dict[str, Any]],
    max_docs: int = 5,
    max_chars_per_doc: int = 3000,
    include_images: bool = True,
) -> str:
    """
    Format extracted document content for inclusion in LLM prompts.

    Args:
        documents: List of extracted document dicts from DocumentContextService
        max_docs: Maximum number of documents to include
        max_chars_per_doc: Maximum characters per document
        include_images: Whether to include image descriptions

    Returns:
        Formatted string with document content
    """
    if not documents:
        return ""

    lines = [
        "## DOCUMENTOS EXTRAÍDOS DEL EXPEDIENTE",
        f"(Se extrajeron y analizaron {len(documents)} documentos de las bitácoras)\n",
        "IMPORTANTE: Usa esta información para contextualizar mejor el documento a generar.\n",
    ]

    for i, doc in enumerate(documents[:max_docs], 1):
        filename = doc.get("filename", "Sin nombre")
        file_type = doc.get("file_type", "unknown").upper()
        binnacle_date = doc.get("binnacle_date", "N/A")
        binnacle_type = doc.get("binnacle_type", "N/A")
        text = doc.get("extracted_text", "")
        images = doc.get("extracted_images", [])
        from_cache = doc.get("from_cache", False)

        # Truncate text
        if len(text) > max_chars_per_doc:
            text = text[:max_chars_per_doc] + "\n[... contenido truncado ...]"

        lines.append(f"### Documento {i}: {filename} ({file_type})")
        lines.append(f"- Fecha: {binnacle_date}")
        lines.append(f"- Tipo de bitácora: {binnacle_type}")
        if from_cache:
            lines.append("- (Contenido desde caché)")

        # Add text content
        if text:
            lines.append("- Contenido extraído:")
            lines.append("```")
            lines.append(text)
            lines.append("```")

        # Add image descriptions
        if include_images and images:
            lines.append(f"\n- Imágenes analizadas ({len(images)}):")
            for img in images[:3]:  # Limit to 3 images per doc
                page = img.get("pageNumber", "?")
                desc = img.get("description", "Sin descripción")
                lines.append(f"  * [Página {page}]: {desc}")

        lines.append("")  # Empty line between docs

    return "\n".join(lines)


def format_binnacles_summary(
    binnacles: list[dict[str, Any]],
    max_entries: int = 10,
) -> str:
    """
    Format binnacles for LLM context.

    Args:
        binnacles: List of binnacle dicts
        max_entries: Maximum number of entries to include

    Returns:
        Formatted string with binnacle summary
    """
    if not binnacles:
        return "No hay bitácoras registradas."

    lines = []
    for b in binnacles[:max_entries]:
        date = b.get("date", "Sin fecha")
        if isinstance(date, datetime):
            date = date.strftime("%d/%m/%Y")
        elif hasattr(date, "strftime"):
            date = date.strftime("%d/%m/%Y")

        type_name = b.get("type_name", "N/A")
        stage = b.get("stage_name", "N/A")
        content = b.get("content", b.get("last_performed", "Sin descripción"))

        if content and len(content) > 150:
            content = content[:150] + "..."

        lines.append(f"- [{date}] ({type_name}) {content}")

    return "\n".join(lines)


def format_collaterals(
    collaterals: list[dict[str, Any]],
    max_entries: int = 5,
) -> str:
    """
    Format collaterals for LLM context.

    Args:
        collaterals: List of collateral dicts
        max_entries: Maximum number to include

    Returns:
        Formatted string with collateral info
    """
    if not collaterals:
        return "No hay garantías registradas."

    lines = []
    for c in collaterals[:max_entries]:
        kind = c.get("kind_of_property", "Inmueble")
        address = c.get("property_address", "Sin dirección")
        status = c.get("status_name", c.get("status", "N/A"))
        registry = c.get("registry_entry", "N/A")
        area = c.get("land_area", "N/A")

        lines.append(f"- {kind}: {address}")
        lines.append(f"  Partida: {registry} | Área: {area} | Estado: {status}")

    return "\n".join(lines)


def format_context_summary(
    context_stats: dict[str, Any],
) -> str:
    """
    Format case context statistics.

    Args:
        context_stats: Stats from ContextCacheService

    Returns:
        Formatted summary string
    """
    if not context_stats:
        return ""

    docs = context_stats.get("total_documents_analyzed", 0)
    pages = context_stats.get("total_pages_analyzed", 0)
    images = context_stats.get("total_images_analyzed", 0)
    version = context_stats.get("context_version", 1)

    return (
        f"Contexto del expediente: {docs} documentos, "
        f"{pages} páginas, {images} imágenes analizadas "
        f"(versión {version})"
    )


# =============================================================================
# Extrajudicial Context Formatting
# =============================================================================


def format_extrajudicial_context(
    extrajudicial: Any,
    include_collection_history: bool = True,
    include_files: bool = True,
    max_collection_actions: int = 15,
) -> str:
    """
    Format complete extrajudicial context for AI prompts.

    Args:
        extrajudicial: ExtrajudicialContext object
        include_collection_history: Include collection action history
        include_files: Include extracted file content
        max_collection_actions: Max collection actions to include

    Returns:
        Formatted string with extrajudicial context
    """
    if not extrajudicial:
        return ""

    lines = [
        "## CONTEXTO EXTRAJUDICIAL (COBRANZA PREJUDICIAL)",
        "",
    ]

    # Client info
    lines.append("### DATOS DEL CLIENTE/DEUDOR")
    lines.append(f"- Código: {extrajudicial.client_code}")
    lines.append(f"- Nombre: {extrajudicial.client_name}")
    if extrajudicial.client_dni_ruc:
        lines.append(f"- DNI/RUC: {extrajudicial.client_dni_ruc}")
    if extrajudicial.client_phone:
        lines.append(f"- Teléfono: {extrajudicial.client_phone}")
    if extrajudicial.client_email:
        lines.append(f"- Email: {extrajudicial.client_email}")
    if extrajudicial.negotiation_type:
        lines.append(f"- Tipo de negociación: {extrajudicial.negotiation_type}")
    if extrajudicial.management_status:
        lines.append(f"- Estado de gestión: {extrajudicial.management_status}")
    if extrajudicial.assigned_officer:
        lines.append(f"- Funcionario asignado: {extrajudicial.assigned_officer}")
    lines.append("")

    # Addresses
    if extrajudicial.addresses:
        lines.append("### DIRECCIONES")
        for addr in extrajudicial.addresses[:5]:
            addr_type = f"({addr.address_type})" if addr.address_type else ""
            location = ", ".join(
                filter(None, [addr.district, addr.province, addr.department])
            )
            lines.append(f"- {addr.address} {addr_type}")
            if location:
                lines.append(f"  {location}")
        lines.append("")

    # Contacts
    if extrajudicial.contacts:
        lines.append("### CONTACTOS")
        for contact in extrajudicial.contacts[:5]:
            contact_type = f"({contact.contact_type})" if contact.contact_type else ""
            contact_info = []
            if contact.phone:
                contact_info.append(f"Tel: {contact.phone}")
            if contact.email:
                contact_info.append(f"Email: {contact.email}")
            lines.append(f"- {contact.name} {contact_type}")
            if contact_info:
                lines.append(f"  {', '.join(contact_info)}")
        lines.append("")

    # Guarantors
    if extrajudicial.guarantors:
        lines.append("### GARANTES/CODEUDORES")
        for guarantor in extrajudicial.guarantors:
            guarantor_info = []
            if guarantor.phone:
                guarantor_info.append(f"Tel: {guarantor.phone}")
            if guarantor.email:
                guarantor_info.append(f"Email: {guarantor.email}")
            lines.append(f"- {guarantor.name}")
            if guarantor_info:
                lines.append(f"  {', '.join(guarantor_info)}")
        lines.append("")

    # Products
    if extrajudicial.products:
        lines.append("### PRODUCTOS FINANCIEROS")
        for product in extrajudicial.products:
            product_name = product.product_name or "Producto"
            state = f"({product.state})" if product.state else ""
            judicial = "[JUDICIAL]" if product.judicial_case_file_id else ""
            lines.append(f"- {product_name} {state} {judicial}")
        lines.append("")

    # Agreement and payments
    if extrajudicial.has_agreement and extrajudicial.agreement:
        lines.append(format_agreement_summary(extrajudicial.agreement))
        lines.append("")

    # Collection history
    if include_collection_history and extrajudicial.collection_actions:
        lines.append(
            format_collection_history(
                extrajudicial.collection_actions,
                max_entries=max_collection_actions,
            )
        )
        lines.append("")

    # Extracted files
    if include_files:
        if extrajudicial.client_files:
            lines.append("### ARCHIVOS DEL CLIENTE EXTRAÍDOS")
            for f in extrajudicial.client_files[:5]:
                lines.append(f"**{f.get('filename', 'Archivo')}** ({f.get('tag', 'Sin categoría')})")
                text = f.get("extracted_text", "")
                if text:
                    if len(text) > 1500:
                        text = text[:1500] + "..."
                    lines.append(f"```\n{text}\n```")
            lines.append("")

        if extrajudicial.payment_vouchers:
            lines.append("### COMPROBANTES DE PAGO EXTRAÍDOS")
            for v in extrajudicial.payment_vouchers[:5]:
                lines.append(
                    f"**{v.get('filename', 'Voucher')}** - "
                    f"Fecha: {v.get('payment_date')} - "
                    f"Monto: S/ {v.get('payment_amount', 0):.2f}"
                )
                text = v.get("extracted_text", "")
                if text:
                    if len(text) > 1000:
                        text = text[:1000] + "..."
                    lines.append(f"```\n{text}\n```")
            lines.append("")

    return "\n".join(lines)


def format_agreement_summary(agreement: Any) -> str:
    """
    Format settlement agreement summary.

    Args:
        agreement: Agreement object

    Returns:
        Formatted string with agreement details
    """
    if not agreement:
        return ""

    lines = [
        "### CONVENIO DE PAGO",
        f"- Fecha de aprobación: {agreement.approval_date}",
        f"- Monto total negociado: S/ {agreement.total_negotiated_amount:,.2f}",
        f"- Total pagado: S/ {agreement.total_paid:,.2f}",
        f"- Saldo pendiente: S/ {agreement.pending_amount:,.2f}",
    ]

    if agreement.judicial_fees:
        lines.append(f"- Gastos judiciales: S/ {agreement.judicial_fees:,.2f}")

    # Payment percentage
    if agreement.total_negotiated_amount > 0:
        pct = (agreement.total_paid / agreement.total_negotiated_amount) * 100
        lines.append(f"- Porcentaje de cumplimiento: {pct:.1f}%")

    # Products in agreement
    if agreement.products:
        lines.append("")
        lines.append("**Productos en convenio:**")
        for prod in agreement.products:
            currency = prod.currency or "PEN"
            symbol = "S/" if currency == "PEN" else "$"
            lines.append(
                f"- {prod.account_number or 'Producto'}: "
                f"Deuda original {symbol} {prod.total_debt:,.2f} → "
                f"Negociado {symbol} {prod.negotiated_amount:,.2f}"
            )

    # Payment history
    if agreement.payments:
        lines.append("")
        lines.append("**Historial de pagos:**")
        for pay in agreement.payments[:10]:
            lines.append(f"- [{pay.payment_date}] S/ {pay.amount:,.2f}")
            if pay.comment:
                lines.append(f"  Ref: {pay.comment}")

    return "\n".join(lines)


def format_collection_history(
    actions: list,
    max_entries: int = 15,
) -> str:
    """
    Format collection action history.

    Args:
        actions: List of CollectionAction objects
        max_entries: Maximum entries to include

    Returns:
        Formatted string with collection history
    """
    if not actions:
        return ""

    lines = [
        "### HISTORIAL DE GESTIONES DE COBRANZA",
        f"(Últimas {min(len(actions), max_entries)} de {len(actions)} gestiones)",
        "",
    ]

    for action in actions[:max_entries]:
        date_str = action.date
        hour_str = f" {action.hour}" if action.hour else ""
        action_type = f"[{action.action_type}]" if action.action_type else ""

        lines.append(f"**{date_str}{hour_str}** {action_type}")

        if action.officer_name:
            lines.append(f"Gestor: {action.officer_name}")

        if action.contact_name:
            lines.append(f"Contacto: {action.contact_name}")

        if action.address:
            lines.append(f"Dirección: {action.address}")

        # Truncate long comments
        comment = action.comment or ""
        if len(comment) > 300:
            comment = comment[:300] + "..."
        if comment:
            lines.append(f"Nota: {comment}")

        lines.append("")

    return "\n".join(lines)
