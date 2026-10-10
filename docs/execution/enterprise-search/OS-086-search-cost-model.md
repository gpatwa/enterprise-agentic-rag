# OS-086 Search Capacity and Cost Model

Monthly capacity is modeled from document count, average chunks per document,
vector dimensions, bytes per vector, shard count, replica count, ingest rate,
query rate, cache hit rate, snapshot storage, and egress. The governing
equations are:

`primary_storage = documents * chunks * (source_bytes + vector_dimensions * 4)`

`provisioned_storage = primary_storage * (1 + replicas) * 1.3 headroom`

`monthly_ingest = indexed_documents * average_document_bytes`

`monthly_query_units = query_requests * (1 + retry_rate) * candidate_multiplier`

The selected managed or operated service supplies the price card; this model
keeps infrastructure choice separate from application contracts and prevents
unmeasured cloud spend from being represented as a deployment result.
