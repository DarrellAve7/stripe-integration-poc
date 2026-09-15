# Ave7Lift Stripe POC

A minimal Flask application that demonstrates Stripe payment integrations in a Sandbox. The POC implements the lowest-effort hosted paths and makes the next, more customizable paths visible for comparison.

| POC path | Stripe option | Relative effort | Availability | Demo action |
| --- | --- | --- | --- | --- |
| 1 | [Payment Links](https://docs.stripe.com/payment-links) | Very low | **Available now** | Opens a Dashboard-created hosted payment page |
| 2 | [Hosted Checkout](https://docs.stripe.com/checkout/quickstart) | Low | **Available now** | Creates a one-time Checkout Session and redirects to Stripe |
| 3 | Hosted Checkout subscription | Low | **Available now** | Creates a recurring Checkout Session and redirects to Stripe |
| 4 | [Payment Element with Checkout Sessions](https://docs.stripe.com/payments/quickstart) | Medium-high | **Available now** | Builds a custom in-page payment form with Stripe.js |
| 5 | [Embedded Checkout form](https://docs.stripe.com/checkout/form/quickstart) | Medium | Deferred | Mounts Stripe Checkout inside the app with Stripe.js |
| 6 | [Payment Element with Payment Intents](https://docs.stripe.com/payments/quickstart-payment-intents) | High | Deferred | Owns the lower-level payment lifecycle and checkout state |

Card data is entered only on Stripe-hosted pages. The demo records `checkout.session.completed` webhook receipts to show the reliable fulfillment signal; the success-page redirect is not used to fulfill an order.

The Payment Element form also uses Stripe's Contact Details Element to collect the email address required by its Checkout Session.

The **Transactions** page lists received completion webhooks newest first and identifies the POC integration that created each new Checkout Session.

The **Fix Now** page sketches the next MVP step using the custom in-app Payment Element path: server-owned service selection, durable checkout attempts, Stripe metadata/idempotency, webhook status synchronization, and a pending manual-fulfillment queue. Authentication remains an intentional integration boundary.

## Available documentation

> [!IMPORTANT]
> **Technical whitepaper available:** [POC goals, implementation details, Mermaid flows, and four-option comparison](docs/technical-whitepaper.md).
>
> **Fix Now roadmap available:** [minimal real-checkout scope, Stripe data synchronization, downstream fulfillment, and the billing-management roadmap](docs/fix-now-roadmap.md).
>
> **Payment gateway abstraction recommendation:** [why Stripe and future providers should sit behind an internal payment API](docs/payment-gateway-abstraction.md).

See [the integration options roadmap](docs/integration-options.md) for the trade-offs and planned progression.

## Status

**v0.2.0 MVP/POC:** The four implemented Stripe Sandbox paths have been exercised end to end, with `checkout.session.completed` receipts captured by the application.

## Start a local Sandbox test

1. In the Stripe Dashboard, create or select a [Stripe Sandbox](https://docs.stripe.com/sandboxes). Do not use live mode.
2. In that Sandbox, create a one-time Price and a recurring Price in **Product catalog**, then create a Payment Link using either product.
   - The app pins server requests to Stripe API version `2026-03-25.dahlia` and loads the matching versioned Stripe.js release. Both are required for `ui_mode="elements"` Checkout Sessions; an account-wide Sandbox upgrade is not required.
   - For the Payment Link, edit its post-payment behavior in the Stripe Dashboard and set **After payment → Redirect to a URL** to `http://localhost:4242/payment-link/success`. The app then displays a **Return to demo** link after successful Payment Link payment.
3. Create a virtual environment and install the application:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -e .
   ```

4. Install the Stripe CLI and authenticate it with the same Stripe account:

   ```bash
   npm install -g @stripe/cli
   stripe login
   ```

5. Copy `.env.example` to `.env`, then replace every placeholder with Sandbox values:

   ```bash
   cp .env.example .env
   ```

   | Variable | Value |
   | --- | --- |
   | `STRIPE_SECRET_KEY` | Active Sandbox secret or restricted key, such as `sk_test_...` or `rkcs_test_...` |
   | `STRIPE_PUBLISHABLE_KEY` | Sandbox publishable key beginning with `pk_test_` |
   | `STRIPE_API_VERSION` | `2026-03-25.dahlia` or newer; required for Payment Element |
   | `STRIPE_PAYMENT_LINK_URL` | Dashboard-created `https://buy.stripe.com/...` link |
   | `STRIPE_ONE_TIME_PRICE_ID` | One-time Price ID beginning `price_...`, not the `prod_...` Product ID |
   | `STRIPE_SUBSCRIPTION_PRICE_ID` | Recurring Price ID beginning `price_...`, not the `prod_...` Product ID |
   | `STRIPE_WEBHOOK_SECRET` | Any placeholder value; `start.sh` obtains the active value |

   Do not use or commit live keys. The app refuses live secret and publishable keys. `start.sh` obtains a fresh webhook signing secret each time it runs and supplies it to the app without modifying `.env`.

6. In another terminal, load the environment and start the application:

   ```bash
   ./start.sh
   ```

Open <http://localhost:4242>. Use `4242 4242 4242 4242`, any future expiration date, and any CVC to complete a successful Sandbox payment. See [Stripe testing](https://docs.stripe.com/testing) for authentication and failure test cards.

Stop the local application before restarting it:

```bash
./end.sh
```

`start.sh` starts the Stripe webhook listener and writes its output to `.run/stripe-listen.log`. `end.sh` records, verifies, and stops both the Flask application and the listener that `start.sh` started. It does not stop unrelated processes.

## Manually stop leftover processes

Use `Ctrl+C` in the terminal that started a process whenever possible. If that terminal is unavailable, list only the demo-related processes:

```bash
ps -eo pid,args | grep -E '[p]ython.*app\.py|[s]tripe listen'
```

Stop an individual PID from that output:

```bash
kill <PID>
```

Use `kill -9 <PID>` only when the normal signal does not stop that specific process after a few seconds. Do not use broad process-name termination commands, because they can stop unrelated applications.

## Verify webhook forwarding

`start.sh` automatically starts the listener. A successful checkout automatically emits `checkout.session.completed`; no manual trigger is needed. To verify the local listener without completing a payment, send a synthetic test event:

```bash
stripe trigger checkout.session.completed
```

The listener should report a `200` response and the app's **Webhook receipts** section should show the event after refresh. The listener only forwards events that occur while it is running. To test a real payment, use any of the four app actions and the Sandbox test card above.

Webhook receipts persist across application restarts in `instance/stripe-poc.sqlite3`. Set `STRIPE_EVENT_DATABASE` to use another local SQLite database path. The database stores only Checkout Session IDs, modes, payment statuses, and receipt timestamps.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```
