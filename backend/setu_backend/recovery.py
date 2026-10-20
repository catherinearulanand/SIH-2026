"""Offline verification and SQLite online-backup API; no copying live WAL files."""
import json
import sqlite3
from collections import defaultdict
from .db import connect, digest


def verify(path):
    db=connect(path)
    errors=[]
    try:
        db.execute('BEGIN')
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok': errors.append('SQLite integrity: '+integrity)
        if db.execute('PRAGMA foreign_key_check').fetchone(): errors.append('Foreign key violation')
        previous='0'*64
        for row in db.execute('SELECT * FROM audit ORDER BY sequence'):
            r=dict(row)
            entry={k:r[k] for k in ('actor_id','action','object_ref','outcome','correlation_id','server_time','previous_hash')}
            entry['sites']=json.loads(r['sites']);entry['details']=json.loads(r['details'])
            if r['previous_hash']!=previous or r['entry_hash']!=digest(entry):
                errors.append('Audit chain mismatch at '+str(r['sequence']))
            previous=r['entry_hash']
        expected=defaultdict(lambda:dict(usable=0,quarantined=0,damaged=0,rejected=0,expired=0))
        for e in db.execute('SELECT * FROM events ORDER BY sequence'):
            from .csv_schema import COLUMNS
            payload={key:(str(e[key]) if key=='quantity' else e[key]) for key in COLUMNS}
            if digest(payload)!=e['payload_hash']: errors.append('Event payload hash mismatch: '+e['event_id'])
            b=expected[(e['site_id'],e['batch_id'])];k=e['event_type'];q=e['quantity']
            if k in ('OPENING','RECEIPT','RETURN'): b['usable']+=q
            elif k in ('ISSUE','DISPATCH'): b['usable']-=q
            elif k=='RELEASE': b['quarantined']-=q;b['usable']+=q
            elif k in ('QUARANTINE','DAMAGE','EXPIRE'):
                b['usable']-=q;b[{'QUARANTINE':'quarantined','DAMAGE':'damaged','EXPIRE':'expired'}[k]]+=q
            elif k in ('RECEIPT_QUARANTINED','RECEIPT_DAMAGED','RECEIPT_REJECTED'):
                b[{'RECEIPT_QUARANTINED':'quarantined','RECEIPT_DAMAGED':'damaged','RECEIPT_REJECTED':'rejected'}[k]]+=q
            else: errors.append('Unknown event kind '+k)
            if any(v<0 for v in b.values()): errors.append('Negative replay balance at '+e['event_id'])
        actual=set()
        for b in db.execute('SELECT * FROM balances'):
            key=(b['site_id'],b['batch_id']);actual.add(key)
            if any(b[k]!=v for k,v in expected[key].items()): errors.append('Projection mismatch: '+str(key))
            reserved=db.execute('''SELECT COALESCE(SUM(x.quantity),0) FROM reservations x JOIN requests r USING(request_id)
                                   WHERE r.source_site_id=? AND x.batch_id=?''',key).fetchone()[0]
            if reserved!=b['reserved']: errors.append('Reservation mismatch: '+str(key))
        if set(expected)-actual: errors.append('Missing balance projection')
        return {'valid':not errors,'errors':errors,'audit_head_sha256':previous,
                'events':db.execute('SELECT COUNT(*) FROM events').fetchone()[0],
                'limitation':'Local chain/triggers detect accidental changes; database administrators can rewrite both. Independent audit sink is Track 4.'}
    finally:
        db.close()


def backup(path,target):
    from pathlib import Path
    if Path(path).resolve()==Path(target).resolve() or Path(target).exists():
        raise ValueError('Backup target must be a new, separate path')
    src=connect(path);dst=sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close();src.close()
    return verify(target)
