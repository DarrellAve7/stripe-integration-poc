import os
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

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

    def sandbox_secret_key_error():
        secret_key = app.config.get("STRIPE_SECRET_KEY")
        if not secret_key:
            return "Configure STRIPE_SECRET_KEY before starting checkout."
        if secret_key.startswith(("sk_live_", "rk_live_")):
            return (
                "This POC refuses live Stripe secret keys. Use a Sandbox key "
                "beginning with sk_test_ or rkcs_test_."
            )
        if not secret_key.startswith(("sk_test_", "rkcs_test_")):
            return "Use a Stripe Sandbox secret key beginning with sk_test_ or rkcs_test_."
        return None

    def sandbox_publishable_key_error():
        publishable_key = app.config.get("STRIPE_PUBLISHABLE_KEY")
        if not publishable_key:
            return "Configure STRIPE_PUBLISHABLE_KEY before opening the custom form."
        if publishable_key.startswith("pk_live_"):
            return (
                "This POC refuses live Stripe publishable keys. Use a Sandbox "
                "publishable key beginning with pk_test_."
            )
        if not publishable_key.startswith("pk_test_"):
            return "Use a Stripe Sandbox publishable key beginning with pk_test_."
        return None

    def sandbox_secret_key_ready():
        return sandbox_secret_key_error() is None

    def sandbox_publishable_key_ready():
        return sandbox_publishable_key_error() is None

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS checkout_attempts (
                    id TEXT PRIMARY KEY,
                    target_item_id TEXT NOT NULL,
                    actor_reference TEXT NOT NULL,
                    product_key TEXT NOT NULL,
                    stripe_price_id TEXT NOT NULL,
                    stripe_checkout_session_id TEXT UNIQUE,
                    stripe_payment_intent_id TEXT,
                    stripe_subscription_id TEXT,
                    amount_total INTEGER,
                    currency TEXT,
                    status TEXT NOT NULL,
                    failure_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_events (
                    stripe_event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    checkout_attempt_id TEXT,
                    received_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fulfillment_actions (
                    checkout_attempt_id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def now():
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

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
                    now(),
                ),
            )

    def fix_now_products():
        return {
            "one-time-service": {
                "label": "One-time Fix Now service",
                "mode": "payment",
                "price_id": app.config["STRIPE_ONE_TIME_PRICE_ID"],
            },
            "service-plan": {
                "label": "Recurring service plan",
                "mode": "subscription",
                "price_id": app.config["STRIPE_SUBSCRIPTION_PRICE_ID"],
            },
        }

    def fix_now_attempts(limit=20):
        with database_connection() as connection:
            rows = connection.execute(
                """
                SELECT checkout_attempts.*,
                       fulfillment_actions.status AS fulfillment_status
                FROM checkout_attempts
                LEFT JOIN fulfillment_actions
                  ON fulfillment_actions.checkout_attempt_id = checkout_attempts.id
                ORDER BY checkout_attempts.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def fix_now_attempt(attempt_id):
        with database_connection() as connection:
            row = connection.execute(
                """
                SELECT checkout_attempts.*,
                       fulfillment_actions.status AS fulfillment_status
                FROM checkout_attempts
                LEFT JOIN fulfillment_actions
                  ON fulfillment_actions.checkout_attempt_id = checkout_attempts.id
                WHERE checkout_attempts.id = ?
                """,
                (attempt_id,),
            ).fetchone()
        return dict(row) if row else None

    def update_attempt_from_session(session, status):
        attempt_id = session.get("metadata", {}).get("checkout_attempt_id")
        if not attempt_id:
            return
        timestamp = now()
        with database_connection() as connection:
            connection.execute(
                """
                UPDATE checkout_attempts
                SET stripe_payment_intent_id = COALESCE(?, stripe_payment_intent_id),
                    stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                    amount_total = COALESCE(?, amount_total),
                    currency = COALESCE(?, currency),
                    status = ?,
                    updated_at = ?,
                    completed_at = CASE WHEN ? = 'paid' THEN ? ELSE completed_at END
                WHERE id = ?
                """,
                (
                    session.get("payment_intent"),
                    session.get("subscription"),
                    session.get("amount_total"),
                    session.get("currency"),
                    status,
                    timestamp,
                    status,
                    timestamp,
                    attempt_id,
                ),
            )
            if status == "paid":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO fulfillment_actions
                        (checkout_attempt_id, action_type, status, created_at)
                    VALUES (?, 'manual_fix_now_review', 'pending', ?)
                    """,
                    (attempt_id, timestamp),
                )

    def record_webhook_event(event):
        session = event["data"]["object"]
        attempt_id = session.get("metadata", {}).get("checkout_attempt_id")
        with database_connection() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO webhook_events
                    (stripe_event_id, event_type, checkout_attempt_id, received_at)
                VALUES (?, ?, ?, ?)
                """,
                (event["id"], event["type"], attempt_id, now()),
            )
        return cursor.rowcount == 1

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
        secret_key_ready = sandbox_secret_key_ready()
        publishable_key_ready = sandbox_publishable_key_ready()
        return render_template(
            "index.html",
            payment_link_url=app.config["STRIPE_PAYMENT_LINK_URL"],
            one_time_ready=secret_key_ready and one_time_price_ready,
            subscription_ready=(
                secret_key_ready
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

    @app.get("/fix-now")
    def fix_now():
        products = [
            {"key": key, **product}
            for key, product in fix_now_products().items()
            if valid_price_id(product["price_id"])
        ]
        return render_template(
            "fix_now.html",
            products=products,
            attempts=fix_now_attempts(),
            target_item_id="ave7lift-demo-item-001",
        )

    @app.post("/fix-now/checkout")
    def create_fix_now_checkout():
        product = fix_now_products().get(request.form.get("product_key"))
        if not product or not valid_price_id(product["price_id"]):
            abort(400, "Choose a configured Fix Now service.")
        secret_key_error = sandbox_secret_key_error()
        publishable_key_error = sandbox_publishable_key_error()
        if secret_key_error or publishable_key_error:
            abort(503, secret_key_error or publishable_key_error)

        attempt_id = str(uuid4())
        timestamp = now()
        target_item_id = "ave7lift-demo-item-001"
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO checkout_attempts
                    (id, target_item_id, actor_reference, product_key, stripe_price_id,
                     status, created_at, updated_at)
                VALUES (?, ?, 'authentication-boundary-demo', ?, ?, 'created', ?, ?)
                """,
                (attempt_id, target_item_id, request.form["product_key"], product["price_id"], timestamp, timestamp),
            )

        configure_stripe()
        try:
            session = stripe.checkout.Session.create(
                mode=product["mode"],
                ui_mode="elements",
                line_items=[{"price": product["price_id"], "quantity": 1}],
                client_reference_id=attempt_id,
                metadata={
                    "checkout_attempt_id": attempt_id,
                    "target_item_id": target_item_id,
                    "product_key": request.form["product_key"],
                    "poc_option": "fix-now",
                },
                return_url=url_for("fix_now_attempt_page", attempt_id=attempt_id, _external=True)
                + "?session_id={CHECKOUT_SESSION_ID}",
                idempotency_key=attempt_id,
            )
        except stripe.StripeError as error:
            with database_connection() as connection:
                connection.execute(
                    """
                    UPDATE checkout_attempts
                    SET status = 'checkout_creation_failed', failure_message = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (error.user_message or str(error), now(), attempt_id),
                )
            return render_template("error.html", message=error.user_message or str(error)), 502

        with database_connection() as connection:
            connection.execute(
                """
                UPDATE checkout_attempts
                SET stripe_checkout_session_id = ?, status = 'checkout_open', updated_at = ?,
                    amount_total = ?, currency = ?
                WHERE id = ?
                """,
                (session.id, now(), session.get("amount_total"), session.get("currency"), attempt_id),
            )
        return render_template(
            "fix_now_payment.html",
            attempt_id=attempt_id,
            client_secret=session.client_secret,
            product_label=product["label"],
            publishable_key=app.config["STRIPE_PUBLISHABLE_KEY"],
            target_item_id=target_item_id,
        )

    @app.get("/fix-now/attempt/<attempt_id>")
    def fix_now_attempt_page(attempt_id):
        attempt = fix_now_attempt(attempt_id)
        if not attempt:
            abort(404)
        return render_template("fix_now_attempt.html", attempt=attempt)

    @app.get("/payment-element")
    def payment_element():
        secret_key_error = sandbox_secret_key_error()
        publishable_key_error = sandbox_publishable_key_error()
        if secret_key_error or publishable_key_error or not valid_price_id(app.config["STRIPE_ONE_TIME_PRICE_ID"]):
            return render_template(
                "error.html",
                message=(
                    secret_key_error
                    or publishable_key_error
                    or "Configure the one-time Price ID (`price_...`) first."
                ),
            ), 503
        return render_template(
            "payment_element.html",
            publishable_key=app.config["STRIPE_PUBLISHABLE_KEY"],
        )

    @app.post("/checkout/payment-element-session")
    def create_payment_element_session():
        secret_key_error = sandbox_secret_key_error()
        publishable_key_error = sandbox_publishable_key_error()
        if secret_key_error or publishable_key_error or not valid_price_id(app.config["STRIPE_ONE_TIME_PRICE_ID"]):
            return jsonify(
                error=(
                    secret_key_error
                    or publishable_key_error
                    or "Configure the one-time Price ID (`price_...`) first."
                )
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
        secret_key_error = sandbox_secret_key_error()
        if secret_key_error or not valid_price_id(price_id):
            return render_template(
                "error.html",
                message=(
                    secret_key_error
                    or "Configure the required Price ID (`price_...`) first."
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
        secret_key_error = sandbox_secret_key_error()
        if secret_key_error:
            return render_template(
                "error.html", message=secret_key_error
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

        if not record_webhook_event(event):
            return "", 200

        session = event["data"]["object"]
        if event["type"] == "checkout.session.completed":
            record_checkout_event(session)
            update_attempt_from_session(
                session, "paid" if session.get("payment_status") == "paid" else "payment_pending"
            )
        elif event["type"] == "checkout.session.async_payment_succeeded":
            record_checkout_event(session)
            update_attempt_from_session(session, "paid")
        elif event["type"] == "checkout.session.async_payment_failed":
            update_attempt_from_session(session, "failed")
        return "", 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run(port=4242)
