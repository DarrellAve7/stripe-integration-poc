# Stripe integration options roadmap

This POC presents payment integrations in ascending implementation effort. All options should use Stripe Sandbox keys for local testing and use signature-verified webhooks for reliable fulfillment.

| Rank | Option | App-owned checkout UI | Server work | Browser work | POC decision |
| --- | --- | --- | --- | --- | --- |
| 1 | [Payment Links](https://docs.stripe.com/payment-links) | No | None when configured in Dashboard | Normal link only | Implemented |
| 2 | [Hosted Checkout](https://docs.stripe.com/checkout/quickstart) | No | Create a Checkout Session | Redirect to its returned URL | Implemented |
| 2 | Hosted Checkout subscriptions | No | Create a Checkout Session with a recurring Price | Redirect to its returned URL | Implemented |
| 3 | [Embedded Checkout form](https://docs.stripe.com/checkout/form/quickstart) | Partially | Create a Checkout Session and provide its client secret | Load Stripe.js and mount the embedded form | Deferred |
| 4 | [Payment Element with Checkout Sessions](https://docs.stripe.com/payments/quickstart) | Yes | Create a Checkout Session and provide its client secret | Load Stripe.js, mount, and confirm the Payment Element | Implemented |
| 5 | [Payment Element with Payment Intents](https://docs.stripe.com/payments/quickstart-payment-intents) | Yes | Create and manage Payment Intents plus application checkout state | Load Stripe.js, mount, confirm, and handle state changes | Deferred |

## Implemented POC paths

Payment Links demonstrate Stripe's no-code route. The dashboard owns the Product, Price, and hosted payment page; the application only links to it.

To return to this demo after a successful Payment Link payment, configure the Payment Link in the Stripe Dashboard: **After payment → Redirect to a URL** → `http://localhost:4242/payment-link/success`. This app route provides a **Return to demo** action. The Payment Link continues to be Dashboard-managed; webhook fulfillment remains independent of this redirect.

Hosted Checkout demonstrates the lowest-code application integration. The Python server controls the Price ID and creates a one-time or subscription Checkout Session. Stripe hosts data collection and payment authentication, then Stripe notifies the application with `checkout.session.completed`.

## Deferred paths

Embedded Checkout is useful when a checkout should appear within the application layout while Stripe still supplies the checkout experience. It adds a browser integration and is therefore not required to establish the POC.

Payment Element with Checkout Sessions is the implemented custom in-page payment path. Checkout Sessions retains higher-level capabilities such as line items and subscriptions while the application takes responsibility for rendering and confirming the payment form.

This path requires Stripe API version `2026-03-25.dahlia` or newer and a matching versioned Stripe.js release. The app sets the server version through `STRIPE_API_VERSION` and loads `https://js.stripe.com/dahlia/stripe.js`, so an account-wide Sandbox upgrade is not required. Do not change a live account version for this POC.

The custom form mounts Stripe's Contact Details Element alongside the Payment Element. It collects the email address Checkout requires before confirmation without sending payment details through the application.

Payment Element with raw Payment Intents is intentionally last. It is appropriate only when the application must control lower-level payment and checkout state that Checkout Sessions does not cover. It demands more custom server logic and client-side state handling.

## Recommended demonstration order

1. Payment Link: show the Dashboard-created URL and complete a payment without application payment code.
2. Hosted Checkout: show the small Flask endpoint creating a Session, then the browser redirect to the same Stripe-hosted payment experience.
3. Hosted subscription: show that a recurring Price changes the same integration into a subscription flow.
4. Payment Element with Checkout Sessions: compare the custom in-app form with the hosted payment pages.
