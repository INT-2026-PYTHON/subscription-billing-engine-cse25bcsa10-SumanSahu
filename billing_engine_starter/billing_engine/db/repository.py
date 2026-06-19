"""
Repositories — the ONLY place SQL lives.

Each repository wraps the Database connection and exposes methods that
take/return domain dataclasses (defined in billing_engine/models/).

⚠️ YOU IMPLEMENT every method body marked TODO.
   The signatures, docstrings, and the LedgerRepository's append-only
   guarantee are already in place — do not change them.

Conventions:
  - Always use parameterized queries (`?` placeholders) — NEVER f-string SQL.
  - Money values are persisted as TEXT using `money.to_storage()`.
  - Dates are persisted as ISO strings (`date.isoformat()`).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from billing_engine.db.database import Database
from billing_engine.money import Money
from billing_engine.models import (
    Customer,
    Plan, PricingType, BillingPeriod,
    Subscription, SubscriptionStatus,
    Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind,
    LedgerEntry, LedgerDirection,
)


# ============================================================
# CUSTOMERS
# ============================================================
class CustomerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, customer: Customer) -> Customer:
        """Insert and return the customer with `id` populated."""
        query = """
            INSERT INTO customers (name, email, country_code, state_code)
            VALUES (?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (customer.name, customer.email, customer.country_code, customer.state_code))
            customer_id = cursor.fetchone()[0]
        customer.id = customer_id
        return customer

    def get(self, customer_id: int) -> Optional[Customer]:
        query = "SELECT id, name, email, country_code, state_code FROM customers WHERE id = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (customer_id,)).fetchone()
        if not row:
            return None
        return Customer(id=row[0], name=row[1], email=row[2], country_code=row[3], state_code=row[4])

    def find_by_email(self, email: str) -> Optional[Customer]:
        query = "SELECT id, name, email, country_code, state_code FROM customers WHERE email = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (email,)).fetchone()
        if not row:
            return None
        return Customer(id=row[0], name=row[1], email=row[2], country_code=row[3], state_code=row[4])

    def list_all(self) -> list[Customer]:
        query = "SELECT id, name, email, country_code, state_code FROM customers;"
        with self.db.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [Customer(id=r[0], name=r[1], email=r[2], country_code=r[3], state_code=r[4]) for r in rows]


# ============================================================
# PLANS  +  PLAN TIERS
# ============================================================
class PlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, plan: Plan) -> Plan:
        query = """
            INSERT INTO plans (name, pricing_type, billing_period, currency)
            VALUES (?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (plan.name, plan.pricing_type.value, plan.billing_period.value, plan.currency))
            plan_id = cursor.fetchone()[0]
        plan.id = plan_id
        return plan

    def get(self, plan_id: int) -> Optional[Plan]:
        query = "SELECT id, name, pricing_type, billing_period, currency FROM plans WHERE id = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (plan_id,)).fetchone()
        if not row:
            return None
        return Plan(
            id=row[0],
            name=row[1],
            pricing_type=PricingType(row[2]),
            billing_period=BillingPeriod(row[3]),
            currency=row[4]
        )

    def list_all(self) -> list[Plan]:
        query = "SELECT id, name, pricing_type, billing_period, currency FROM plans;"
        with self.db.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [
            Plan(
                id=r[0],
                name=r[1],
                pricing_type=PricingType(r[2]),
                billing_period=BillingPeriod(r[3]),
                currency=r[4]
            ) for r in rows
        ]


class PlanTierRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, plan_id: int, from_units: int, to_units: Optional[int], unit_price: Money) -> int:
        """Insert a tier; return new id."""
        query = """
            INSERT INTO plan_tiers (plan_id, from_units, to_units, unit_price)
            VALUES (?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (plan_id, from_units, to_units, unit_price.to_storage()))
            tier_id = cursor.fetchone()[0]
        return tier_id

    def list_for_plan(self, plan_id: int, currency: str) -> list[tuple[int, Optional[int], Money]]:
        """Return [(from_units, to_units, unit_price)] ordered by from_units."""
        query = "SELECT from_units, to_units, unit_price FROM plan_tiers WHERE plan_id = ? ORDER BY from_units;"
        with self.db.connect() as conn:
            rows = conn.execute(query, (plan_id,)).fetchall()
        return [(r[0], r[1], Money(r[2], currency)) for r in rows]


# ============================================================
# DISCOUNTS
# ============================================================
class DiscountRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, code: str, discount_type: str, value: str, currency: Optional[str] = None) -> int:
        query = """
            INSERT INTO discounts (code, discount_type, value, currency)
            VALUES (?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (code, discount_type, value, currency))
            discount_id = cursor.fetchone()[0]
        return discount_id

    def get_by_code(self, code: str) -> Optional[dict]:
        """Return raw row as dict, or None."""
        query = "SELECT id, code, discount_type, value, currency FROM discounts WHERE code = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (code,)).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "code": row[1],
            "discount_type": row[2],
            "value": row[3],
            "currency": row[4]
        }


# ============================================================
# SUBSCRIPTIONS
# ============================================================
class SubscriptionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _row_to_model(self, row: tuple) -> Subscription:
        return Subscription(
            id=row[0],
            customer_id=row[1],
            plan_id=row[2],
            status=SubscriptionStatus(row[3]),
            current_period_start=date.fromisoformat(row[4]),
            current_period_end=date.fromisoformat(row[5]),
            trial_end=date.fromisoformat(row[6]) if row[6] else None,
            discount_code=row[7]
        )

    def add(self, subscription: Subscription) -> Subscription:
        query = """
            INSERT INTO subscriptions (customer_id, plan_id, status, current_period_start, current_period_end, trial_end, discount_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (
                subscription.customer_id,
                subscription.plan_id,
                subscription.status.value,
                subscription.current_period_start.isoformat(),
                subscription.current_period_end.isoformat(),
                subscription.trial_end.isoformat() if subscription.trial_end else None,
                subscription.discount_code
            ))
            sub_id = cursor.fetchone()[0]
        subscription.id = sub_id
        return subscription

    def get(self, subscription_id: int) -> Optional[Subscription]:
        query = """
            SELECT id, customer_id, plan_id, status, current_period_start, current_period_end, trial_end, discount_code 
            FROM subscriptions WHERE id = ?;
        """
        with self.db.connect() as conn:
            row = conn.execute(query, (subscription_id,)).fetchone()
        if not row:
            return None
        return self._row_to_model(row)

    def list_all(self) -> list[Subscription]:
        query = """
            SELECT id, customer_id, plan_id, status, current_period_start, current_period_end, trial_end, discount_code 
            FROM subscriptions;
        """
        with self.db.connect() as conn:
            rows = conn.execute(query).fetchall()
        return [self._row_to_model(r) for r in rows]

    def get_due_for_billing(self, as_of: date) -> list[Subscription]:
        query = """
            SELECT id, customer_id, plan_id, status, current_period_start, current_period_end, trial_end, discount_code 
            FROM subscriptions 
            WHERE current_period_end <= ? AND status = ?;
        """
        with self.db.connect() as conn:
            rows = conn.execute(query, (as_of.isoformat(), SubscriptionStatus.ACTIVE.value)).fetchall()
        return [self._row_to_model(r) for r in rows]

    def update_period(self, subscription_id: int, new_start: date, new_end: date) -> None:
        query = """
            UPDATE subscriptions 
            SET current_period_start = ?, current_period_end = ? 
            WHERE id = ?;
        """
        with self.db.transaction() as conn:
            conn.execute(query, (new_start.isoformat(), new_end.isoformat(), subscription_id))

    def update_status(
        self,
        subscription_id: int,
        new_status: SubscriptionStatus,
        past_due_since: Optional[date] = None,
    ) -> None:
        query = """
            UPDATE subscriptions 
            SET status = ?, past_due_since = ? 
            WHERE id = ?;
        """
        with self.db.transaction() as conn:
            conn.execute(query, (
                new_status.value, 
                past_due_since.isoformat() if past_due_since else None, 
                subscription_id
            ))

    def update_plan(self, subscription_id: int, new_plan_id: int) -> None:
        """Switch the subscription to a different plan (used by upgrade flow)."""
        query = "UPDATE subscriptions SET plan_id = ? WHERE id = ?;"
        with self.db.transaction() as conn:
            conn.execute(query, (new_plan_id, subscription_id))


# ============================================================
# USAGE
# ============================================================
class UsageRecordRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, subscription_id: int, metric: str, quantity: int) -> int:
        query = """
            INSERT INTO usage_records (subscription_id, metric, quantity, recorded_at)
            VALUES (?, ?, ?, datetime('now'))
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (subscription_id, metric, quantity))
            record_id = cursor.fetchone()[0]
        return record_id

    def sum_for_period(
        self, subscription_id: int, metric: str, period_start: date, period_end: date
    ) -> int:
        query = """
            SELECT COALESCE(SUM(quantity), 0) 
            FROM usage_records 
            WHERE subscription_id = ? 
              AND metric = ? 
              AND recorded_at >= ? 
              AND recorded_at < ?;
        """
        # Ensure standard interval boundary strategy [start, end)
        with self.db.connect() as conn:
            row = conn.execute(query, (
                subscription_id, 
                metric, 
                period_start.isoformat(), 
                period_end.isoformat()
            )).fetchone()
        return row[0]


# ============================================================
# INVOICES + LINE ITEMS
# ============================================================
class InvoiceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, invoice: Invoice) -> Invoice:
        query = """
            INSERT INTO invoices (subscription_id, period_start, period_end, status, currency, total_amount, tax_amount, pdf_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (
                invoice.subscription_id,
                invoice.period_start.isoformat(),
                invoice.period_end.isoformat(),
                invoice.status.value,
                invoice.currency,
                invoice.total_amount.to_storage(),
                invoice.tax_amount.to_storage(),
                invoice.pdf_path
            ))
            invoice_id = cursor.fetchone()[0]
        invoice.id = invoice_id
        return invoice

    def get(self, invoice_id: int) -> Optional[Invoice]:
        query = """
            SELECT id, subscription_id, period_start, period_end, status, currency, total_amount, tax_amount, pdf_path 
            FROM invoices WHERE id = ?;
        """
        with self.db.connect() as conn:
            row = conn.execute(query, (invoice_id,)).fetchone()
        if not row:
            return None
        
        currency = row[5]
        return Invoice(
            id=row[0],
            subscription_id=row[1],
            period_start=date.fromisoformat(row[2]),
            period_end=date.fromisoformat(row[3]),
            status=InvoiceStatus(row[4]),
            currency=currency,
            total_amount=Money(row[6], currency),
            tax_amount=Money(row[7], currency),
            pdf_path=row[8]
        )

    def count_for_subscription(self, subscription_id: int) -> int:
        query = "SELECT COUNT(*) FROM invoices WHERE subscription_id = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (subscription_id,)).fetchone()
        return row[0]

    def mark_paid(self, invoice_id: int) -> None:
        query = "UPDATE invoices SET status = ? WHERE id = ?;"
        with self.db.transaction() as conn:
            conn.execute(query, (InvoiceStatus.PAID.value, invoice_id))

    def mark_failed(self, invoice_id: int) -> None:
        query = "UPDATE invoices SET status = ? WHERE id = ?;"
        with self.db.transaction() as conn:
            conn.execute(query, (InvoiceStatus.FAILED.value, invoice_id))

    def set_pdf_path(self, invoice_id: int, path: str) -> None:
        query = "UPDATE invoices SET pdf_path = ? WHERE id = ?;"
        with self.db.transaction() as conn:
            conn.execute(query, (path, invoice_id))


class InvoiceLineItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, line_item: InvoiceLineItem) -> InvoiceLineItem:
        query = """
            INSERT INTO invoice_line_items (invoice_id, description, amount, kind)
            VALUES (?, ?, ?, ?)
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (
                line_item.invoice_id,
                line_item.description,
                line_item.amount.to_storage(),
                line_item.kind.value
            ))
            line_item_id = cursor.fetchone()[0]
        line_item.id = line_item_id
        return line_item

    def list_for_invoice(self, invoice_id: int) -> list[InvoiceLineItem]:
        # We need to grab the currency first to rebuild the Money objects properly
        query_curr = "SELECT currency FROM invoices WHERE id = ?;"
        query_lines = "SELECT id, invoice_id, description, amount, kind FROM invoice_line_items WHERE invoice_id = ?;"
        
        with self.db.connect() as conn:
            curr_row = conn.execute(query_curr, (invoice_id,)).fetchone()
            if not curr_row:
                return []
            currency = curr_row[0]
            rows = conn.execute(query_lines, (invoice_id,)).fetchall()
            
        return [
            InvoiceLineItem(
                id=r[0],
                invoice_id=r[1],
                description=r[2],
                amount=Money(r[3], currency),
                kind=LineItemKind(r[4])
            ) for r in rows
        ]


# ============================================================
# LEDGER — APPEND-ONLY
# ============================================================
class LedgerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, entry: LedgerEntry) -> LedgerEntry:
        query = """
            INSERT INTO ledger_entries (customer_id, invoice_id, amount, currency, direction, description)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id, created_at;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (
                entry.customer_id,
                entry.invoice_id,
                entry.amount.to_storage(),
                entry.currency,
                entry.direction.value,
                entry.description
            ))
            row = cursor.fetchone()
        entry.id = row[0]
        # Assuming your LedgerEntry dataclass has a created_at string/datetime field
        if hasattr(entry, 'created_at'):
            entry.created_at = datetime.fromisoformat(row[1]) if isinstance(row[1], str) else row[1]
        return entry

    def list_for_customer(self, customer_id: int) -> list[LedgerEntry]:
        query = """
            SELECT id, customer_id, invoice_id, amount, currency, direction, description 
            FROM ledger_entries WHERE customer_id = ? ORDER BY id ASC;
        """
        with self.db.connect() as conn:
            rows = conn.execute(query, (customer_id,)).fetchall()
        return [
            LedgerEntry(
                id=r[0],
                customer_id=r[1],
                invoice_id=r[2],
                amount=Money(r[3], r[4]),
                currency=r[4],
                direction=LedgerDirection(r[5]),
                description=r[6]
            ) for r in rows
        ]

    def update(self, *args, **kwargs):
        raise NotImplementedError("Ledger is append-only. Post a reversing entry instead.")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Ledger is append-only. Post a reversing entry instead.")


# ============================================================
# PAYMENT ATTEMPTS (Day 3 Groundwork)
# ============================================================
class PaymentAttemptRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        invoice_id: int,
        attempt_no: int,
        status: str,
        failure_reason: Optional[str],
        next_retry_at: Optional[datetime],
    ) -> int:
        query = """
            INSERT INTO payment_attempts (invoice_id, attempt_no, status, failure_reason, next_retry_at, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            RETURNING id;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(query, (
                invoice_id,
                attempt_no,
                status,
                failure_reason,
                next_retry_at.isoformat() if next_retry_at else None
            ))
            attempt_id = cursor.fetchone()[0]
        return attempt_id

    def list_for_invoice(self, invoice_id: int) -> list[dict]:
        query = "SELECT id, invoice_id, attempt_no, status, failure_reason, next_retry_at, created_at FROM payment_attempts WHERE invoice_id = ? ORDER BY attempt_no ASC;"
        with self.db.connect() as conn:
            rows = conn.execute(query, (invoice_id,)).fetchall()
        return [
            {
                "id": r[0],
                "invoice_id": r[1],
                "attempt_no": r[2],
                "status": r[3],
                "failure_reason": r[4],
                "next_retry_at": datetime.fromisoformat(r[5]) if r[5] else None,
                "created_at": r[6]
            } for r in rows
        ]

    def count_for_invoice(self, invoice_id: int) -> int:
        query = "SELECT COUNT(*) FROM payment_attempts WHERE invoice_id = ?;"
        with self.db.connect() as conn:
            row = conn.execute(query, (invoice_id,)).fetchone()
        return row[0]
