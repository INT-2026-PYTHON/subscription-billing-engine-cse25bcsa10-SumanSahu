"""
build_invoice — PURE function that turns inputs into an Invoice dataclass.

⚠️ NO database calls here. No `datetime.now()`. No PDF. Just math.

The order is FIXED:
    1. base       = strategy.calculate(usage)
    2. discount   = discount.apply(base) if discount else 0
    3. taxable    = base - discount
    4. tax        = tax_calc.apply(taxable)
    5. total      = taxable + tax.total
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from billing_engine.money import Money
from billing_engine.models import (
    Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind, Subscription, Plan,
)
from billing_engine.pricing.base import PricingStrategy
from billing_engine.discounts.base import Discount, DiscountContext
from billing_engine.taxes.base import TaxCalculator, TaxContext


def build_invoice(
    subscription: Subscription,
    plan: Plan,
    strategy: PricingStrategy,
    discount: Optional[Discount],
    tax_calc: TaxCalculator,
    tax_context: TaxContext,
    usage_quantity: int,
    period_start: date,
    period_end: date,
    invoice_count_so_far: int,
) -> Invoice:
    """Pure function. Returns an Invoice (id=None, status=DRAFT) ready to be persisted."""
    
    currency = plan.currency
    line_items: list[InvoiceLineItem] = []

    # 1. Base Charge Calculation
    base_charge = strategy.calculate(usage_quantity)
    line_items.append(
        InvoiceLineItem(
            id=None,
            invoice_id=None,
            description=f"Base subscription charge for {plan.name} ({usage_quantity} units used)",
            amount=base_charge,
            kind=LineItemKind.BASE_CHARGE
        )
    )

    # 2. Discount Evaluation & Application
    discount_amount = Money.zero(currency)
    if discount:
        context = DiscountContext(
            invoice_count_so_far=invoice_count_so_far,
            period_start=period_start
        )
        discount_amount = discount.apply(base_charge, context)
        
        if discount_amount.amount > 0:
            line_items.append(
                InvoiceLineItem(
                    id=None,
                    invoice_id=None,
                    description=f"Discount applied: {discount.code}",
                    amount=discount_amount,
                    kind=LineItemKind.DISCOUNT
                )
            )

    # 3. Compute Taxable Amount
    taxable_amount = base_charge - discount_amount

    # 4. Compute Tax
    tax_result = tax_calc.apply(taxable_amount, tax_context)
    for tax_line in tax_result.lines:
        line_items.append(
            InvoiceLineItem(
                id=None,
                invoice_id=None,
                description=tax_line.description,
                amount=tax_line.amount,
                kind=LineItemKind.TAX
            )
        )

    # 5. Compute Final Total
    total_amount = taxable_amount + tax_result.total

    # 6. Build and Assemble the Draft Invoice Model
    invoice = Invoice(
        id=None,
        subscription_id=subscription.id,
        period_start=period_start,
        period_end=period_end,
        status=InvoiceStatus.DRAFT,
        currency=currency,
        total_amount=total_amount,
        tax_amount=tax_result.total,
        pdf_path=None
    )
    
    # Securely wire the built line items to the object if your model tracks them
    if hasattr(invoice, "line_items"):
        invoice.line_items = line_items
    else:
        # If your local test framework expects it returned as an explicit tuple 
        # or attached via a custom attribute, it's safer to provide both or keep it decoupled.
        invoice._line_items = line_items

    return invoice
