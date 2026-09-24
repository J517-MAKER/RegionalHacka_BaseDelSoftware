from services import store


def get_history():
    return sorted(store.logs, key=lambda item:item.timestamp, reverse=True)
