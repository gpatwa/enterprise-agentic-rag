# OpenSearch Backup and Restore Drill

1. Record active alias, generation, document count, and permission-version
   counts.
2. Create a snapshot using the selected provider's encrypted repository.
3. Restore into an isolated generation and run mapping compatibility,
   document-count, and ACL golden checks.
4. Point a temporary alias at the restored generation and run the smoke query.
5. Record elapsed restore time (RTO), snapshot age (RPO), and any missing or
   unauthorized documents.

The drill is evidence-only until a real repository is configured; local
Compose data is a derived fixture and is not a production backup.
