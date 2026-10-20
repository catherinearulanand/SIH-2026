"""Actor-bound preview, atomic commit and exact duplicate handling."""
from . import clock
import hashlib
import json
from datetime import datetime, timezone
from .auth import DomainError
from .csv_schema import parse, COLUMNS
from .db import transaction, digest, uid, now, revision, bump, audit, canonical
from .inventory import apply_event


def source(db, actor, source_id):
    actor.require(['custodian'])
    row = db.execute('SELECT * FROM sources WHERE source_id=? AND enabled=1',(source_id,)).fetchone()
    if not row or source_id != 'SIH_SYNTHETIC_CSV':
        raise DomainError('SOURCE_DENIED','Source is not enabled for CSV import',403)
    return row


def assess(db, actor, csv_text, correlation):
    rows, errors = parse(csv_text)
    if errors:
        return [], errors, 0
    accepted, duplicates = [],0
    # A savepoint exercises the real accounting path and always removes its writes.
    db.execute('SAVEPOINT import_assessment')
    try:
        for number, row in sorted(enumerate(rows,2),key=lambda p:(p[1]['occurred_at'],p[1]['event_id'])):
            actor.require(sites=[row['site_id']])
            old = db.execute('SELECT payload_hash FROM events WHERE event_id=?',(row['event_id'],)).fetchone()
            if old:
                if old[0] != digest(row):
                    errors.append({'row':number,'field':'event_id','message':'Existing ID has different content'})
                else:
                    duplicates += 1
                continue
            try:
                apply_event(db,actor,row,correlation,source_id='SIH_SYNTHETIC_CSV')
                accepted.append(row)
            except DomainError as exc:
                errors.append({'row':number,'field':'event','message':exc.message,'code':exc.code})
    finally:
        db.execute('ROLLBACK TO import_assessment')
        db.execute('RELEASE import_assessment')
    return accepted,errors,duplicates


def preview(db, actor, body, correlation):
    source_id = body.get('source_id')
    source(db,actor,source_id)
    with transaction(db):
        rows,errors,duplicates = assess(db,actor,body.get('csv_text'),correlation)
        csv_text = body.get('csv_text')
        sha = hashlib.sha256(csv_text.encode()).hexdigest() if isinstance(csv_text,str) else None
        preview_id = uid('preview') if not errors else None
        if preview_id:
            db.execute('INSERT INTO previews VALUES (?,?,?,?,?,?,NULL)',
                       (preview_id,actor.actor_id,source_id,sha,revision(db),now()))
        audit(db,actor.actor_id,'IMPORT_PREVIEW',preview_id or 'invalid-import',actor.sites,correlation,
              {'valid':not errors,'row_count':len(rows),'error_count':len(errors)})
        return {'valid':not errors,'accepted_rows':len(rows) if not errors else 0,
                'unchanged_duplicate_rows':duplicates,'errors':errors,'source_id':source_id,
                'preview_id':preview_id,'preview_sha256':sha,'revision':revision(db)}


def commit(db, actor, body, correlation):
    source_id = body.get('source_id')
    source(db,actor,source_id)
    csv_text = body.get('csv_text')
    if not isinstance(csv_text,str):
        raise DomainError('INVALID_INPUT','csv_text is required')
    with transaction(db):
        p = db.execute('SELECT * FROM previews WHERE preview_id=? AND actor_id=?',
                       (body.get('preview_id'),actor.actor_id)).fetchone()
        if not p or p['source_id']!=source_id or p['content_hash']!=hashlib.sha256(csv_text.encode()).hexdigest():
            raise DomainError('PREVIEW_MISMATCH','Preview is missing, belongs to another actor or content changed',409)
        if p['result']:
            return json.loads(p['result'])
        if (clock.utcnow()-datetime.fromisoformat(p['created_at'].replace('Z','+00:00'))).total_seconds()>900:
            raise DomainError('PREVIEW_EXPIRED','Preview expired; validate again',409)
        if p['revision']!=revision(db):
            raise DomainError('STALE_VERSION','Inventory changed; validate again',409,revision(db))
        rows,errors,duplicates = assess(db,actor,csv_text,correlation)
        if errors:
            raise DomainError('IMPORT_REJECTED','No rows committed',422,field_errors=errors)
        for row in rows:
            apply_event(db,actor,row,correlation,source_id=source_id)
        if rows:
            bump(db)
        result = {'committed':True,'accepted_rows':len(rows),'unchanged_duplicate_rows':duplicates,
                  'errors':[],'revision':revision(db),'source_sha256':p['content_hash'],'preview_id':p['preview_id']}
        db.execute('UPDATE previews SET result=? WHERE preview_id=?',(canonical(result),p['preview_id']))
        audit(db,actor.actor_id,'IMPORT_COMMIT',p['preview_id'],actor.sites,correlation,result)
        return result
