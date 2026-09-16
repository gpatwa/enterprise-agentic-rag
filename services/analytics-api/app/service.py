from uuid import uuid4

from app.analytics.engine import AnalyticsEngine
from app.analytics.formatter import suggest_chart_spec
from app.analytics.schema_context import COMMON_METRICS, get_all_table_names
from app.config import Settings
from app.context import ContextBootstrap
from app.llm import OpenAICompatibleClient
from packages.platform_contracts.analytics import (
    AnalyticsQueryRequest,
    AnalyticsQueryResponse,
    AnalyticsSchemaResponse,
)


class AnalyticsService:
    def __init__(self, config: Settings):
        self.config = config
        self.llm = OpenAICompatibleClient(config)
        self.engine = AnalyticsEngine(config, self.llm)
        self.context_bootstrap = ContextBootstrap(config)

    @property
    def database_configured(self) -> bool:
        return self.config.ANALYTICS_DEMO_MODE or bool(self.config.database_url)

    @property
    def llm_configured(self) -> bool:
        return self.config.ANALYTICS_DEMO_MODE or self.llm.configured

    @property
    def context_index_ready(self) -> bool:
        return not self.context_bootstrap.state.configured or self.context_bootstrap.state.ready

    async def start(self) -> None:
        await self.llm.start()
        self.engine.start()
        self.context_bootstrap.start()

    async def close(self) -> None:
        self.engine.close()
        await self.llm.close()
        self.context_bootstrap.close()

    async def query(self, request: AnalyticsQueryRequest) -> AnalyticsQueryResponse:
        result = (
            _demo_result(request.query)
            if self.config.ANALYTICS_DEMO_MODE
            else await self.engine.run(request.query)
        )
        status = "failed" if result["error"] else "succeeded"
        return AnalyticsQueryResponse(
            query_id=uuid4().hex,
            query=request.query,
            dataset=request.dataset,
            status=status,
            sql=result["sql"],
            columns=result["columns"],
            rows=result["rows"],
            row_count=result["row_count"],
            execution_time_ms=result["time_ms"],
            truncated=result["truncated"],
            chart_spec=suggest_chart_spec(
                result["columns"], result["rows"], request.query
            ),
            error=result["error"],
        )

    def schema(self, dataset: str) -> AnalyticsSchemaResponse:
        return AnalyticsSchemaResponse(
            dataset=dataset,
            tables=get_all_table_names(),
            metrics=sorted(COMMON_METRICS),
        )


def _demo_result(query: str) -> dict:
    """Deterministic local result used only when ANALYTICS_DEMO_MODE=true."""
    query_lower = query.lower()
    if "category" in query_lower:
        columns = ["product_category", "item_gmv"]
        rows = [
            {"product_category": "health_beauty", "item_gmv": 1_258_681.34},
            {"product_category": "watches_gifts", "item_gmv": 1_205_005.68},
            {"product_category": "bed_bath_table", "item_gmv": 1_036_988.68},
            {"product_category": "sports_leisure", "item_gmv": 988_048.97},
            {"product_category": "computers_accessories", "item_gmv": 911_954.32},
        ]
        sql = (
            "SELECT p.product_category_name AS product_category, SUM(oi.price) AS item_gmv "
            "FROM olist_orders o JOIN olist_order_items oi ON oi.order_id = o.order_id "
            "JOIN olist_products p ON p.product_id = oi.product_id "
            "WHERE o.order_status = 'delivered' "
            "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
        )
    else:
        columns = ["month", "revenue"]
        rows = [
            {"month": "2017-09-01", "revenue": 727_762.45},
            {"month": "2017-10-01", "revenue": 779_677.88},
            {"month": "2017-11-01", "revenue": 1_194_882.80},
            {"month": "2017-12-01", "revenue": 878_401.48},
            {"month": "2018-01-01", "revenue": 1_115_004.18},
            {"month": "2018-02-01", "revenue": 992_463.34},
        ]
        sql = (
            "SELECT DATE_TRUNC('month', o.order_purchase_timestamp) AS month, "
            "SUM(op.payment_value) AS revenue FROM olist_orders o "
            "JOIN olist_order_payments op ON op.order_id = o.order_id "
            "WHERE o.order_status = 'delivered' GROUP BY 1 ORDER BY 1 LIMIT 100"
        )
    return {
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "time_ms": 18,
        "error": "",
        "truncated": False,
    }
