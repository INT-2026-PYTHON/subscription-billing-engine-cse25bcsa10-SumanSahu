"""
FlatRate — same charge every period regardless of usage.

Example: ₹999/month subscription, no matter how much the customer uses.
"""

from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy


class FlatRate(PricingStrategy):
    """Charges a fixed amount every billing period."""

    def __init__(self, amount: Money) -> None:
        # TODO Day 1
        raise NotImplementedError("Day 1: implement FlatRate.__init__")

    def calculate(self, quantity: int) -> Money:
        # TODO Day 1
        raise NotImplementedError("Day 1: implement FlatRate.calculate")


from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy

class FlatRate(PricingStrategy):
    def __init__(self, amount: Money):
        if not isinstance(amount, Money):
            raise TypeError("Amount must be a Money instance")
        if amount.is_negative():
            raise ValueError("Amount cannot be negative")
        self.amount = amount

    def calculate(self, quantity: int) -> Money:
        return self.amount
