"""Batch accounting. Buckets are disjoint; reservations are a subset of usable."""
from . import clock
from datetime import date
from .auth import DomainError
from .db import now, digest, revision


def integer(value, field='quantity', minimum=1, maximum=10_000_000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError('INVALID_INPUT',f'{field} must be an integer from {minimum} to {maximum}')
    return value


def text(value, field, maximum=256):
    if not isinstance(value,str) or not value.strip() or len(value)>maximum or '\x00' in value:
        raise DomainError('INVALID_INPUT',f'{field} must be nonempty text, at most {maximum} characters')
    return value.strip()


def timestamp(value):
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(value.replace('Z','+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None or dt > clock.utcnow():
            raise ValueError
        return dt.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
    except (ValueError,TypeError,AttributeError):
        raise DomainError('INVALID_TIME','occurred_at must be a nonfuture timestamp with timezone') from None


def batch(db, batch_id, item_id, expiry):
    old = db.execute('SELECT * FROM batches WHERE batch_id=?',(batch_id,)).fetchone()
    if old and (old['item_id']!=item_id or old['expiry_date']!=expiry):
        raise DomainError('BATCH_CONFLICT','Batch item or expiry cannot change',409)
    if not old:
        db.execute('INSERT INTO batches VALUES (?,?,?)',(batch_id,item_id,expiry))


def apply_event(db, actor, row, correlation, source_id='WORKFLOW', request_id=None,
                shipment_id=None, receipt_part_id=None, internal=False):
    """Caller holds write transaction; all projections/events commit or roll back together."""
    actor.require(sites=[row['site_id']])
    q = integer(int(row['quantity']))
    item = db.execute('SELECT * FROM items WHERE item_id=?',(row['item_id'],)).fetchone()
    if not item or row['base_unit'] != item['base_unit']:
        raise DomainError('INVALID_UNIT','Unknown item or noncanonical unit')
    kind = row['event_type']
    if not internal:
        actor.require(['qa'] if kind=='RELEASE' else ['storekeeper','custodian'])
    batch(db,row['batch_id'],row['item_id'],row['expiry_date'])
    db.execute('INSERT OR IGNORE INTO balances(site_id,batch_id) VALUES (?,?)',(row['site_id'],row['batch_id']))
    current = db.execute('SELECT * FROM balances WHERE site_id=? AND batch_id=?',
                         (row['site_id'],row['batch_id'])).fetchone()
    values = {k:current[k] for k in ('usable','quarantined','damaged','rejected','expired')}
    # Historical CSV import is posted now, but event order and origin timestamps remain intact.
    expired_at_event = date.fromisoformat(row['expiry_date']) < date.fromisoformat(row['occurred_at'][:10])
    if kind=='EXPIRE' and not expired_at_event:
        raise DomainError('INVALID_EXPIRY','Formal expiry requires occurrence after the batch expiry date',409)
    if kind in ('OPENING','RECEIPT','RETURN'):
        if expired_at_event:
            raise DomainError('EXPIRED_BATCH','Expired goods cannot enter usable stock',409)
        if kind=='OPENING' and db.execute('SELECT 1 FROM events WHERE site_id=? AND batch_id=?',
                                         (row['site_id'],row['batch_id'])).fetchone():
            raise DomainError('OPENING_EXISTS','Opening balance must be the first batch event at this site',409)
        values['usable'] += q
    elif kind in ('RECEIPT_QUARANTINED','RECEIPT_DAMAGED','RECEIPT_REJECTED'):
        values[{'RECEIPT_QUARANTINED':'quarantined','RECEIPT_DAMAGED':'damaged','RECEIPT_REJECTED':'rejected'}[kind]] += q
    elif kind=='RELEASE':
        if expired_at_event or date.fromisoformat(row['expiry_date']) < clock.today():
            raise DomainError('EXPIRED_BATCH','Expired batch cannot be released',409)
        if values['quarantined']<q:
            raise DomainError('INSUFFICIENT_STOCK','Insufficient quarantined stock',409)
        values['quarantined']-=q
        values['usable']+=q
    elif kind in ('ISSUE','DISPATCH','QUARANTINE','DAMAGE','EXPIRE'):
        if kind in ('ISSUE','DISPATCH') and expired_at_event:
            raise DomainError('EXPIRED_BATCH','Expired batch cannot be issued',409)
        if values['usable'] - current['reserved'] < q:
            raise DomainError('INSUFFICIENT_STOCK','Insufficient unreserved usable stock',409)
        values['usable']-=q
        if kind in ('QUARANTINE','DAMAGE','EXPIRE'):
            values[{'QUARANTINE':'quarantined','DAMAGE':'damaged','EXPIRE':'expired'}[kind]]+=q
    else:
        raise DomainError('INVALID_EVENT','Unsupported stock event')
    last_observed = max(current['last_observed_at'] or '',row['occurred_at'])
    posted = now()
    db.execute('''UPDATE balances SET usable=?,quarantined=?,damaged=?,rejected=?,expired=?,
      version=version+1,last_observed_at=?,last_posted_at=?,last_physical_count_at=?
      WHERE site_id=? AND batch_id=?''',
      (*values.values(),last_observed,posted,
       row['occurred_at'] if kind=='OPENING' else current['last_physical_count_at'],row['site_id'],row['batch_id']))
    db.execute('''INSERT INTO events(event_id,schema_version,source_id,site_id,item_id,batch_id,event_type,
        quantity,base_unit,occurred_at,recorded_at,expiry_date,source_ref,actor_id,payload_hash,correlation_id,
        request_id,shipment_id,receipt_part_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (row['event_id'],'1.0',source_id,row['site_id'],row['item_id'],row['batch_id'],kind,q,row['base_unit'],
         row['occurred_at'],posted,row['expiry_date'],row['source_ref'],actor.actor_id,digest(row),correlation,
         request_id,shipment_id,receipt_part_id))


def stock(db, actor, site_id=None, item_id=None):
    if site_id:
        actor.require(sites=[site_id])
    sites = [site_id] if site_id else sorted(actor.sites)
    placeholders = ','.join('?' for _ in sites)
    result = []
    for row in db.execute(f'''SELECT b.*,t.item_id,t.expiry_date,i.base_unit FROM balances b
         JOIN batches t USING(batch_id) JOIN items i USING(item_id)
         WHERE site_id IN ({placeholders}) ORDER BY site_id,t.item_id,expiry_date,batch_id''',sites):
        if item_id and row['item_id']!=item_id:
            continue
        r = dict(row)
        expired = date.fromisoformat(r['expiry_date']) < clock.today()
        # Dynamic expiry is a disjoint view, not a second physical stock event.
        r['physical_on_hand'] = sum(r[k] for k in ('usable','quarantined','damaged','rejected','expired'))
        r['expiry_blocked'] = expired
        r['quality_quarantined'] = r['quarantined']
        if expired:
            r['expired'] += r['usable'] + r['quarantined'] + r['damaged'] + r['rejected']
            for key in ('usable','quarantined','damaged','rejected'):
                r[key]=0
        r['allocatable'] = max(0,r['usable']-r['reserved'])
        r['quality_unavailable'] = r['physical_on_hand']-r['usable']
        r['last_synchronization_at'] = None
        r['synchronization_warning'] = 'Independent source sync time is unknown; last_posted_at is server stock-event receipt time'
        result.append(r)
    return {'schema_version':'1.0','revision':revision(db),'as_of':now(),'synthetic':True,'batches':result}
