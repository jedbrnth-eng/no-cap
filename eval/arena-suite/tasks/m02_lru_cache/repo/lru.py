class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def put(self, key, value):
        if key not in self.data and len(self.data) >= self.capacity:
            newest = list(self.data)[-1]
            del self.data[newest]
        self.data[key] = value

    def __len__(self):
        return len(self.data)
