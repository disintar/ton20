def chunks(data, size=1000):
    for i in range(0, len(data), size):
        yield data[i:i + size]