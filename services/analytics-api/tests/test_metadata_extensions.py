"""EA-026 to EA-028 review boundary and catalog conformance tests."""
from app.metadata import DataHubMetadataProvider, create_exploratory_discovery
from packages.platform_contracts.metadata import MetadataAsset, MetadataQualityReport


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {
                "dataset": {
                    "urn": "urn:li:dataset:orders",
                    "name": "orders",
                    "properties": {"description": "Order facts"},
                    "ownership": {"owners": [{"owner": {"urn": "urn:li:corpuser:analytics"}}]},
                    "schemaMetadata": {"fields": [{"fieldPath": "order_id", "nativeDataType": "BIGINT"}]},
                }
            }
        }


class Client:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        return Response()


def test_datahub_adapter_conforms_to_shared_snapshot():
    client = Client()
    asset = DataHubMetadataProvider("https://datahub.example", "token", client).get_snapshot("orders").assets[0]
    assert asset.id == "urn:li:dataset:orders"
    assert asset.owner_ids == ["urn:li:corpuser:analytics"]
    assert asset.columns[0].data_type == "BIGINT"
    assert client.calls[0][0].endswith("/api/graphql")


def test_exploratory_discovery_requires_review_and_cannot_execute():
    asset = MetadataAsset(id="raw", display_name="Raw", physical_name="raw", provider="datahub")
    quality = MetadataQualityReport(asset_id="raw", score=0.5, actionable=False, missing=["certification"])
    discovery = create_exploratory_discovery(asset, quality)
    assert discovery.review_required is True
    assert discovery.execution_allowed is False
