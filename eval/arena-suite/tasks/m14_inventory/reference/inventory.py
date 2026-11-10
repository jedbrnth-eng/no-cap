class Inventory:
    def __init__(self):
        self._stock = {}

    @staticmethod
    def _check(qty):
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise ValueError("qty must be a positive integer")

    def add(self, sku, qty):
        self._check(qty)
        self._stock[sku] = self._stock.get(sku, 0) + qty

    def remove(self, sku, qty):
        self._check(qty)
        have = self._stock.get(sku, 0)
        if qty > have:
            raise ValueError("not enough stock")
        if qty == have:
            del self._stock[sku]
        else:
            self._stock[sku] = have - qty

    def count(self, sku):
        return self._stock.get(sku, 0)

    def items(self):
        return sorted(self._stock)
