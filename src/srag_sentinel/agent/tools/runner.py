"""Run the metric tools against the database with the read-only account."""

from srag_sentinel.agent.tools.metrics import ScopeArgs, get_srag_metrics, get_srag_series
from srag_sentinel.data.repository import SurrealCountersReader
from srag_sentinel.db.client import open_connection
from srag_sentinel.domain.models import MetricsPayload
from srag_sentinel.domain.series import SeriesPayload
from srag_sentinel.settings import Settings


async def load_metrics_and_series(
    settings: Settings, args: ScopeArgs
) -> tuple[MetricsPayload, SeriesPayload]:
    """Fetch metrics and chart series for ``args`` (connects as the ``api_ro`` user)."""
    auth = {
        "namespace": settings.surreal_namespace,
        "database": settings.surreal_data_database,
        "username": settings.surreal_api_ro_user,
        "password": settings.surreal_api_ro_password.get_secret_value(),
    }
    async with open_connection(
        settings.surreal_url,
        auth=auth,
        namespace=settings.surreal_namespace,
        database=settings.surreal_data_database,
    ) as connection:
        reader = SurrealCountersReader(connection)
        return await get_srag_metrics(reader, args), await get_srag_series(reader, args)
