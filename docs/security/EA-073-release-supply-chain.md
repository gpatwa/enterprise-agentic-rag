# EA-073 Release Supply-Chain Checklist

Every pilot release must produce and retain:

- a pinned dependency lock/report and source revision;
- an SBOM for application and container artifacts;
- dependency, image, secret, and license scan results;
- a signed artifact digest and verifiable provenance statement;
- vulnerability owner, severity, remediation deadline, and exception expiry;
- a record that production promotion requires the evaluation release gate.

Critical vulnerabilities block release. High vulnerabilities require security
approval and a time-bounded exception before pilot launch. Signing keys belong
to the release system, never to the repository or application environment.
The actual scanner, registry, signing service, and SLA are deployment-specific
external gates.
