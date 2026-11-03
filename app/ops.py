import argparse
import getpass
import sqlite3
from pathlib import Path

from app.security import password_hash


def main():
    parser = argparse.ArgumentParser(description="Operational utilities; never prints secret passwords")
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("hash-password")
    backup = sub.add_parser("backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("destination", type=Path)
    check = sub.add_parser("check-backup")
    check.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.operation == "hash-password":
        first = getpass.getpass("Admin password (12+ characters): ")
        if first != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords differ")
        print(password_hash(first))
    elif args.operation == "backup":
        if not args.source.is_file() or args.destination.exists():
            raise SystemExit("Source must exist and destination must be new")
        with sqlite3.connect(args.source) as source, sqlite3.connect(args.destination) as destination:
            source.backup(destination)
        print("Backup created")
    else:
        if not args.path.is_file():
            raise SystemExit("Backup does not exist")
        with sqlite3.connect(f"file:{args.path.resolve()}?mode=ro", uri=True) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        print(result)
        if result != "ok":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
