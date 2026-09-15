# Stripe Integration POC

A minimal Flask application that demonstrates Stripe's simplest web payment integrations in a Sandbox:

| Path | Application work | Demo action |
| --- | --- | --- |
| Payment Link | None | Opens a Stripe Dashboard-created hosted payment page |
| Hosted Checkout payment | Small server endpoint | Creates a one-time Checkout Session and redirects to Stripe |
| Hosted Checkout subscription | Small server endpoint | Creates a recurring Checkout Session and redirects to Stripe |

Card data is entered only on Stripe-hosted pages. The demo records `checkout.session.completed` webhook receipts to show the reliable fulfillment signal; the success-page redirect is not used to fulfill an order.

## Status

**v0.1.0 MVP/POC:** The first Stripe Sandbox integration has been verified end to end: a Checkout payment produced a `checkout.session.completed` webhook receipt in the application.

## Start a local Sandbox test

1. In the Stripe Dashboard, create or select a [Stripe Sandbox](https://docs.stripe.com/sandboxes). Do not use live mode.
2. In that Sandbox, create a one-time Price and a recurring Price in **Product catalog**, then create a Payment Link using either product.
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
   | `STRIPE_SECRET_KEY` | Sandbox secret key beginning with `sk_test_` |
   | `STRIPE_PAYMENT_LINK_URL` | Dashboard-created `https://buy.stripe.com/...` link |
   | `STRIPE_ONE_TIME_PRICE_ID` | One-time `price_...` ID |
   | `STRIPE_SUBSCRIPTION_PRICE_ID` | Recurring `price_...` ID |
   | `STRIPE_WEBHOOK_SECRET` | Any placeholder value; `start.sh` obtains the active value |

   Do not use or commit live keys. `start.sh` obtains a fresh webhook signing secret each time it runs and supplies it to the app without modifying `.env`.

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

The listener should report a `200` response and the app's **Webhook receipts** section should show the event after refresh. The listener only forwards events that occur while it is running. To test a real payment, use any of the three app actions and the Sandbox test card above.

Webhook receipts persist across application restarts in `instance/stripe-poc.sqlite3`. Set `STRIPE_EVENT_DATABASE` to use another local SQLite database path. The database stores only Checkout Session IDs, modes, payment statuses, and receipt timestamps.

## What is deliberately out of scope

Embedded Checkout and the Payment Element are deferred. They require browser-side Stripe.js and more custom checkout code. Raw Payment Intents are lower-level still, requiring the application to own more payment lifecycle and checkout state.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```
