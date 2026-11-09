class Inventory:
    def __init__(self):
        self._stock = {}

    def add(self, sku, qty):
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def remove(self, sku, qty):
        self._stock[sku] = self._stock.get(sku, 0) - qty

    def count(self, sku):
        return self._stock.get(sku, 0)

    def items(self):
        return sorted(self._stock)
