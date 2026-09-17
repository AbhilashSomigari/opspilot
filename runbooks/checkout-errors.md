# Checkout Elevated Error Rate Runbook

When checkout 5xx rises, first separate an edge failure in checkout from an upstream dependency failure.

1. Compare checkout, payment, and catalog 5xx rates over the same five-minute window.
2. Inspect distributed traces for child spans with long duration or non-success status.
3. Search checkout logs for `dependency failure` or `dependency timeout`.
4. Check deployments in the 30 minutes before the first error-rate increase.
5. If an upstream service is failing, mitigate that dependency rather than rolling back checkout blindly.
6. Rollback/config/code actions require human approval and a recorded audit event.
