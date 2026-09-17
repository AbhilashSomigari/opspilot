# Invalid Catalog Data Runbook

If catalog returns invalid pricing, checkout may call payment with a non-positive amount. The payment service rejects non-positive charges. Validate catalog response fields, trace the request into payment, and inspect checkout dependency errors. Treat data-contract violations separately from payment-provider availability failures.
