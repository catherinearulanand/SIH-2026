"""Opaque demo bearer tokens, provisioned locally; identity never comes from request JSON."""
import hashlib
import json
import secrets
from dataclasses import dataclass
from .db import transaction

ROLES = {'storekeeper','planner','approver','dispatcher','receiver','qa','custodian','auditor','admin'}

class DomainError(Exception):
    def __init__(self, code, message, status=422, current_version=None, field_errors=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.current_version, self.field_errors = current_version, field_errors or []

@dataclass(frozen=True)
class Actor:
    actor_id: str
    roles: frozenset
    sites: frozenset

    def require(self, roles=(), sites=()):
        if roles and not self.roles.intersection(roles):
            raise DomainError('FORBIDDEN','Insufficient role authority',403)
        if not set(sites).issubset(self.sites):
            raise DomainError('FORBIDDEN','Site scope denied',403)


def provision(db, actor_id, roles, sites):
    if not actor_id or len(actor_id)>80 or not roles or not set(roles)<=ROLES:
        raise ValueError('Invalid actor or roles')
    known = {r[0] for r in db.execute('SELECT site_id FROM sites')}
    if not sites or not set(sites)<=known:
        raise ValueError('Unknown or empty site scope')
    token = secrets.token_urlsafe(40)
    with transaction(db):
        db.execute('''INSERT INTO actors VALUES (?,?,?,?,1) ON CONFLICT(actor_id) DO UPDATE SET
                   token_hash=excluded.token_hash,roles=excluded.roles,sites=excluded.sites,active=1''',
                   (actor_id,hashlib.sha256(token.encode()).hexdigest(),json.dumps(sorted(roles)),json.dumps(sorted(sites))))
    return token


def authenticate(db, token):
    if not isinstance(token,str) or not 20 <= len(token) <= 200:
        raise DomainError('UNAUTHENTICATED','Valid bearer token required',401)
    row = db.execute('SELECT * FROM actors WHERE token_hash=? AND active=1',
                     (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row:
        raise DomainError('UNAUTHENTICATED','Valid bearer token required',401)
    return Actor(row['actor_id'],frozenset(json.loads(row['roles'])),frozenset(json.loads(row['sites'])))
