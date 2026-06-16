"""
GSTCalculator — Indian Goods & Services Tax.

The rule:
    - If customer_state == seller_state (or seller_state is "")  =>  intra-state
        -> charge CGST + SGST (split equally, e.g. 9% + 9% = 18%)
    - Else  =>  inter-state
        -> charge IGST (e.g. 18%)

Customers without a state code default to IGST (safe choice).
"""

from decimal import Decimal

from billing_engine.money import Money
from billing_engine.taxes.base import TaxCalculator, TaxContext, TaxBreakdown


class GSTCalculator(TaxCalculator):
    def __init__(self, cgst: Decimal, sgst: Decimal, igst: Decimal) -> None:
        # TODO Day 1
        #   - Validate each rate is Decimal in [0, 1].
        #   - Validate cgst + sgst == igst (sanity check on Indian GST setup).
        #   - Store on self.
        raise NotImplementedError("Day 1: implement GSTCalculator.__init__")

    def apply(self, taxable: Money, context: TaxContext) -> TaxBreakdown:
        # TODO Day 1
        #   - Decide intra vs inter-state from context.
        #     intra = bool(context.customer_state) and context.customer_state == context.seller_state
        #   - If intra: components = [("CGST X%", taxable*cgst), ("SGST Y%", taxable*sgst)], total = sum
        #   - Else:     components = [("IGST Z%", taxable*igst)],                            total = igst leg
        raise NotImplementedError("Day 1: implement GSTCalculator.apply")


from decimal import Decimal
from billing_engine.money import Money
from billing_engine.taxes.base import TaxCalculator, TaxContext, TaxBreakdown

class GSTCalculator(TaxCalculator):
    def __init__(self, cgst: Decimal, sgst: Decimal, igst: Decimal):
        if any(isinstance(r, float) for r in (cgst, sgst, igst)):
            raise TypeError("Rates must be Decimals, not floats")
        if not all(Decimal("0") <= r <= Decimal("1") for r in (cgst, sgst, igst)):
            raise ValueError("Rates must be in the range [0, 1]")
        if cgst + sgst != igst:
            raise ValueError("Sanity check failed: CGST + SGST must equal IGST")
            
        self.cgst = cgst
        self.sgst = sgst
        self.igst = igst

    def apply(self, taxable: Money, context: TaxContext) -> TaxBreakdown:
        intra = bool(context.customer_state) and context.customer_state == context.seller_state
        
        if intra:
            cgst_amt = taxable * self.cgst
            sgst_amt = taxable * self.sgst
            components = [
                (f"CGST {self.cgst * 100}%", cgst_amt),
                (f"SGST {self.sgst * 100}%", sgst_amt)
            ]
            total = cgst_amt + sgst_amt
        else:
            igst_amt = taxable * self.igst
            components = [
                (f"IGST {self.igst * 100}%", igst_amt)
            ]
            total = igst_amt
            
        return TaxBreakdown(components=components, total=total)
