"""
VATCalculator — single-rate VAT (e.g. 19% in Germany).
"""

from decimal import Decimal

from billing_engine.money import Money
from billing_engine.taxes.base import TaxCalculator, TaxContext, TaxBreakdown


class VATCalculator(TaxCalculator):
    def __init__(self, rate: Decimal) -> None:
        # TODO Day 1
        #   - Validate 0 <= rate <= 1.
        #   - Reject float.
        #   - Store on self.
        raise NotImplementedError("Day 1: implement VATCalculator.__init__")

    def apply(self, taxable: Money, context: TaxContext) -> TaxBreakdown:
        # TODO Day 1
        #   - vat = taxable * self.rate
        #   - Return TaxBreakdown with one component (f"VAT {percent}%", vat) and total = vat.
        #   - Tip: format the rate as a percentage cleanly.
        raise NotImplementedError("Day 1: implement VATCalculator.apply")


from decimal import Decimal
from billing_engine.money import Money
from billing_engine.taxes.base import TaxCalculator, TaxContext, TaxBreakdown

class VATCalculator(TaxCalculator):
    def __init__(self, rate: Decimal):
        if isinstance(rate, float):
            raise TypeError("Rate must be a Decimal, not a float")
        if not Decimal("0") <= rate <= Decimal("1"):
            raise ValueError("Rate must be in the range [0, 1]")
        self.rate = rate

    def apply(self, taxable: Money, context: TaxContext) -> TaxBreakdown:
        vat_amt = taxable * self.rate
        pct = self.rate * Decimal("100")
        label = f"VAT {pct}%"
        return TaxBreakdown(components=[(label, vat_amt)], total=vat_amt)
