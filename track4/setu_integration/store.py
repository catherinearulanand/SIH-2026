"""Track 4 storage. It is deliberately separate from the Track 1 authority database."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime,timezone
from .contracts import canonical,digest,ContractError


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def connect(path):
    db=sqlite3.connect(str(path),isolation_level=None,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA busy_timeout=15000')
    return db


@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield;db.commit()
    except BaseException:
        db.rollback();raise


def initialize(path):
    db=connect(path)
    try:
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=FULL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS recommendations(
          recommendation_id TEXT PRIMARY KEY,creator_id TEXT NOT NULL,sites TEXT NOT NULL,
          snapshot_id TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,input_revision INTEGER NOT NULL,
          forecast_run_id TEXT NOT NULL,plan_id TEXT NOT NULL,graph_version TEXT NOT NULL,
          scenario_id TEXT NOT NULL,constraints_version TEXT NOT NULL,source_site_id TEXT NOT NULL,
          destination_site_id TEXT NOT NULL,item_id TEXT NOT NULL,proposed_quantity INTEGER NOT NULL,
          solver_status TEXT NOT NULL,warnings TEXT NOT NULL,explanation TEXT NOT NULL,
          evidence_digest TEXT NOT NULL,record_digest TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS request_links(
          recommendation_id TEXT PRIMARY KEY REFERENCES recommendations,request_id TEXT UNIQUE NOT NULL,
          actor_id TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS idempotency(
          actor_id TEXT NOT NULL,operation TEXT NOT NULL,key TEXT NOT NULL,payload_hash TEXT NOT NULL,
          result TEXT NOT NULL,PRIMARY KEY(actor_id,operation,key));
        CREATE TABLE IF NOT EXISTS audit_mirror(
          track1_sequence INTEGER PRIMARY KEY,payload TEXT NOT NULL,payload_digest TEXT NOT NULL,
          previous_mirror_hash TEXT NOT NULL,mirror_hash TEXT NOT NULL UNIQUE,mirrored_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT OR IGNORE INTO metadata VALUES ('track1_audit_cursor','0');
        CREATE TRIGGER IF NOT EXISTS recommendations_no_update BEFORE UPDATE ON recommendations
          BEGIN SELECT RAISE(ABORT,'immutable recommendations'); END;
        CREATE TRIGGER IF NOT EXISTS recommendations_no_delete BEFORE DELETE ON recommendations
          BEGIN SELECT RAISE(ABORT,'immutable recommendations'); END;
        CREATE TRIGGER IF NOT EXISTS audit_mirror_no_update BEFORE UPDATE ON audit_mirror
          BEGIN SELECT RAISE(ABORT,'immutable audit mirror'); END;
        CREATE TRIGGER IF NOT EXISTS audit_mirror_no_delete BEFORE DELETE ON audit_mirror
          BEGIN SELECT RAISE(ABORT,'immutable audit mirror'); END;
        ''')
    finally:
        db.close()


def save_recommendation(db,actor,data):
    ident='rec_'+uuid.uuid4().hex;created=now()
    record={**data,'recommendation_id':ident,'creator_id':actor['actor_id'],'sites':sorted(actor['sites']),'created_at':created}
    record_digest=digest(record)
    db.execute('''INSERT INTO recommendations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(
        ident,actor['actor_id'],canonical(sorted(actor['sites'])),data['snapshot_id'],data['snapshot_sha256'],data['input_revision'],
        data['forecast_run_id'],data['plan_id'],data['graph_version'],data['scenario_id'],data['constraints_version'],
        data['source_site_id'],data['destination_site_id'],data['item_id'],data['proposed_quantity'],data['solver_status'],
        canonical(data['warnings']),canonical(data['explanation']),data['evidence_digest'],record_digest,created))
    return get_recommendation(db,ident,actor)


def get_recommendation(db,ident,actor):
    row=db.execute('SELECT * FROM recommendations WHERE recommendation_id=?',(ident,)).fetchone()
    if not row:
        raise ContractError('NOT_FOUND','Recommendation not found',404)
    result=dict(row);sites=set(json.loads(result.pop('sites')))
    if not sites<=set(actor['sites']):
        raise ContractError('NOT_FOUND','Recommendation not found',404)
    result['warnings']=json.loads(result['warnings']);result['explanation']=json.loads(result['explanation'])
    return result


def idempotent(db,actor_id,operation,key,payload,action):
    if not isinstance(key,str) or not 1<=len(key)<=128:
        raise ContractError('INVALID_INPUT','Idempotency-Key must be 1..128 characters')
    payload_hash=digest(payload)
    with transaction(db):
        old=db.execute('SELECT * FROM idempotency WHERE actor_id=? AND operation=? AND key=?',(actor_id,operation,key)).fetchone()
        if old:
            if old['payload_hash']!=payload_hash:
                raise ContractError('IDEMPOTENCY_CONFLICT','Key was used for a different payload',409)
            return json.loads(old['result']),True
        result=action()
        db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?)',(actor_id,operation,key,payload_hash,canonical(result)))
        return result,False


def mirror_records(db,records):
    added=0
    with transaction(db):
        previous=db.execute('SELECT mirror_hash FROM audit_mirror ORDER BY track1_sequence DESC LIMIT 1').fetchone()
        previous=previous[0] if previous else '0'*64
        for record in records:
            sequence=record.get('sequence')
            if type(sequence) is not int or sequence<1:
                raise ContractError('UPSTREAM_CONTRACT_ERROR','Track 1 audit sequence is invalid',502)
            existing=db.execute('SELECT payload_digest FROM audit_mirror WHERE track1_sequence=?',(sequence,)).fetchone()
            payload_digest=digest(record)
            if existing:
                if existing['payload_digest']!=payload_digest:
                    raise ContractError('AUDIT_CONFLICT','Previously mirrored Track 1 audit record changed',409)
                continue
            envelope={'track1_sequence':sequence,'payload_digest':payload_digest,'previous_mirror_hash':previous}
            mirror_hash=digest(envelope)
            db.execute('INSERT INTO audit_mirror VALUES (?,?,?,?,?,?)',
                       (sequence,canonical(record),payload_digest,previous,mirror_hash,now()))
            previous=mirror_hash;added+=1
        if records:
            db.execute("UPDATE metadata SET value=? WHERE key='track1_audit_cursor'",(str(max(r['sequence'] for r in records)),))
    return added
