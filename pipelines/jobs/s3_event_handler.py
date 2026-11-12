# pipelines/jobs/s3_event_handler.py
import os

from ray.job_submission import JobSubmissionClient

# Config
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "http://rag-ray-cluster-head-svc:8265")
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
DEFAULT_TENANT_ID = "default"


def extract_tenant_id(s3_key: str) -> str:
    """
    Extract tenant_id from the S3 key path.

    Expected key format: uploads/{tenant_id}/{user_id}/{file_id}.{ext}
    Falls back to DEFAULT_TENANT_ID if the path doesn't match the expected format.
    """
    parts = s3_key.split("/")
    # uploads/acme-corp/user123/abc.pdf → parts = ["uploads", "acme-corp", "user123", "abc.pdf"]
    if len(parts) >= 3 and parts[0] == "uploads":
        return parts[1]
    return DEFAULT_TENANT_ID


def handle_s3_event(event, context):
    """
    AWS Lambda entry point (or called via SQS poller).
    Triggered when a file is uploaded to S3.
    Extracts tenant_id from the S3 key path and passes it to the Ray job.
    """
    # 1. Parse Event
    # Assuming standard S3 Event structure
    for record in event['Records']:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        tenant_id = extract_tenant_id(key)

        print(f"File uploaded: s3://{bucket}/{key} (tenant={tenant_id})")

        # 2. Submit Ray Job with tenant context
        submit_ingestion_job(bucket, key, tenant_id)


def submit_ingestion_job(bucket: str, file_key: str, tenant_id: str = DEFAULT_TENANT_ID):
    """
    Submits a job to the Ray Cluster via REST API.
    Passes tenant_id as an environment variable so the ingestion pipeline
    can tag all vectors and graph nodes with the correct tenant.
    """
    client = JobSubmissionClient(RAY_ADDRESS)

    # The command runs inside the Ray Head node
    # It executes the 'main.py' pipeline we wrote in Module 4
    job_id = client.submit_job(
        entrypoint=f"python pipelines/ingestion/main.py {bucket} {file_key}",

        # Working dir contains our pipeline code
        runtime_env={
            "working_dir": "./",
            "pip": [
                "boto3",
                "qdrant-client",
                "neo4j",
                "langchain-text-splitters>=0.3,<1",
                "unstructured",
                # OpenSearch sink (INGEST_VECTOR_SINKS=opensearch); same pins as services/api/requirements.txt
                "opensearch-py[async]>=2.4,<3.0",
                "pydantic==2.6.0",
                "pydantic-settings==2.1.0",
                "google-genai>=0.5.0",
            ],
            "env_vars": {
                "TENANT_ID": tenant_id,
                # 768 dims everywhere (see ray_job.yaml); GOOGLE_API_KEY is a secret and is not set here.
                "INGEST_EMBED_PROVIDER": "gemini",
                "GEMINI_EMBED_DIMENSIONS": "768",
            },
        }
    )

    print(f"Submitted Ray Job ID: {job_id} (tenant={tenant_id})")
    return job_id


if __name__ == "__main__":
    # Local test simulation
    fake_event = {
        "Records": [{
            "s3": {
                "bucket": {"name": "rag-docs"},
                "object": {"key": "uploads/acme-corp/user123/engine_v8.pdf"}
            }
        }]
    }
    handle_s3_event(fake_event, None)
