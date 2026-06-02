# services/api/app/observability.py
"""
Cloud-agnostic OpenTelemetry setup.

Configures tracing (and optionally metrics) based on OTEL_EXPORTER setting.
Supported exporters:
  "otlp"            — Standard OTLP gRPC/HTTP exporter (Jaeger, Datadog, etc.)
  "xray"            — AWS X-Ray (via OTLP exporter with X-Ray ID generator)
  "azure_monitor"   — Azure Application Insights (via azure-monitor-opentelemetry-exporter)
  "none"            — Disabled (no-op, useful for local dev / tests)

Usage:
  Called from main.py lifespan.  All deps are optional — gracefully degrades.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def setup_observability(app: FastAPI) -> None:
    """Configure and attach OpenTelemetry to the FastAPI app."""
    from app.config import settings

    exporter = settings.OTEL_EXPORTER.lower().strip()

    if exporter == "none":
        logger.info("Observability disabled (OTEL_EXPORTER=none)")
        return

    # Common OTel setup
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {
            "service.name": settings.OTEL_SERVICE_NAME,
            "cloud.provider": settings.CLOUD_PROVIDER,
            "deployment.environment": settings.ENV,
        }
    )

    if exporter == "xray":
        _setup_xray(resource, settings)
    elif exporter == "azure_monitor":
        _setup_azure_monitor(resource, settings)
    else:
        # Default: standard OTLP exporter
        _setup_otlp(resource, settings)

    # Auto-instrument FastAPI (works with any exporter above)
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info(f"FastAPI auto-instrumented (exporter={exporter})")
    except ImportError:
        logger.warning(
            "opentelemetry-instrumentation-fastapi not installed — "
            "auto-instrumentation skipped"
        )


def _setup_otlp(resource, settings) -> None:
    """Standard OTLP gRPC exporter (Jaeger, Datadog Agent, OTel Collector)."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = settings.get_otel_endpoint() or "http://localhost:4317"
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(f"OTLP tracing configured (endpoint={endpoint})")


def _setup_xray(resource, settings) -> None:
    """AWS X-Ray via OTLP exporter with X-Ray-compatible ID generator."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter,
    )
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    try:
        from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator

        id_generator = AwsXRayIdGenerator()
    except ImportError:
        logger.warning(
            "opentelemetry-sdk-extension-aws not installed — "
            "using default ID generator for X-Ray"
        )
        id_generator = None

    endpoint = settings.get_otel_endpoint() or "http://localhost:4317"
    exporter = OTLPSpanExporter(endpoint=endpoint)

    provider_kwargs = {"resource": resource}
    if id_generator:
        provider_kwargs["id_generator"] = id_generator

    provider = TracerProvider(**provider_kwargs)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info(f"AWS X-Ray tracing configured (endpoint={endpoint})")


def _setup_azure_monitor(resource, settings) -> None:
    """Azure Application Insights via azure-monitor-opentelemetry-exporter."""
    try:
        from azure.monitor.opentelemetry.exporter import (
            AzureMonitorTraceExporter,
        )
    except ImportError:
        raise ImportError(
            "azure-monitor-opentelemetry-exporter is required when "
            "OTEL_EXPORTER='azure_monitor'. "
            "Install: pip install azure-monitor-opentelemetry-exporter"
        )

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    conn_str = settings.AZURE_MONITOR_CONNECTION_STRING
    if not conn_str:
        raise ValueError(
            "AZURE_MONITOR_CONNECTION_STRING is required when "
            "OTEL_EXPORTER='azure_monitor'"
        )

    exporter = AzureMonitorTraceExporter(connection_string=conn_str)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger.info("Azure Monitor (App Insights) tracing configured")
