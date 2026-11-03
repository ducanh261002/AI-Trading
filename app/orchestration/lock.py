class WorkerLock:
    """Hold one OS file lock per database; released automatically on process death."""
    def __init__(self, database_path):
        self.path = str(database_path) + ".agents.lock"
        self.file = None

    def acquire(self):
        import os
        self.file = open(self.path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.file.seek(0, 2)
                if self.file.tell() == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("Another agent worker already owns this database; use one backend process") from exc

    def release(self):
        if self.file:
            self.file.close()
            self.file = None
