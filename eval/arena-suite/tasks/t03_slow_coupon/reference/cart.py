class Cart:
    def __init__(self):
        self.lines = []
        self.coupon = 0

    def add(self, name, price, qty=1):
        self.lines.append((name, price, qty))

    def apply_coupon(self, amount):
        self.coupon = amount

    def total(self):
        subtotal = sum(price * qty for _name, price, qty in self.lines)
        return max(0, subtotal - self.coupon)
