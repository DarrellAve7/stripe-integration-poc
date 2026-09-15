# Payment gateway abstraction recommendation

## Executive summary

This POC demonstrates Stripe directly because Stripe is the fastest way to make payment behavior tangible. For a production platform, however, Ave7Lift should ideally place Stripe and any future payment provider behind an internal payment gateway layer.

In this context, "payment gateway" means an Ave7Lift-owned payment API and adapter layer. The application should call generic payment capabilities such as "start checkout," "record payment result," "create billing portal session," or "refund payment." Stripe, or any other payment service, should be treated as an implementation detail behind that API wherever practical.

The goal is not to hide every provider-specific feature. The goal is to keep business workflows from becoming tightly coupled to one vendor's object model, event names, SDKs, and operational assumptions.

## Why this matters

Payment providers are durable but not permanent architectural choices. A company may eventually need multiple providers because of geography, pricing, feature fit, customer preference, outages, account restrictions, fraud posture, or acquisition/integration requirements.

If business code calls Stripe directly everywhere, changing or adding a provider becomes expensive. Product flows, fulfillment logic, reporting, support tools, webhook handling, and customer billing screens can all become tied to Stripe-specific concepts. That is acceptable for a POC, but it creates long-term switching cost.

An internal payment gateway gives the application one payment-facing contract while allowing provider choices to move behind configuration, metadata, routing rules, and adapter code.

## Recommended architecture

At a high level, the application should depend on an internal payment API:

```text
Product / workflow code
        |
        v
Ave7Lift payment gateway API
        |
        +-- Stripe adapter
        +-- Future provider adapter
        +-- Manual/offline adapter, if needed
```

The payment gateway owns the payment vocabulary that the rest of the application uses. Provider adapters translate that vocabulary into provider-specific API calls and webhook events.

For example, the application should not need to know whether a checkout was created with Stripe Checkout Sessions, another provider's hosted page, or a future provider's embedded payment form. It should ask the gateway to start a checkout for a specific business intent and then react to normalized payment outcomes.

## Generic capabilities

The first version of the gateway can stay small. It should expose a limited set of payment capabilities rather than trying to model every possible provider feature.

Suggested initial capabilities:

| Capability | Purpose |
| --- | --- |
| Start checkout | Create a payment or subscription checkout for a known business intent |
| Get checkout status | Return the current normalized state of a checkout attempt |
| Receive provider event | Verify, deduplicate, and translate a provider webhook |
| Record payment outcome | Update the application payment record from a normalized event |
| Create billing portal session | Send an authenticated customer to provider-managed billing, when supported |
| Refund payment | Initiate or record a refund through the selected provider |

The gateway should expose stable internal records such as `payment_attempt`, `payment_customer`, `payment_method_reference`, `payment_event`, and `payment_refund`. Provider-specific IDs can be stored on those records as references, not used as the application's primary business identifiers.

## Provider adapters

Each provider adapter should be responsible for the mechanics of one payment service:

- Mapping internal product keys to provider Price, Plan, Product, or SKU identifiers.
- Creating the provider checkout session or payment intent.
- Supplying browser-safe client secrets or hosted checkout URLs.
- Verifying webhook signatures.
- Translating provider events into normalized application events.
- Storing provider IDs for support, reconciliation, and troubleshooting.

Stripe-specific code would therefore live mostly in a Stripe adapter. The rest of the application would depend on internal concepts such as `payment_attempt_id`, `product_key`, `customer_id`, `status`, and `fulfillment_action`.

## Configuration and routing

Provider choice should be configuration-driven where possible. The application can start simple with one default provider, then grow into more advanced routing when there is a real business reason.

Possible routing inputs:

| Input | Example use |
| --- | --- |
| Product or service type | Use one provider for subscriptions and another for one-time services |
| Customer region or currency | Route to providers with better local payment-method support |
| Account or tenant | Support partner-specific payment arrangements |
| Feature requirement | Use a provider only when it supports billing portal, tax, installments, or a required payment method |
| Operational status | Temporarily route new checkouts away from an unhealthy provider |

This does not mean every payment should dynamically fail over in real time. Payments are stateful. A checkout started with one provider generally needs to finish with that provider. Redundancy is more realistic for new checkout creation, provider onboarding, and future product flexibility than for mid-payment failover.

## Normalized statuses

The gateway should normalize provider-specific events into a small status model that the business can rely on.

Example status model:

| Status | Meaning |
| --- | --- |
| `created` | The application created a payment attempt |
| `checkout_open` | A provider checkout was created and is available to the customer |
| `payment_pending` | Payment is awaiting customer action or delayed confirmation |
| `paid` | Payment succeeded and fulfillment may proceed |
| `failed` | Payment failed |
| `canceled` | Customer or system canceled the checkout |
| `refunded` | Payment was refunded |
| `disputed` | Provider reported a dispute or chargeback |

Provider payloads can still be stored for audit and support, but downstream business workflows should react to the normalized statuses.

## What should not be abstracted too early

The gateway should not become a large theoretical framework before the product needs it. Some provider features are meaningfully different and should not be flattened prematurely.

Avoid over-abstracting:

- Tax calculation rules.
- Subscription lifecycle edge cases.
- Disputes and chargebacks.
- Provider-hosted billing portal behavior.
- Payment method availability by country.
- Deep reporting and reconciliation details.

The right approach is a thin abstraction over the capabilities the application actually uses, with escape hatches for provider-specific references and operations.

## Recommended near-term path

For this POC, direct Stripe integration is appropriate. It proves the payment experience quickly and keeps the demo easy to understand.

For the next production-oriented iteration, Ave7Lift should introduce an internal payment gateway boundary before Stripe calls spread through the application. The first version can be small:

1. Define a `PaymentGateway` interface or service module.
2. Move Stripe Checkout Session creation behind a Stripe adapter.
3. Store an application-owned payment attempt before calling Stripe.
4. Normalize Stripe webhooks into internal payment events.
5. Keep provider IDs as references on application records.
6. Use configuration to choose the active provider, even if Stripe is the only configured provider at first.

This gives the team the low-friction benefits of Stripe now while preserving room for future providers, redundancy, and vendor flexibility.
