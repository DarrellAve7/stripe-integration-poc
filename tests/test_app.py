import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app


class StripeDemoTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.config = {
            "TESTING": True,
            "STRIPE_SECRET_KEY": "sk_test_example",
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

    @patch("app.stripe.Webhook.construct_event")
    def test_completed_checkout_webhook_is_recorded(self, construct_event):
        construct_event.return_value = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_completed",
                    "mode": "payment",
                    "payment_status": "paid",
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
        restarted_homepage = create_app(self.config).test_client().get("/")
        self.assertIn(b"cs_test_completed", restarted_homepage.data)


if __name__ == "__main__":
    unittest.main()
