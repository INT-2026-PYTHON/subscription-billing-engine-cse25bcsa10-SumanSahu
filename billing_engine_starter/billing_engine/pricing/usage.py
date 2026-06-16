"""
UsageBased — pay per unit consumed.

Example: ₹0.50 per API call. Customer makes 1200 calls => charge = ₹600.
"""

from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy


class UsageBased(PricingStrategy):
    """Charges `unit_price * quantity`."""

    def __init__(self, unit_price: Money) -> None:
        # TODO Day 1
        raise NotImplementedError("Day 1: implement UsageBased.__init__")

    def calculate(self, quantity: int) -> Money:
        # TODO Day 1
        raise NotImplementedError("Day 1: implement UsageBased.calculate")


from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy

class UsageBased(PricingStrategy):
    def __init__(self, unit_price: Money):
        if not isinstance(unit_price, Money):
            raise TypeError("Unit price must be a Money instance")
        if unit_price.is_negative():
            raise ValueError("Unit price cannot be negative")
        self.unit_price = unit_price

    def calculate(self, quantity: int) -> Money:
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        return self.unit_price * quantity
