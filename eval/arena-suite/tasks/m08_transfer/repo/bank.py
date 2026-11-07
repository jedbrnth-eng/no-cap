class InsufficientFunds(Exception):
    pass


class Bank:
    def __init__(self):
        self.balances = {}

    def open(self, name, amount=0):
        self.balances[name] = amount

    def transfer(self, src, dst, amount):
        self.balances[dst] += amount
        self.balances[src] -= amount
