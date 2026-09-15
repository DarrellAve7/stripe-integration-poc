import os
import sqlite3
from datetime import datetime, timezone

import stripe
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        STRIPE_SECRET_KEY=os.environ.get("STRIPE_SECRET_KEY"),
        STRIPE_PUBLISHABLE_KEY=os.environ.get("STRIPE_PUBLISHABLE_KEY"),
        STRIPE_PAYMENT_LINK_URL=os.environ.get("STRIPE_PAYMENT_LINK_URL"),
        STRIPE_ONE_TIME_PRICE_ID=os.environ.get("STRIPE_ONE_TIME_PRICE_ID"),
        STRIPE_SUBSCRIPTION_PRICE_ID=os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID"),
        STRIPE_WEBHOOK_SECRET=os.environ.get("STRIPE_WEBHOOK_SECRET"),
        STRIPE_API_VERSION=os.environ.get(
            "STRIPE_API_VERSION", "2026-03-25.dahlia"
        ),
        DATABASE=os.environ.get(
            "STRIPE_EVENT_DATABASE",
            os.path.join(app.instance_path, "stripe-poc.sqlite3"),
        ),
    )
    if test_config:
        app.config.update(test_config)

    def configured(*keys):
        return all(app.config.get(key) for key in keys)

    def configure_stripe():
        stripe.api_key = app.config["STRIPE_SECRET_KEY"]
        stripe.api_version = app.config["STRIPE_API_VERSION"]

    def valid_price_id(price_id):
        return isinstance(price_id, str) and price_id.startswith("price_")

    def database_connection():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        return connection

    def initialize_database():
        database_directory = os.path.dirname(app.config["DATABASE"])
        if database_directory:
            os.makedirs(database_directory, exist_ok=True)
        with database_connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkout_events (
                    session_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    payment_status TEXT NOT NULL,
                    poc_option TEXT,
                    received_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(checkout_events)")
            }
            if "poc_option" not in columns:
                connection.execute("ALTER TABLE checkout_events ADD COLUMN poc_option TEXT")

    def poc_option_for_session(session):
        if session.get("payment_link"):
            return "Payment Link"
        if session.get("metadata", {}).get("poc_option") == "payment-element":
            return "Payment Element"
        if session["mode"] == "subscription":
            return "Hosted subscription"
        if session.get("metadata", {}).get("poc_option") == "hosted-checkout":
            return "Hosted Checkout"
        return "Legacy receipt"

    def record_checkout_event(session):
        with database_connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO checkout_events
                    (session_id, mode, payment_status, poc_option, received_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    session["mode"],
                    session.get("payment_status", "pending"),
                    poc_option_for_session(session),
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                ),
            )

    def checkout_events():
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT session_id AS id, mode, payment_status, poc_option, received_at
                FROM checkout_events
                ORDER BY received_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    initialize_database()

    @app.get("/")
    def index():
        one_time_price_ready = valid_price_id(app.config["STRIPE_ONE_TIME_PRICE_ID"])
        secret_key_ready = configured("STRIPE_SECRET_KEY")
        publishable_key_ready = configured("STRIPE_PUBLISHABLE_KEY")
        return render_template(
            "index.html",
            payment_link_url=app.config["STRIPE_PAYMENT_LINK_URL"],
            one_time_ready=secret_key_ready and one_time_price_ready,
            subscription_ready=(
                configured("STRIPE_SECRET_KEY", "STRIPE_SUBSCRIPTION_PRICE_ID")
                and valid_price_id(app.config["STRIPE_SUBSCRIPTION_PRICE_ID"])
            ),
            payment_element_ready=(
                secret_key_ready and publishable_key_ready and one_time_price_ready
            ),
            one_time_price_ready=one_time_price_ready,
            secret_key_ready=secret_key_ready,
            publishable_key_ready=publishable_key_ready,
            events=checkout_events(),
        )

    @app.post("/checkout/one-time")
    def create_one_time_checkout():
        return create_checkout_session(
            mode="payment",
            price_id=app.config["STRIPE_ONE_TIME_PRICE_ID"],
            poc_option="hosted-checkout",
        )

    @app.post("/checkout/subscription")
    def create_subscription_checkout():
        return create_checkout_session(
            mode="subscription",
            price_id=app.config["STRIPE_SUBSCRIPTION_PRICE_ID"],
            poc_option="hosted-subscription",
        )

    @app.get("/payment-element")
    def payment_element():
        if not configured(
            "STRIPE_SECRET_KEY",
            "STRIPE_PUBLISHABLE_KEY",
            "STRIPE_ONE_TIME_PRICE_ID",
        ) or not valid_price_id(app.config["STRIPE_ONE_TIME_PRICE_ID"]):
            return render_template(
                "error.html",
                message=(
                    "Configure the Stripe secret key, publishable key, and one-time "
                    "Price ID (`price_...`) first."
                ),
            ), 503
        return render_template(
            "payment_element.html",
            publishable_key=app.config["STRIPE_PUBLISHABLE_KEY"],
        )

    @app.post("/checkout/payment-element-session")
    def create_payment_element_session():
        if not configured(
            "STRIPE_SECRET_KEY",
            "STRIPE_PUBLISHABLE_KEY",
            "STRIPE_ONE_TIME_PRICE_ID",
        ) or not valid_price_id(app.config["STRIPE_ONE_TIME_PRICE_ID"]):
            return jsonify(
                error="Configure the Stripe keys and one-time Price ID (`price_...`) first."
            ), 503

        configure_stripe()
        try:
            session = stripe.checkout.Session.create(
                mode="payment",
                ui_mode="elements",
                line_items=[
                    {"price": app.config["STRIPE_ONE_TIME_PRICE_ID"], "quantity": 1}
                ],
                metadata={"poc_option": "payment-element"},
                return_url=url_for("checkout_success", _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}",
            )
        except stripe.StripeError as error:
            return jsonify(error=error.user_message or str(error)), 502

        return jsonify(clientSecret=session.client_secret)

    def create_checkout_session(mode, price_id, poc_option):
        if not configured("STRIPE_SECRET_KEY") or not valid_price_id(price_id):
            return render_template(
                "error.html",
                message=(
                    "Configure the Stripe secret key and the required Price ID "
                    "(`price_...`) first."
                ),
            ), 503

        configure_stripe()
        try:
            session = stripe.checkout.Session.create(
                mode=mode,
                line_items=[{"price": price_id, "quantity": 1}],
                metadata={"poc_option": poc_option},
                success_url=url_for("checkout_success", _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=url_for("index", _external=True),
            )
        except stripe.StripeError as error:
            return render_template("error.html", message=error.user_message or str(error)), 502

        return redirect(session.url, code=303)

    @app.get("/checkout/success")
    def checkout_success():
        session_id = request.args.get("session_id")
        if not session_id:
            abort(400, "Missing Checkout Session ID.")
        if not configured("STRIPE_SECRET_KEY"):
            return render_template(
                "error.html", message="Configure STRIPE_SECRET_KEY to look up this session."
            ), 503

        configure_stripe()
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as error:
            return render_template("error.html", message=error.user_message or str(error)), 502
        return render_template("success.html", session=session)

    @app.get("/transactions")
    def transactions():
        return render_template("transactions.html", events=checkout_events())

    @app.get("/payment-link/success")
    def payment_link_success():
        return render_template("payment_link_success.html")

    @app.post("/webhook")
    def stripe_webhook():
        if not configured("STRIPE_WEBHOOK_SECRET"):
            abort(503, "Configure STRIPE_WEBHOOK_SECRET before accepting webhooks.")

        try:
            event = stripe.Webhook.construct_event(
                request.get_data(),
                request.headers.get("Stripe-Signature", ""),
                app.config["STRIPE_WEBHOOK_SECRET"],
            )
        except ValueError:
            abort(400, "Invalid webhook payload.")
        except stripe.SignatureVerificationError:
            abort(400, "Invalid webhook signature.")

        if event["type"] == "checkout.session.completed":
            record_checkout_event(event["data"]["object"])
        return "", 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(port=4242)
