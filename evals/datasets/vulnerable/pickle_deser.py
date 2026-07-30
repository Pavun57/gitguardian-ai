import pickle


def restore_session(blob):
    return pickle.loads(blob)
