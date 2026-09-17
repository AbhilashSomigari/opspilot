# Dependency Latency Runbook

A checkout request has a two-second dependency timeout in the demo environment. A payment or catalog p95 near or above that budget can produce checkout 504 responses.

Correlate service p95 latency with checkout 504s and trace child-span duration. Prefer reverting a recent latency-causing change or correcting the dependency configuration. Do not increase timeout as a first response unless the downstream SLO justifies it.
