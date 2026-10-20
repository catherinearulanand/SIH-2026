"""Independent review, atomic FEFO reservation and attributable partial fulfilment."""
from . import clock
import json
from datetime import datetime, timezone
from .auth import DomainError
from .db import now, uid, revision, bump, audit, canonical
from .inventory import integer, text, stock, apply_event

POLICY_VERSION='synthetic-policy-v1'


def get_request(db, actor, request_id, require_both=True):
    row=db.execute('SELECT * FROM requests WHERE request_id=?',(request_id,)).fetchone()
    if not row or not ({row['source_site_id'],row['destination_site_id']} & actor.sites):
        raise DomainError('NOT_FOUND','Request not found',404)
    if require_both:
        actor.require(sites=[row['source_site_id'],row['destination_site_id']])
    result=dict(row)
    result['reservations']=[dict(r) for r in db.execute('SELECT * FROM reservations WHERE request_id=? ORDER BY batch_id',(request_id,))]
    result['dispatched_quantity']=sum(r['dispatched'] for r in result['reservations'])
    result['reserved_quantity']=sum(r['quantity'] for r in result['reservations'])
    result['decisions']=[dict(d) for d in db.execute('SELECT * FROM decisions WHERE request_id=? ORDER BY server_time',(request_id,))]
    return result


def version(row, body):
    integer(body.get('expected_version'),'expected_version')
    if row['version']!=body['expected_version']:
        raise DomainError('STALE_VERSION','Object version changed',409,row['version'])


def create_request(db, actor, body, correlation):
    actor.require(['planner'])
    src=text(body.get('source_site_id'),'source_site_id',48)
    dst=text(body.get('destination_site_id'),'destination_site_id',48)
    actor.require(sites=[src,dst])
    if src==dst:
        raise DomainError('INVALID_INPUT','Source and destination must differ')
    item=text(body.get('item_id'),'item_id',48)
    if not db.execute('SELECT 1 FROM items WHERE item_id=?',(item,)).fetchone():
        raise DomainError('UNKNOWN_ITEM','Unknown item')
    q=integer(body.get('quantity'))
    input_revision=integer(body.get('input_revision'),'input_revision',0,2**63-1)
    if input_revision!=revision(db):
        raise DomainError('STALE_VERSION','Planning input changed',409,revision(db))
    snapshot_id=body.get('snapshot_id')
    if snapshot_id:
        snap=db.execute('SELECT * FROM snapshots WHERE snapshot_id=?',(snapshot_id,)).fetchone()
        if not snap or not {src,dst}<=set(json.loads(snap['sites'])) or not set(json.loads(snap['sites']))<=actor.sites:
            raise DomainError('SNAPSHOT_DENIED','Snapshot unavailable in this scope',403)
        if snap['revision']!=input_revision:
            raise DomainError('STALE_VERSION','Snapshot does not match input revision',409,revision(db))
    ident,ts=uid('req'),now()
    reason=text(body.get('reason'),'reason',1000)
    db.execute('''INSERT INTO requests VALUES (?,?,?,?,?,?, 'DRAFT',1,?,?,?,NULL,?,?,?)''',
               (ident,actor.actor_id,src,dst,item,q,input_revision,snapshot_id,POLICY_VERSION,reason,ts,ts))
    audit(db,actor.actor_id,'REQUEST_CREATED',ident,[src,dst],correlation,{'quantity':q,'policy_version':POLICY_VERSION,'reason':reason})
    return get_request(db,actor,ident)


def transition(db, actor, request_id, action, body, correlation):
    r=get_request(db,actor,request_id)
    version(r,body)
    sites=[r['source_site_id'],r['destination_site_id']]
    if action=='submit':
        actor.require(['planner'])
        if actor.actor_id!=r['creator_id'] or r['status']!='DRAFT':
            raise DomainError('INVALID_STATE','Only the creator can submit a draft',409)
        if r['input_revision']!=revision(db):
            raise DomainError('STALE_VERSION','Input changed; create a fresh draft',409,revision(db))
        status='SUBMITTED'
    elif action in ('approve','reject'):
        actor.require(['approver'])
        if actor.actor_id==r['creator_id']:
            raise DomainError('SELF_APPROVAL','Creator cannot review their own request',403)
        if r['status']!='SUBMITTED':
            raise DomainError('INVALID_STATE','Request must be submitted',409)
        reason=text(body.get('reason'),'reason',1000)
        if action=='approve':
            if r['input_revision']!=revision(db):
                raise DomainError('STALE_VERSION','Stock changed; create a fresh draft',409,revision(db))
            candidates=stock(db,actor,r['source_site_id'],r['item_id'])['batches']
            if sum(b['allocatable'] for b in candidates)<r['quantity']:
                raise DomainError('INSUFFICIENT_STOCK','Not enough allocatable stock for complete reservation',409)
            needed=r['quantity']
            max_age=db.execute("SELECT max_age_seconds FROM sources WHERE source_id='SIH_SYNTHETIC_CSV'").fetchone()[0]
            for b in candidates:
                if needed==0:
                    break
                if b['allocatable']==0:
                    continue
                latest_evidence=max(b['last_posted_at'] or '',b['last_physical_count_at'] or '')
                age=(clock.utcnow()-datetime.fromisoformat(latest_evidence.replace('Z','+00:00'))).total_seconds()
                if age>max_age:
                    raise DomainError('STALE_DATA','Stock evidence freshness exceeded; verify a current physical count or reconcile evidence before approval',409)
                count=b['last_physical_count_at']
                # Explicit demonstration rule, not a sponsor freshness requirement.
                if not count or (clock.utcnow()-datetime.fromisoformat(count.replace('Z','+00:00'))).total_seconds()>30*86400:
                    raise DomainError('STALE_COUNT','Physical count evidence older than the demo 30-day policy',409)
                q=min(needed,b['allocatable'])
                db.execute('UPDATE balances SET reserved=reserved+?,version=version+1 WHERE site_id=? AND batch_id=?',
                           (q,r['source_site_id'],b['batch_id']))
                db.execute('INSERT INTO reservations VALUES (?,?,?,0)',(request_id,b['batch_id'],q))
                needed-=q
            if needed:
                raise DomainError('INSUFFICIENT_STOCK','Not enough allocatable stock for complete reservation',409)
            bump(db)
            status='APPROVED'
        else:
            status='REJECTED'
        db.execute('UPDATE requests SET approver_id=? WHERE request_id=?',(actor.actor_id,request_id))
    elif action=='cancel':
        actor.require(['planner','approver'])
        if actor.actor_id not in (r['creator_id'],r['approver_id']):
            raise DomainError('FORBIDDEN','Only creator or reviewer can cancel',403)
        if r['status'] not in ('DRAFT','SUBMITTED','APPROVED') or r['dispatched_quantity']:
            raise DomainError('INVALID_STATE','Dispatched or terminal requests cannot be cancelled',409)
        for line in r['reservations']:
            db.execute('UPDATE balances SET reserved=reserved-?,version=version+1 WHERE site_id=? AND batch_id=?',
                       (line['quantity'],r['source_site_id'],line['batch_id']))
        db.execute('UPDATE reservations SET quantity=0 WHERE request_id=?',(request_id,))
        if r['reserved_quantity']:
            bump(db)
        status='CANCELLED'
    elif action=='close':
        actor.require(['approver'])
        if r['status']!='APPROVED' or r['reserved_quantity'] or r['dispatched_quantity']!=r['quantity']:
            raise DomainError('UNRESOLVED','All approved quantities must be dispatched before closure',409)
        if db.execute("SELECT 1 FROM shipments WHERE request_id=? AND status!='RECONCILED'",(request_id,)).fetchone():
            raise DomainError('UNRESOLVED','Shipment receipt or disposition reconciliation remains open',409)
        status='CLOSED'
    else:
        raise DomainError('NOT_FOUND','Unknown action',404)
    db.execute('UPDATE requests SET status=?,version=version+1,updated_at=? WHERE request_id=?',(status,now(),request_id))
    reason=body.get('reason') or r['reason']
    db.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?)',
               (uid('decision'),request_id,actor.actor_id,action,reason,r['version'],r['version']+1,r['input_revision'],r['policy_version'],now()))
    audit(db,actor.actor_id,'REQUEST_'+action.upper(),request_id,sites,correlation,
          {'before_version':r['version'],'after_version':r['version']+1,'policy_version':POLICY_VERSION,'reason':reason})
    return get_request(db,actor,request_id)


def dispatch(db,actor,request_id,body,correlation):
    actor.require(['dispatcher'])
    r=get_request(db,actor,request_id)
    version(r,body)
    if r['status']!='APPROVED':
        raise DomainError('INVALID_STATE','Independent approval and reservation required',409)
    q=integer(body.get('quantity'))
    if q>r['reserved_quantity']:
        raise DomainError('OVER_DISPATCH','Quantity exceeds outstanding reservation',409)
    sid,ts=uid('shipment'),now()
    db.execute('INSERT INTO shipments VALUES (?,?,?,1,?)',(sid,request_id,'DISPATCH_RECORDED',ts))
    remaining=q
    by_batch={b['batch_id']:b for b in stock(db,actor,r['source_site_id'],r['item_id'])['batches']}
    lines=sorted(r['reservations'],key=lambda x:(by_batch[x['batch_id']]['expiry_date'],x['batch_id']))
    for line in lines:
        take=min(remaining,line['quantity'])
        if not take:
            continue
        b=by_batch[line['batch_id']]
        if b['expiry_blocked']:
            raise DomainError('EXPIRED_BATCH','Reserved batch expired before dispatch; cancel/review required',409)
        db.execute('UPDATE balances SET reserved=reserved-? WHERE site_id=? AND batch_id=?',(take,r['source_site_id'],b['batch_id']))
        row=dict(event_id=uid('evt'),site_id=r['source_site_id'],item_id=r['item_id'],batch_id=b['batch_id'],
                 event_type='DISPATCH',quantity=str(take),base_unit=b['base_unit'],occurred_at=ts,
                 expiry_date=b['expiry_date'],source_ref=sid)
        apply_event(db,actor,row,correlation,request_id=request_id,shipment_id=sid,internal=True)
        db.execute('UPDATE reservations SET quantity=quantity-?,dispatched=dispatched+? WHERE request_id=? AND batch_id=?',
                   (take,take,request_id,b['batch_id']))
        db.execute('INSERT INTO shipment_lines VALUES (?,?,?,0)',(sid,b['batch_id'],take))
        remaining-=take
    db.execute('UPDATE requests SET version=version+1,updated_at=? WHERE request_id=?',(ts,request_id))
    bump(db)
    audit(db,actor.actor_id,'DISPATCH',sid,[r['source_site_id'],r['destination_site_id']],correlation,{'quantity':q,'request_id':request_id})
    return get_shipment(db,actor,sid)


def get_shipment(db,actor,shipment_id):
    s=db.execute('SELECT * FROM shipments WHERE shipment_id=?',(shipment_id,)).fetchone()
    if not s:
        raise DomainError('NOT_FOUND','Shipment not found',404)
    r=get_request(db,actor,s['request_id'],False)
    result=dict(s)
    result.update(source_site_id=r['source_site_id'],destination_site_id=r['destination_site_id'],item_id=r['item_id'])
    result['lines']=[dict(l) for l in db.execute('SELECT * FROM shipment_lines WHERE shipment_id=? ORDER BY batch_id',(shipment_id,))]
    result['unresolved_quantity']=sum(l['quantity']-l['received'] for l in result['lines'])
    result['receipt_parts']=[{**json.loads(p['payload']),'actor_id':p['actor_id'],'recorded_at':p['created_at']} for p in db.execute('SELECT * FROM receipt_parts WHERE shipment_id=? ORDER BY created_at',(shipment_id,))]
    return result


def receive(db,actor,shipment_id,body,correlation):
    actor.require(['receiver'])
    s=get_shipment(db,actor,shipment_id)
    actor.require(sites=[s['destination_site_id']])
    version(s,body)
    if s['status'] not in ('DISPATCH_RECORDED','PARTIALLY_RECEIVED'):
        raise DomainError('INVALID_STATE','Shipment is not receiving',409)
    part_id=text(body.get('receipt_part_id'),'receipt_part_id',80)
    if db.execute('SELECT 1 FROM receipt_parts WHERE receipt_part_id=?',(part_id,)).fetchone():
        raise DomainError('DUPLICATE_PART','Receipt part already exists; retry with original idempotency key',409)
    parts=body.get('lines')
    if not isinstance(parts,list) or not 1<=len(parts)<=100:
        raise DomainError('INVALID_INPUT','lines must contain 1 to 100 dispositions')
    known={l['batch_id']:l for l in s['lines']}
    seen=set()
    for line in parts:
        if not isinstance(line,dict) or set(line)!={'batch_id','accepted','quarantined','damaged','rejected'}:
            raise DomainError('INVALID_INPUT','Each line needs batch_id, accepted, quarantined, damaged and rejected')
        bid=text(line.get('batch_id'),'batch_id',48)
        if bid not in known or bid in seen:
            raise DomainError('INVALID_BATCH','Batch absent from shipment or repeated')
        seen.add(bid)
        for k in ('accepted','quarantined','damaged','rejected'):
            integer(line[k],k,0)
        total=sum(line[k] for k in ('accepted','quarantined','damaged','rejected'))
        if total<=0 or total>known[bid]['quantity']-known[bid]['received']:
            raise DomainError('OVER_RECEIPT','Physical quantity must be positive and cannot exceed dispatched remainder',409)
        batch=db.execute('SELECT * FROM batches WHERE batch_id=?',(bid,)).fetchone()
        unit=db.execute('SELECT base_unit FROM items WHERE item_id=?',(s['item_id'],)).fetchone()[0]
        for k,kind in [('accepted','RECEIPT'),('quarantined','RECEIPT_QUARANTINED'),('damaged','RECEIPT_DAMAGED'),('rejected','RECEIPT_REJECTED')]:
            if line[k]:
                row=dict(event_id=uid('evt'),site_id=s['destination_site_id'],item_id=s['item_id'],batch_id=bid,
                         event_type=kind,quantity=str(line[k]),base_unit=unit,occurred_at=now(),
                         expiry_date=batch['expiry_date'],source_ref=part_id)
                apply_event(db,actor,row,correlation,request_id=s['request_id'],shipment_id=shipment_id,receipt_part_id=part_id,internal=True)
        db.execute('UPDATE shipment_lines SET received=received+? WHERE shipment_id=? AND batch_id=?',(total,shipment_id,bid))
    db.execute('INSERT INTO receipt_parts VALUES (?,?,?,?,?)',(part_id,shipment_id,actor.actor_id,canonical(body),now()))
    # Even a complete physical receipt needs explicit disposition reconciliation.
    db.execute("UPDATE shipments SET status='PARTIALLY_RECEIVED',version=version+1 WHERE shipment_id=?",(shipment_id,))
    bump(db)
    audit(db,actor.actor_id,'RECEIPT_PART',part_id,[s['source_site_id'],s['destination_site_id']],correlation,{'shipment_id':shipment_id,'lines':parts})
    return get_shipment(db,actor,shipment_id)


def reconcile(db,actor,shipment_id,body,correlation):
    actor.require(['approver'])
    s=get_shipment(db,actor,shipment_id)
    actor.require(sites=[s['source_site_id'],s['destination_site_id']])
    version(s,body)
    if s['unresolved_quantity'] or s['status']!='PARTIALLY_RECEIVED':
        raise DomainError('UNRESOLVED','All physical quantities must be accounted for before reconciliation',409)
    reason=text(body.get('reason'),'reason',1000)
    db.execute("UPDATE shipments SET status='RECONCILED',version=version+1 WHERE shipment_id=?",(shipment_id,))
    audit(db,actor.actor_id,'SHIPMENT_RECONCILED',shipment_id,[s['source_site_id'],s['destination_site_id']],correlation,{'reason':reason})
    return get_shipment(db,actor,shipment_id)
