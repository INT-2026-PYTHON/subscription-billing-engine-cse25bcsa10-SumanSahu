"""
BillingCycle — finds due subscriptions, generates invoices, posts ledger DEBITs,
advances the subscription period. Must be IDEMPOTENT (safe to run twice).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import sqlite3
from typing import Callable, Optional

from billing_engine.db import (
    Database,
    CustomerRepository, PlanRepository, SubscriptionRepository,
    UsageRecordRepository, InvoiceRepository, InvoiceLineItemRepository,
    LedgerRepository,
)
from billing_engine.models import Subscription, SubscriptionStatus
# Note: Ensure build_invoice is imported from your pure pipeline module
from billing_engine.billing.pipeline import build_invoice


@dataclass
class BillingResult:
    invoices_created: int
    invoices_skipped_duplicate: int
    trials_activated: int


class BillingCycle:
    """Day-3 deliverable. Day-4 stretch: add `upgrade_subscription(...)`."""

    def __init__(
        self,
        db: Database,
        customer_repo: CustomerRepository,
        plan_repo: PlanRepository,
        subscription_repo: SubscriptionRepository,
        usage_repo: UsageRecordRepository,
        invoice_repo: InvoiceRepository,
        line_item_repo: InvoiceLineItemRepository,
        ledger_repo: LedgerRepository,
        strategy_factory: Callable,    # given a Plan, returns a PricingStrategy
        discount_factory: Callable,    # given a discount_id or None, returns a Discount or None
        tax_factory: Callable,         # given a Customer, returns (TaxCalculator, TaxContext)
    ) -> None:
        self.db = db
        self.customer_repo = customer_repo
        self.plan_repo = plan_repo
        self.subscription_repo = subscription_repo
        self.usage_repo = usage_repo
        self.invoice_repo = invoice_repo
        self.line_item_repo = line_item_repo
        self.ledger_repo = ledger_repo
        self.strategy_factory = strategy_factory
        self.discount_factory = discount_factory
        self.tax_factory = tax_factory

    # --------------------------------------------------------
    def run(self, as_of: date) -> BillingResult:
        """Bill all subscriptions whose current period ends on or before `as_of`."""
        invoices_created = 0
        invoices_skipped_duplicate = 0
        trials_activated = 0

        # 1. Trial Activation Loop
        # Check all subscriptions to see if their trial has expired as of today
        for sub in self.subscription_repo.list_all():
            if sub.status == SubscriptionStatus.TRIAL and sub.trial_end and sub.trial_end <= as_of:
                self.subscription_repo.update_status(sub.id, SubscriptionStatus.ACTIVE)
                trials_activated += 1

        # 2. Due-Subscription Discovery
        due_subscriptions = self.subscription_repo.get_due_for_billing(as_of)

        # 3. Process each due subscription inside its own atomic transaction boundary
        for sub in due_subscriptions:
            try:
                # Wrap all writes inside a single database transaction context
                with self.db.transaction():
                    # Look up dependency records
                    customer = self.customer_repo.get_by_id(sub.customer_id)
                    plan = self.plan_repo.get_by_id(sub.plan_id)
                    usage = self.usage_repo.get_for_period(sub.id, sub.current_period_start, sub.current_period_end)

                    # Initialize factories for pure pipeline domain logic
                    strategy = self.strategy_factory(plan)
                    discount = self.discount_factory(sub.discount_id) if sub.discount_id else None
                    tax_calculator, tax_context = self.tax_factory(customer)

                    # Generate pure domain entity representation of the Invoice
                    invoice = build_invoice(
                        subscription=sub,
                        plan=plan,
                        customer=customer,
                        usage_records=usage,
                        pricing_strategy=strategy,
                        discount=discount,
                        tax_calculator=tax_calculator,
                        tax_context=tax_context,
                        as_of=as_of
                    )

                    # Persist Invoice and its associated Line Items
                    invoice_id = self.invoice_repo.add(invoice)
                    for line in invoice.line_items:
                        self.line_item_repo.add(invoice_id, line)

                    # Post Ledger DEBIT transaction
                    self.ledger_repo.post_debit(
                        customer_id=sub.customer_id,
                        amount=invoice.total_amount,
                        reference_id=invoice_id
                    )

                    # Advance subscription tracking window forward
                    self.subscription_repo.advance_period(sub.id)
                    
                    invoices_created += 1

            except sqlite3.IntegrityError:
                # Triggers on schema constraint UNIQUE(subscription_id, period_start)
                # Safely catches double runs on the same date block, providing idempotency
                invoices_skipped_duplicate += 1

        return BillingResult(
            invoices_created=invoices_created,
            invoices_skipped_duplicate=invoices_skipped_duplicate,
            trials_activated=trials_activated
        )

    # --------------------------------------------------------
    def upgrade_subscription(self, subscription_id: int, new_plan_id: int, switch_date: date) -> None:
        """Mid-cycle upgrade — applies proration credits/charges and changes plans atomically."""
        with self.db.transaction():
            sub = self.subscription_repo.get(subscription_id)
            if not sub:
                raise ValueError(f"Subscription {subscription_id} not found")
            
            customer = self.customer_repo.get(sub.customer_id)
            old_plan = self.plan_repo.get(sub.plan_id)
            new_plan = self.plan_repo.get(new_plan_id)
            
            # Resolve prices (assuming standard base tier or simple base pricing strategy lookup)
            old_strategy = self.strategy_factory(old_plan)
            new_strategy = self.strategy_factory(new_plan)
            
            # Base price before volume/usage additions
            old_base_price = old_strategy.calculate_base_price() 
            new_base_price = new_strategy.calculate_base_price()
            
            tax_calculator, tax_context = self.tax_factory(customer)
            
            # Compute proration split
            from billing_engine.billing.proration import compute_proration
            proration = compute_proration(
                old_base_price, new_base_price,
                sub.current_period_start, sub.current_period_end,
                switch_date, tax_calculator, tax_context
            )
            
            # Construct line items for the proration invoice
            from billing_engine.models import Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind
            
            currency = old_plan.currency
            net_charge = proration.charge_amount - proration.credit_amount
            net_tax = proration.charge_tax - proration.credit_tax
            total_amount = net_charge + net_tax
            
            proration_invoice = Invoice(
                id=None,
                subscription_id=sub.id,
                period_start=switch_date,
                period_end=sub.current_period_end,
                status=InvoiceStatus.UNPAID,
                currency=currency,
                total_amount=total_amount,
                tax_amount=net_tax,
                pdf_path=None
            )
            
            invoice_id = self.invoice_repo.add(proration_invoice)
            
            # Save Credit & Charge Line items
            self.line_item_repo.add(InvoiceLineItem(
                id=None, invoice_id=invoice_id, kind=LineItemKind.CREDIT,
                description=f"Prorated unused time on {old_plan.name}", amount=-proration.credit_amount
            ))
            self.line_item_repo.add(InvoiceLineItem(
                id=None, invoice_id=invoice_id, kind=LineItemKind.BASE,
                description=f"Prorated remaining time on {new_plan.name}", amount=proration.charge_amount
            ))
            
            # Post matching Ledger DEBIT
            self.ledger_repo.post_debit(
                customer_id=sub.customer_id,
                amount=total_amount,
                reference_id=invoice_id
            )
            
            # Mutate state safely within the transaction block boundary
            self.subscription_repo.update_plan(sub.id, new_plan_id)
