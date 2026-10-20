"""SQLite transaction boundary. One local API instance; not a distributed database."""
import contextlib
import hashlib
import json
import sqlite3
import uuid
from . import clock

SCHEMA_VERSION = 1

def now():
    return clock.utcnow().isoformat(timespec='microseconds').replace('+00:00', 'Z')

def uid(prefix):
    return prefix + '_' + uuid.uuid4().hex

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def connect(path):
    db = sqlite3.connect(str(path), isolation_level=None, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=15000')
    return db

@contextlib.contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise

def initialize(path):
    db = connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
    INSERT OR IGNORE INTO metadata VALUES ('revision',0);
    CREATE TABLE IF NOT EXISTS actors(
      actor_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, roles TEXT NOT NULL,
      sites TEXT NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)));
    CREATE TABLE IF NOT EXISTS sites(site_id TEXT PRIMARY KEY, name TEXT NOT NULL, access_scope TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS items(item_id TEXT PRIMARY KEY, base_unit TEXT NOT NULL,
      expiry_required INTEGER NOT NULL, conversion_version TEXT NOT NULL, quality_policy TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sources(source_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
      authoritative_fields TEXT NOT NULL, permitted_use TEXT NOT NULL, enabled INTEGER NOT NULL,
      allowed_sites TEXT NOT NULL, max_age_seconds INTEGER NOT NULL, version INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY, item_id TEXT NOT NULL REFERENCES items,
      expiry_date TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS balances(
      site_id TEXT NOT NULL REFERENCES sites, batch_id TEXT NOT NULL REFERENCES batches,
      usable INTEGER NOT NULL DEFAULT 0 CHECK(usable>=0),
      quarantined INTEGER NOT NULL DEFAULT 0 CHECK(quarantined>=0),
      damaged INTEGER NOT NULL DEFAULT 0 CHECK(damaged>=0),
      rejected INTEGER NOT NULL DEFAULT 0 CHECK(rejected>=0),
      expired INTEGER NOT NULL DEFAULT 0 CHECK(expired>=0),
      reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0 AND reserved<=usable),
      version INTEGER NOT NULL DEFAULT 0, last_observed_at TEXT, last_posted_at TEXT,
      last_physical_count_at TEXT, PRIMARY KEY(site_id,batch_id));
    CREATE TABLE IF NOT EXISTS events(
      sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,
      schema_version TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES sources,
      site_id TEXT NOT NULL REFERENCES sites, item_id TEXT NOT NULL REFERENCES items,
      batch_id TEXT NOT NULL REFERENCES batches, event_type TEXT NOT NULL,
      quantity INTEGER NOT NULL CHECK(quantity>0), base_unit TEXT NOT NULL,
      occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, expiry_date TEXT NOT NULL,
      source_ref TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES actors,
      payload_hash TEXT NOT NULL, correlation_id TEXT NOT NULL,
      request_id TEXT, shipment_id TEXT, receipt_part_id TEXT);
    CREATE INDEX IF NOT EXISTS events_scope ON events(site_id,sequence);
    CREATE TABLE IF NOT EXISTS previews(
      preview_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors,
      source_id TEXT NOT NULL REFERENCES sources, content_hash TEXT NOT NULL,
      revision INTEGER NOT NULL, created_at TEXT NOT NULL, result TEXT);
    CREATE TABLE IF NOT EXISTS requests(
      request_id TEXT PRIMARY KEY, creator_id TEXT NOT NULL REFERENCES actors,
      source_site_id TEXT NOT NULL REFERENCES sites, destination_site_id TEXT NOT NULL REFERENCES sites,
      item_id TEXT NOT NULL REFERENCES items, quantity INTEGER NOT NULL CHECK(quantity>0),
      status TEXT NOT NULL CHECK(status IN ('DRAFT','SUBMITTED','APPROVED','REJECTED','CANCELLED','CLOSED')),
      version INTEGER NOT NULL, input_revision INTEGER NOT NULL,
      snapshot_id TEXT, policy_version TEXT NOT NULL,
      approver_id TEXT REFERENCES actors, reason TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS decisions(decision_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests,
      actor_id TEXT NOT NULL REFERENCES actors, action TEXT NOT NULL, reason TEXT NOT NULL,
      before_version INTEGER NOT NULL, after_version INTEGER NOT NULL, input_revision INTEGER NOT NULL,
      policy_version TEXT NOT NULL, server_time TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reservations(
      request_id TEXT NOT NULL REFERENCES requests, batch_id TEXT NOT NULL REFERENCES batches,
      quantity INTEGER NOT NULL CHECK(quantity>=0), dispatched INTEGER NOT NULL DEFAULT 0 CHECK(dispatched>=0),
      PRIMARY KEY(request_id,batch_id));
    CREATE TABLE IF NOT EXISTS shipments(shipment_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests,
      status TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS shipment_lines(
      shipment_id TEXT NOT NULL REFERENCES shipments, batch_id TEXT NOT NULL REFERENCES batches,
      quantity INTEGER NOT NULL CHECK(quantity>0), received INTEGER NOT NULL DEFAULT 0 CHECK(received>=0 AND received<=quantity),
      PRIMARY KEY(shipment_id,batch_id));
    CREATE TABLE IF NOT EXISTS receipt_parts(receipt_part_id TEXT PRIMARY KEY, shipment_id TEXT NOT NULL REFERENCES shipments,
      actor_id TEXT NOT NULL REFERENCES actors, payload TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS idempotency(
      actor_id TEXT NOT NULL REFERENCES actors, operation TEXT NOT NULL, key TEXT NOT NULL,
      payload_hash TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(actor_id,operation,key));
    CREATE TABLE IF NOT EXISTS snapshots(snapshot_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors,
      sites TEXT NOT NULL, revision INTEGER NOT NULL, content_hash TEXT NOT NULL,
      payload TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS physical_counts(count_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites,
      batch_id TEXT NOT NULL REFERENCES batches, counted_quantity INTEGER NOT NULL CHECK(counted_quantity>=0),
      actor_id TEXT NOT NULL REFERENCES actors, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, source_ref TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS demand(
      record_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites, item_id TEXT NOT NULL REFERENCES items,
      period TEXT NOT NULL, payload TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES actors,
      recorded_at TEXT NOT NULL, UNIQUE(site_id,item_id,period));
    CREATE TABLE IF NOT EXISTS observations(
      event_id TEXT PRIMARY KEY, site_id TEXT NOT NULL REFERENCES sites,
      actor_id TEXT NOT NULL REFERENCES actors, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
      recorded_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(
      sequence INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT NOT NULL, action TEXT NOT NULL,
      object_ref TEXT NOT NULL, sites TEXT NOT NULL, outcome TEXT NOT NULL, details TEXT NOT NULL,
      correlation_id TEXT NOT NULL, server_time TEXT NOT NULL, previous_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
    CREATE TRIGGER IF NOT EXISTS snapshots_no_update BEFORE UPDATE ON snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshots'); END;
    CREATE TRIGGER IF NOT EXISTS snapshots_no_delete BEFORE DELETE ON snapshots BEGIN SELECT RAISE(ABORT,'immutable snapshots'); END;
    CREATE TRIGGER IF NOT EXISTS decisions_no_update BEFORE UPDATE ON decisions BEGIN SELECT RAISE(ABORT,'immutable decisions'); END;
    CREATE TRIGGER IF NOT EXISTS decisions_no_delete BEFORE DELETE ON decisions BEGIN SELECT RAISE(ABORT,'immutable decisions'); END;
    CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable events'); END;
    CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable events'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
    CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'immutable audit'); END;
    ''')
    with transaction(db):
        db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (?,?)',(SCHEMA_VERSION,now()))
        for site in ('DEMO_A','DEMO_B'):
            db.execute('INSERT OR IGNORE INTO sites VALUES (?,?,?)',(site,'Fictional '+site,site))
        for item, unit in [('WATER_1L','BOTTLE'),('RATIONS_DRY','PACK'),('BANDAGE_STD','PACK')]:
            db.execute('INSERT OR IGNORE INTO items VALUES (?,?,?,?,?)',(item,unit,1,'base-v1','QA_REQUIRED'))
        db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?,?)',
                   ('SIH_SYNTHETIC_CSV','SIH fictional fixture','inventory events',
                    'SYNTHETIC_DEMONSTRATION_ONLY',1,canonical(['DEMO_A','DEMO_B']),86400,1))
        db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?,?,?,?)',
                   ('WORKFLOW','Setu synthetic workflow','authorized business events',
                    'SYNTHETIC_DEMONSTRATION_ONLY',1,canonical(['DEMO_A','DEMO_B']),86400,1))
    db.close()

def revision(db):
    return db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]

def bump(db):
    db.execute("UPDATE metadata SET value=value+1 WHERE key='revision'")
    return revision(db)

def audit(db, actor, action, object_ref, sites, correlation, details=None, outcome='ALLOW'):
    previous = db.execute('SELECT entry_hash FROM audit ORDER BY sequence DESC LIMIT 1').fetchone()
    entry = dict(actor_id=actor, action=action, object_ref=object_ref, sites=sorted(sites),
                 outcome=outcome, details=details or {}, correlation_id=correlation,
                 server_time=now(), previous_hash=previous[0] if previous else '0'*64)
    db.execute('''INSERT INTO audit(actor_id,action,object_ref,sites,outcome,details,correlation_id,
                  server_time,previous_hash,entry_hash) VALUES (?,?,?,?,?,?,?,?,?,?)''',
               (actor,action,object_ref,canonical(entry['sites']),outcome,canonical(entry['details']),
                correlation,entry['server_time'],entry['previous_hash'],digest(entry)))
