import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app, stripe


class StripeDemoTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.config = {
            "TESTING": True,
            "STRIPE_SECRET_KEY": "sk_test_example",
            "STRIPE_PUBLISHABLE_KEY": "pk_test_example",
            "STRIPE_API_VERSION": "2026-03-25.dahlia",
            "STRIPE_ONE_TIME_PRICE_ID": "price_one_time",
            "STRIPE_SUBSCRIPTION_PRICE_ID": "price_subscription",
            "STRIPE_WEBHOOK_SECRET": "whsec_example",
            "DATABASE": str(Path(self.temp_directory.name) / "events.sqlite3"),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_directory.cleanup()

    @patch("app.stripe.checkout.Session.create")
    def test_one_time_checkout_creates_payment_session(self, create_session):
        create_session.return_value = SimpleNamespace(url="https://checkout.stripe.test/session")

        response = self.client.post("/checkout/one-time")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["Location"], "https://checkout.stripe.test/session")
        arguments = create_session.call_args.kwargs
        self.assertEqual(arguments["mode"], "payment")
        self.assertEqual(arguments["line_items"], [{"price": "price_one_time", "quantity": 1}])
        self.assertEqual(arguments["metadata"], {"poc_option": "hosted-checkout"})
        self.assertIn("{CHECKOUT_SESSION_ID}", arguments["success_url"])

    @patch("app.stripe.checkout.Session.create")
    def test_subscription_checkout_creates_subscription_session(self, create_session):
        create_session.return_value = SimpleNamespace(url="https://checkout.stripe.test/subscription")

        response = self.client.post("/checkout/subscription")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(create_session.call_args.kwargs["mode"], "subscription")
        self.assertEqual(
            create_session.call_args.kwargs["line_items"],
            [{"price": "price_subscription", "quantity": 1}],
        )
        self.assertEqual(
            create_session.call_args.kwargs["metadata"],
            {"poc_option": "hosted-subscription"},
        )

    @patch("app.stripe.checkout.Session.create")
    def test_payment_element_creates_checkout_session_with_client_secret(
        self, create_session
    ):
        create_session.return_value = SimpleNamespace(
            client_secret="cs_test_element_secret"
        )

        response = self.client.post("/checkout/payment-element-session")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"clientSecret": "cs_test_element_secret"})
        arguments = create_session.call_args.kwargs
        self.assertEqual(arguments["mode"], "payment")
        self.assertEqual(arguments["ui_mode"], "elements")
        self.assertEqual(arguments["line_items"], [{"price": "price_one_time", "quantity": 1}])
        self.assertEqual(arguments["metadata"], {"poc_option": "payment-element"})
        self.assertIn("{CHECKOUT_SESSION_ID}", arguments["return_url"])
        self.assertEqual(stripe.api_version, "2026-03-25.dahlia")

    def test_payment_element_page_uses_publishable_key(self):
        response = self.client.get("/payment-element")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"https://js.stripe.com/dahlia/stripe.js", response.data)
        self.assertIn(b"pk_test_example", response.data)
        self.assertIn(b"Payment form could not load:", response.data)
        self.assertIn(b"Payment confirmation failed:", response.data)
        self.assertIn(b'event.preventDefault()', response.data)
        self.assertIn(b'Loading payment form...', response.data)
        self.assertIn(b'checkout.createContactDetailsElement()', response.data)

    def test_product_id_does_not_enable_checkout(self):
        app = create_app({**self.config, "STRIPE_ONE_TIME_PRICE_ID": "prod_example"})

        response = app.test_client().post("/checkout/payment-element-session")

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"price_...", response.data)

    def test_home_page_explains_invalid_one_time_price_id(self):
        app = create_app({**self.config, "STRIPE_ONE_TIME_PRICE_ID": "prod_example"})

        response = app.test_client().get("/")

        self.assertIn(b"Set a one-time Price ID beginning", response.data)

    def test_payment_link_success_page_returns_to_demo(self):
        response = self.client.get("/payment-link/success")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Return to demo", response.data)
        self.assertIn(b'href="/"', response.data)

    def test_home_page_explains_hosted_integration_differences(self):
        response = self.client.get("/")

        self.assertIn(b"<title>Ave7Lift Stripe POC</title>", response.data)
        self.assertIn(b"ave7-short-logo-white.png", response.data)
        self.assertIn(b"Ave7Lift POC: Payment integration", response.data)
        self.assertIn(b"What changes between the hosted options?", response.data)
        self.assertIn(b"Flask creates a Session?", response.data)
        self.assertIn(b"Browser -&gt; Stripe Payment Link", response.data)
        self.assertIn(
            b"Browser -&gt; Flask (client secret) -&gt; Stripe.js -&gt; Stripe -&gt; Browser",
            response.data,
        )
        self.assertIn(b"Embedded Checkout", response.data)
        self.assertIn(b"Payment Element + Payment Intents", response.data)

    @patch("app.stripe.Webhook.construct_event")
    def test_completed_checkout_webhook_is_recorded(self, construct_event):
        construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_completed",
                    "mode": "payment",
                    "payment_status": "paid",
                    "metadata": {"poc_option": "payment-element"},
                }
            },
        }

        response = self.client.post(
            "/webhook",
            data=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "test_signature"},
        )

        self.assertEqual(response.status_code, 200)
        homepage = self.client.get("/")
        self.assertIn(b"cs_test_completed", homepage.data)
        self.assertIn(b"paid", homepage.data)
        self.assertIn(b"Payment Element", homepage.data)
        restarted_homepage = create_app(self.config).test_client().get("/")
        self.assertIn(b"cs_test_completed", restarted_homepage.data)

    def test_transactions_list_payment_element_receipt(self):
        with sqlite3.connect(self.config["DATABASE"]) as connection:
            connection.execute(
                """
                INSERT INTO checkout_events
                    (session_id, mode, payment_status, poc_option, received_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "cs_test_older",
                    "payment",
                    "paid",
                    "Hosted Checkout",
                    "2026-09-15 18:10:00 UTC",
                ),
            )
            connection.execute(
                """
                INSERT INTO checkout_events
                    (session_id, mode, payment_status, poc_option, received_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "cs_test_transaction",
                    "payment",
                    "paid",
                    "Payment Element",
                    "2026-09-15 18:11:00 UTC",
                ),
            )

        response = self.client.get("/transactions")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Payment Element", response.data)
        self.assertIn(b"cs_test_transaction", response.data)
        self.assertLess(response.data.index(b"cs_test_transaction"), response.data.index(b"cs_test_older"))


if __name__ == "__main__":
    unittest.main()
