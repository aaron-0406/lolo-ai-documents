"""
Pytest configuration and fixtures.
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.models.schemas import CaseContext


@pytest.fixture
def sample_case_context() -> CaseContext:
    """Create a sample case context for testing."""
    return CaseContext(
        case_file_id=12345,
        case_number="00123-2024-0-1801-JR-CI-01",
        client_id=100,
        client_name="Juan Pérez García",
        client_dni_ruc="12345678",
        client_address="Av. Javier Prado 1234, San Isidro, Lima",
        court="1° Juzgado Civil de Lima",
        secretary="María López",
        subject="Obligación de Dar Suma de Dinero",
        procedural_way="Proceso Único de Ejecución",
        process_status="EN TRÁMITE",
        current_stage="ETAPA POSTULATORIA",
        amount_demanded_soles=50000.00,
        amount_demanded_dollars=0,
        customer_name="Banco Financiero S.A.",
        customer_ruc="20100130204",
        bank_name="Banco Financiero",
        customer_has_bank_id=1,
        binnacles=[
            {
                "date": datetime.now(),
                "last_performed": "Se admite demanda y se corre traslado",
                "resolution_number": "01-2024",
                "procedural_stage": "ETAPA POSTULATORIA",
            }
        ],
        collaterals=[
            {
                "registry_entry": "P12345678",
                "property_address": "Jr. Los Álamos 456, Miraflores",
                "department": "Lima",
                "province": "Lima",
                "district": "Miraflores",
                "land_area": 200.0,
                "appraisal_value": 150000.00,
                "status": "Vigente",
            }
        ],
        products=[
            {
                "description": "Préstamo Personal",
                "amount": 50000.00,
                "currency": "PEN",
            }
        ],
    )


@pytest.fixture
def mock_redis():
    """Create a mock Redis service."""
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def mock_mysql():
    """Create a mock MySQL service."""
    mock = AsyncMock()
    mock.case_file_exists = AsyncMock(return_value=True)
    mock.get_case_file_context = AsyncMock(return_value=None)
    return mock
