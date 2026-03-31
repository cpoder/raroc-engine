"""JSON file-based storage for customers and API keys."""

import fcntl
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel


class Customer(BaseModel):
    id: str
    email: str
    organization: str = ""
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""
    created_at: str = ""
    status: str = "active"


class APIKey(BaseModel):
    key: str
    customer_id: str
    created_at: str = ""
    expires_at: str = ""
    active: bool = True
    last_used: str = ""


class JsonStorage:
    def __init__(self, data_dir: str | None = None):
        self.data_dir = Path(data_dir or os.environ.get("RAROC_DATA_DIR", "/app/data"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._customers_path = self.data_dir / "customers.json"
        self._keys_path = self.data_dir / "keys.json"

    def _read_json(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        with open(path, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _write_json(self, path: Path, data: list[dict]):
        with open(path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2)
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def load_customers(self) -> list[Customer]:
        return [Customer(**c) for c in self._read_json(self._customers_path)]

    def save_customers(self, customers: list[Customer]):
        self._write_json(self._customers_path, [c.model_dump() for c in customers])

    def load_keys(self) -> list[APIKey]:
        return [APIKey(**k) for k in self._read_json(self._keys_path)]

    def save_keys(self, keys: list[APIKey]):
        self._write_json(self._keys_path, [k.model_dump() for k in keys])

    def get_customer(self, customer_id: str) -> Optional[Customer]:
        for c in self.load_customers():
            if c.id == customer_id:
                return c
        return None

    def find_customer_by_stripe(self, stripe_customer_id: str) -> Optional[Customer]:
        for c in self.load_customers():
            if c.stripe_customer_id == stripe_customer_id:
                return c
        return None

    def find_customer_by_email(self, email: str) -> Optional[Customer]:
        for c in self.load_customers():
            if c.email.lower() == email.lower():
                return c
        return None

    def add_customer(
        self,
        email: str,
        organization: str = "",
        stripe_customer_id: str = "",
        stripe_subscription_id: str = "",
    ) -> Customer:
        customers = self.load_customers()
        # Idempotent: return existing if stripe_customer_id matches
        if stripe_customer_id:
            for c in customers:
                if c.stripe_customer_id == stripe_customer_id:
                    return c
        customer = Customer(
            id=secrets.token_hex(16),
            email=email,
            organization=organization,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="active",
        )
        customers.append(customer)
        self.save_customers(customers)
        return customer

    def add_key(self, customer_id: str, expires_days: int = 365) -> APIKey:
        keys = self.load_keys()
        # Check if customer already has an active key
        for k in keys:
            if k.customer_id == customer_id and k.active:
                return k
        now = datetime.now(timezone.utc)
        key = APIKey(
            key="rk_" + secrets.token_hex(16),
            customer_id=customer_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(days=expires_days)).isoformat(),
            active=True,
        )
        keys.append(key)
        self.save_keys(keys)
        return key

    def get_key(self, key_str: str) -> Optional[APIKey]:
        for k in self.load_keys():
            if k.key == key_str:
                return k
        return None

    def validate_key(self, key_str: str) -> Optional[APIKey]:
        """Return the key if it exists, is active, and not expired."""
        k = self.get_key(key_str)
        if not k or not k.active:
            return None
        if k.expires_at:
            expires = datetime.fromisoformat(k.expires_at)
            if expires < datetime.now(timezone.utc):
                return None
        return k

    def revoke_key(self, key_str: str) -> bool:
        keys = self.load_keys()
        for k in keys:
            if k.key == key_str:
                k.active = False
                self.save_keys(keys)
                return True
        return False

    def touch_key(self, key_str: str):
        keys = self.load_keys()
        for k in keys:
            if k.key == key_str:
                k.last_used = datetime.now(timezone.utc).isoformat()
                self.save_keys(keys)
                return

    def get_keys_for_customer(self, customer_id: str) -> list[APIKey]:
        return [k for k in self.load_keys() if k.customer_id == customer_id]

    def list_customers_with_keys(self) -> list[dict]:
        customers = self.load_customers()
        keys = self.load_keys()
        keys_by_customer: dict[str, list[dict]] = {}
        for k in keys:
            keys_by_customer.setdefault(k.customer_id, []).append(k.model_dump())
        result = []
        for c in customers:
            entry = c.model_dump()
            entry["keys"] = keys_by_customer.get(c.id, [])
            result.append(entry)
        return result
