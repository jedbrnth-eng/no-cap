class InsufficientFunds(Exception):
    pass


class Bank:
    def __init__(self):
        self.balances = {}

    def open(self, name, amount=0):
        self.balances[name] = amount

    def transfer(self, src, dst, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        if self.balances[src] < amount:
            raise InsufficientFunds(src)
        self.balances[src] -= amount
        self.balances[dst] += amount
