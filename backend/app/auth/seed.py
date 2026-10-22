# backend/app/auth/seed.py
"""Sample clients and users (spec §2.4). Run from backend/: python -m app.auth.seed"""
import argparse

from app.auth.passwords import hash_password
from app.settings import Settings
from app.store import AppUser, Client, Connection, Store

CLIENTS = [("NovaBank", "novabank"), ("Bharat Finserv", "bharat")]
USERS = [   # username, display name, client code (None = platform admin), default password
    ("admin", "Platform Admin", None, "admin123"),
    ("nova.analyst", "Nova Analyst", "novabank", "nova123"),
    ("bharat.analyst", "Bharat Analyst", "bharat", "bharat123"),
]


def seed(store: Store, admin_password: str | None = None, client_password: str | None = None) -> list[str]:
    lines = []
    with store.session() as s:
        clients = {}
        for name, code in CLIENTS:
            client = s.query(Client).filter_by(code=code).first()
            if client is None:
                client = Client(name=name, code=code)
                s.add(client)
                s.flush()
                lines.append(f"created client {name}")
            clients[code] = client
        for username, display, code, default in USERS:
            if s.query(AppUser).filter_by(username=username).first():
                lines.append(f"user {username} exists; password left unchanged")
                continue
            password = (admin_password if code is None else client_password) or default
            s.add(AppUser(username=username, display_name=display, password_hash=hash_password(password),
                          role="admin" if code is None else "client",
                          client_id=clients[code].id if code else None))
            lines.append(f"created user {username} / {password}")
        for client in clients.values():
            has_one = s.query(Connection).filter_by(client_id=client.id).first()
            orphan = s.query(Connection).filter_by(name=client.name, client_id=None).first()
            if orphan and not has_one:
                orphan.client_id = client.id
                lines.append(f"attached connection {orphan.name} to {client.name}")
        s.commit()
    return lines


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create the sample clients and users.")
    parser.add_argument("--admin-password")
    parser.add_argument("--client-password")
    args = parser.parse_args(argv)
    settings = Settings()
    for line in seed(Store(settings.db_url), args.admin_password, args.client_password):
        print(line)
    print("These are sample logins for a proof of concept. Change them before showing the app to anyone else.")


if __name__ == "__main__":
    main()
