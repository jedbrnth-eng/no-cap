class Cart:
    def __init__(self):
        self.lines = []
        self.coupon = 0

    def add(self, name, price, qty=1):
        self.lines.append((name, price, qty))

    def apply_coupon(self, amount):
        self.coupon = amount

    def total(self):
        total = 0
        for _name, price, qty in self.lines:
            total += price * qty - self.coupon
        return total
