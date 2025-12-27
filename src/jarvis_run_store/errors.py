class RunStoreError(Exception):
    pass


class NotFoundError(RunStoreError):
    pass


class ConflictError(RunStoreError):
    pass


class StorageFullError(RunStoreError):
    pass
