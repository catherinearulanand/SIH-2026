"""Public application interface shared by HTTP, tests and local integration tools."""
from . import clock
import hashlib
import json
import sqlite3
from datetime import date
from . import imports, workflow
from .auth import DomainError, authenticate
from .db import connect, transaction, uid, now, revision, bump, canonical, digest, audit
from .inventory import stock, text, integer, timestamp, apply_event
from .csv_schema import parse, COLUMNS


class Service:
    def __init__(self,path):
        self.path=path

    def call(self,token,method,path,body=None,key=None,query=None,correlation=None):
        db=connect(self.path)
        correlation=correlation or uid('corr')
        actor=None
        try:
            actor=authenticate(db,token)
            if method=='GET':
                db.execute('BEGIN')
                result=self.read(db,actor,path,query or {},correlation)
                db.commit()
                return result
            if method!='POST':
                raise DomainError('METHOD_NOT_ALLOWED','Use GET or POST',405)
            if not isinstance(body,dict):
                raise DomainError('INVALID_INPUT','JSON object required')
            if path=='/api/v1/imports/validate':
                strict(body,{'source_id','csv_text'})
                return imports.preview(db,actor,body,correlation)
            if path=='/api/v1/imports/commit':
                strict(body,{'source_id','csv_text','preview_id','preview_sha256'})
                return imports.commit(db,actor,body,correlation)
            key=text(key,'Idempotency-Key',128)
            with transaction(db):
                old=db.execute('SELECT * FROM idempotency WHERE actor_id=? AND operation=? AND key=?',
                               (actor.actor_id,path,key)).fetchone()
                payload_hash=digest(body)
                if old:
                    if old['payload_hash']!=payload_hash:
                        raise DomainError('IDEMPOTENCY_CONFLICT','Key was used for a different payload',409)
                    # Recheck current scope before returning a saved response after role/scope changes.
                    sites=json.loads(old['result']).get('_authorized_sites',[])
                    actor.require(sites=sites)
                    result=json.loads(old['result']);result.pop('_authorized_sites',None)
                    return result
                result=self.write(db,actor,path,body,correlation)
                stored={**result,'_authorized_sites':sorted(actor.sites)}
                db.execute('INSERT INTO idempotency VALUES (?,?,?,?,?)',
                           (actor.actor_id,path,key,payload_hash,canonical(stored)))
                return result
        except DomainError as exc:
            if db.in_transaction:
                db.rollback()
            if actor:
                # Denial audit is separate, so rollback cannot erase the failed attempt.
                with transaction(db):
                    audit(db,actor.actor_id,'API_DENIED',path,actor.sites,correlation,{'code':exc.code},'DENY')
            raise
        except sqlite3.OperationalError as exc:
            if db.in_transaction:
                db.rollback()
            if 'locked' in str(exc).lower() or 'busy' in str(exc).lower():
                raise DomainError('DATABASE_BUSY','Database busy; retry with the same idempotency key',503) from None
            raise
        except sqlite3.IntegrityError:
            if db.in_transaction:
                db.rollback()
            raise DomainError('CONFLICT','Duplicate identifier or accounting constraint conflict',409) from None
        finally:
            db.close()

    def read(self,db,actor,path,query,correlation):
        if path=='/api/v1/me':
            return {'actor_id':actor.actor_id,'roles':sorted(actor.roles),'sites':sorted(actor.sites)}
        if path=='/api/v1/inventory':
            return stock(db,actor,query.get('site_id'),query.get('item_id'))
        if path=='/api/v1/catalog':
            return {'schema_version':'1.0','synthetic':True,
                    'sites':[dict(r) for r in db.execute('SELECT * FROM sites') if r['site_id'] in actor.sites],
                    'items':[dict(r) for r in db.execute('SELECT * FROM items')]}
        if path=='/api/v1/sources':
            return {'sources':[{**dict(r),'allowed_sites':json.loads(r['allowed_sites'])} for r in db.execute('SELECT * FROM sources')
                               if set(json.loads(r['allowed_sites'])) & actor.sites]}
        if path=='/api/v1/requests':
            ids=[r['request_id'] for r in db.execute('SELECT * FROM requests ORDER BY created_at DESC')
                 if {r['source_site_id'],r['destination_site_id']}<=actor.sites]
            return {'requests':[workflow.get_request(db,actor,i) for i in ids[:500]]}
        if path.startswith('/api/v1/requests/') and len(path.split('/'))==5:
            return workflow.get_request(db,actor,path.split('/')[-1])
        if path=='/api/v1/shipments':
            result=[]
            for s in db.execute('SELECT s.shipment_id,r.source_site_id,r.destination_site_id FROM shipments s JOIN requests r USING(request_id) ORDER BY s.created_at DESC'):
                if {s['source_site_id'],s['destination_site_id']} & actor.sites:
                    result.append(workflow.get_shipment(db,actor,s['shipment_id']))
            return {'shipments':result[:500]}
        if path.startswith('/api/v1/shipments/') and len(path.split('/'))==5:
            return workflow.get_shipment(db,actor,path.split('/')[-1])
        if path.startswith('/api/v1/snapshots/') and len(path.split('/'))==5:
            s=db.execute('SELECT * FROM snapshots WHERE snapshot_id=?',(path.split('/')[-1],)).fetchone()
            if not s or not set(json.loads(s['sites']))<=actor.sites:
                raise DomainError('NOT_FOUND','Snapshot not found',404)
            return {'snapshot_id':s['snapshot_id'],'content_sha256':s['content_hash'],'data':json.loads(s['payload'])}
        if path=='/api/v1/demand':
            if query.get('site_id'):
                actor.require(sites=[query['site_id']])
            rows=[]
            for r in db.execute('SELECT * FROM demand ORDER BY period,site_id,item_id'):
                if r['site_id'] in actor.sites and (not query.get('site_id') or r['site_id']==query['site_id']):
                    rows.append({**json.loads(r['payload']),'record_id':r['record_id'],'recorded_at':r['recorded_at']})
            return {'schema_version':'1.0','records':rows,'warnings':[] if rows else ['NO_DEMAND_HISTORY: supplied CSV contains inventory events, not demand observations']}
        if path in ('/api/v1/events','/api/v1/audit'):
            if path.endswith('audit'):
                actor.require(['auditor'])
            try:
                after=int(query.get('after','0'));limit=int(query.get('limit','100'))
                if after<0 or not 1<=limit<=500:
                    raise ValueError
            except (ValueError,TypeError):
                raise DomainError('INVALID_INPUT','after must be nonnegative; limit must be 1..500') from None
            if query.get('site_id'):
                actor.require(sites=[query['site_id']])
            result=[]
            table='audit' if path.endswith('audit') else 'events'
            # Sequence cursor advances only across records actually returned.
            for row in db.execute(f'SELECT * FROM {table} WHERE sequence>? ORDER BY sequence',(after,)):
                r=dict(row)
                if table=='events':
                    allowed=r['site_id'] in actor.sites and (not query.get('site_id') or r['site_id']==query['site_id'])
                else:
                    scope=set(json.loads(r['sites']))
                    allowed=scope<=actor.sites and (not query.get('site_id') or query['site_id'] in scope)
                if allowed:
                    if table=='audit':
                        r['sites']=json.loads(r['sites']);r['details']=json.loads(r['details'])
                    result.append(r)
                    if len(result)>=limit:
                        break
            return {'records':result,'next_after':result[-1]['sequence'] if result else after}
        raise DomainError('NOT_FOUND','Endpoint not found',404)

    def write(self,db,actor,path,body,correlation):
        parts=path.split('/')
        if path=='/api/v1/requests':
            strict(body,{'source_site_id','destination_site_id','item_id','quantity','input_revision','snapshot_id','reason'})
            return workflow.create_request(db,actor,body,correlation)
        if len(parts)==6 and parts[3]=='requests':
            if parts[5]=='dispatch':
                strict(body,{'expected_version','quantity'})
                return workflow.dispatch(db,actor,parts[4],body,correlation)
            strict(body,{'expected_version','reason'})
            return workflow.transition(db,actor,parts[4],parts[5],body,correlation)
        if len(parts)==6 and parts[3]=='shipments':
            if parts[5]=='receipt-parts':
                strict(body,{'expected_version','receipt_part_id','lines'})
                return workflow.receive(db,actor,parts[4],body,correlation)
            if parts[5]=='reconcile':
                strict(body,{'expected_version','reason'})
                return workflow.reconcile(db,actor,parts[4],body,correlation)
        if path=='/api/v1/inventory-events':
            strict(body,set(COLUMNS)|{'expected_version','source_id'})
            actor.require(['storekeeper','custodian','qa'])
            integer(body.get('expected_version'),'expected_version',0,2**63-1)
            if body['expected_version']!=revision(db):
                raise DomainError('STALE_VERSION','Inventory changed',409,revision(db))
            if body.get('source_id','WORKFLOW')!='WORKFLOW':
                raise DomainError('SOURCE_DENIED','Direct events use the WORKFLOW source',403)
            integer(body.get('quantity'))
            raw={k:body.get(k) for k in COLUMNS}
            # Reuse the exact CSV validation schema; never interpret a numeric unit conversion.
            import csv,io
            out=io.StringIO();w=csv.DictWriter(out,fieldnames=COLUMNS);w.writeheader();w.writerow(raw)
            rows,errors=parse(out.getvalue())
            if errors:
                raise DomainError('INVALID_EVENT','Inventory event validation failed',field_errors=errors)
            row=rows[0]
            actor.require(sites=[row['site_id']])
            if row['event_type'] in ('ISSUE','RELEASE') and date.fromisoformat(row['expiry_date'])<clock.today():
                raise DomainError('EXPIRED_BATCH','Cannot issue or release currently expired stock',409)
            apply_event(db,actor,row,correlation)
            bump(db)
            audit(db,actor.actor_id,'INVENTORY_EVENT',row['event_id'],[row['site_id']],correlation,{'event_type':row['event_type'],'source_ref':row['source_ref']})
            return {'event_id':row['event_id'],'revision':revision(db)}
        if path=='/api/v1/snapshots':
            strict(body,{'site_ids'})
            actor.require(['planner','custodian','auditor'])
            sites=body.get('site_ids',sorted(actor.sites))
            if not isinstance(sites,list) or not sites or any(not isinstance(s,str) for s in sites) or len(set(sites))!=len(sites):
                raise DomainError('INVALID_INPUT','site_ids must be unique site IDs')
            actor.require(sites=sites)
            from .auth import Actor
            scoped=Actor(actor.actor_id,actor.roles,frozenset(sites))
            ts=now();inv=stock(db,scoped)
            data={'schema_version':'1.0','synthetic':True,'created_at':ts,'revision':revision(db),
                  'site_ids':sorted(sites),'inventory':inv,
                  'ledger_cutoff_sequence':db.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0],
                  'demand':self.read(db,scoped,'/api/v1/demand',{},correlation),
                  'policy_version':workflow.POLICY_VERSION,
                  'sources':self.read(db,scoped,'/api/v1/sources',{},correlation)['sources'],
                  'outbound_commitments':[], 'confirmed_inbound':[],
                  'warnings':['Inventory history is not consumed demand. No synthetic forecast history was fabricated.',
                              'Graph/scenario constraints and forecast evaluation belong to Track 2; attach their versions to recommendations.']}
            for r in db.execute("SELECT * FROM requests WHERE status='APPROVED'"):
                reserved=db.execute('SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE request_id=?',(r['request_id'],)).fetchone()[0]
                if r['source_site_id'] in sites:
                    data['outbound_commitments'].append({'request_id':r['request_id'],'site_id':r['source_site_id'],'item_id':r['item_id'],
                                                         'reserved_not_dispatched':reserved,'already_subtracted_from_allocatable':True})
                if r['destination_site_id'] in sites:
                    for s in db.execute("SELECT * FROM shipments WHERE request_id=? AND status!='RECONCILED'",(r['request_id'],)):
                        quantity=db.execute('SELECT COALESCE(SUM(quantity-received),0) FROM shipment_lines WHERE shipment_id=?',(s['shipment_id'],)).fetchone()[0]
                        data['confirmed_inbound'].append({'shipment_id':s['shipment_id'],'site_id':r['destination_site_id'],
                                                          'item_id':r['item_id'],'outstanding_quantity':quantity,'arrival_at':None,
                                                          'warning':'No confirmed arrival time; exclude from dated supply until timing is established'})
            ident=uid('snapshot');h=digest(data)
            db.execute('INSERT INTO snapshots VALUES (?,?,?,?,?,?,?)',(ident,actor.actor_id,canonical(sorted(sites)),revision(db),h,canonical(data),ts))
            audit(db,actor.actor_id,'SNAPSHOT_CREATED',ident,sites,correlation,{'content_sha256':h,'revision':revision(db)})
            return {'snapshot_id':ident,'content_sha256':h,'data':data}
        if path=='/api/v1/physical-counts':
            strict(body,{'count_id','site_id','batch_id','counted_quantity','occurred_at','source_ref','expected_version'})
            actor.require(['custodian'])
            site=text(body.get('site_id'),'site_id',48)
            actor.require(sites=[site])
            integer(body.get('expected_version'),'expected_version',0,2**63-1)
            if body['expected_version']!=revision(db):
                raise DomainError('STALE_VERSION','Stock changed; repeat count reconciliation',409,revision(db))
            count=integer(body.get('counted_quantity'),'counted_quantity',0)
            when=timestamp(body.get('occurred_at'))
            bid=text(body.get('batch_id'),'batch_id',48)
            ident=text(body.get('count_id'),'count_id',80)
            ref=text(body.get('source_ref'),'source_ref',80)
            b=db.execute('SELECT * FROM balances WHERE site_id=? AND batch_id=?',(site,bid)).fetchone()
            if not b:
                raise DomainError('INVALID_BATCH','Batch absent from this site')
            physical=sum(b[k] for k in ('usable','quarantined','damaged','rejected','expired'))
            if count!=physical:
                raise DomainError('COUNT_DISCREPANCY','Count differs from ledger; resolve through authorized evidence events before verifying count',409)
            # A late count must not certify movements posted after the physical observation.
            if when < (b['last_posted_at'] or '') or when < (b['last_physical_count_at'] or ''):
                raise DomainError('STALE_COUNT','Count predates current stock evidence; recount required',409)
            db.execute('INSERT INTO physical_counts VALUES (?,?,?,?,?,?,?,?)',(ident,site,bid,count,actor.actor_id,when,now(),ref))
            db.execute('UPDATE balances SET last_physical_count_at=?,version=version+1 WHERE site_id=? AND batch_id=?',(when,site,bid))
            bump(db)
            audit(db,actor.actor_id,'PHYSICAL_COUNT_VERIFIED',ident,[site],correlation,{'batch_id':bid,'counted_quantity':count,'source_ref':ref})
            return {'count_id':ident,'revision':revision(db),'physical_on_hand':physical,'stock_mutated':False}
        if path=='/api/v1/demand':
            strict(body,{'record_id','site_id','item_id','period','requested','issued','consumed_if_known','returned','unmet','counted_quantity','missing_flag','stockout_flag','source_ref'})
            actor.require(['custodian'])
            actor.require(sites=[text(body.get('site_id'),'site_id',48)])
            item=db.execute('SELECT 1 FROM items WHERE item_id=?',(body.get('item_id'),)).fetchone()
            if not item:
                raise DomainError('UNKNOWN_ITEM','Unknown item')
            try:
                period=date.fromisoformat(body.get('period'))
                if period>clock.today():
                    raise ValueError
            except (TypeError,ValueError):
                raise DomainError('INVALID_INPUT','period must be a nonfuture ISO date') from None
            for flag in ('missing_flag','stockout_flag'):
                if type(body.get(flag)) is not bool:
                    raise DomainError('INVALID_INPUT',flag+' must be boolean')
            for k in ('requested','issued','consumed_if_known','returned','unmet'):
                if body.get(k) is not None:
                    integer(body[k],k,0)
            if body['missing_flag']:
                if any(body.get(k) is not None for k in ('requested','issued','consumed_if_known','returned','unmet')):
                    raise DomainError('INVALID_INPUT','Missing observation quantities must be null, not zero')
            elif any(body.get(k) is None for k in ('requested','issued','returned','unmet')):
                raise DomainError('INVALID_INPUT','Nonmissing observation requires requested, issued, returned and unmet; unknown consumption stays null')
            text(body.get('source_ref'),'source_ref',80)
            ident=text(body.get('record_id'),'record_id',80)
            db.execute('INSERT INTO demand VALUES (?,?,?,?,?,?,?)',(ident,body['site_id'],body['item_id'],str(period),canonical(body),actor.actor_id,now()))
            bump(db)
            audit(db,actor.actor_id,'DEMAND_RECORDED',ident,[body['site_id']],correlation,{'period':str(period)})
            return {'record_id':ident,'revision':revision(db)}
        if path=='/api/v1/observations':
            strict(body,{'schema_version','event_id','site_id','device_id','boot_session','sequence','batch_id','observation_type','value','unit','occurred_at','calibration_status','synthetic'})
            actor.require(['storekeeper'])
            actor.require(sites=[text(body.get('site_id'),'site_id',48)])
            if body.get('schema_version')!='1.0' or body.get('synthetic') is not True:
                raise DomainError('SIMULATION_ONLY','Only explicitly synthetic v1.0 observations are supported')
            for k in ('event_id','device_id','boot_session','batch_id','observation_type','unit','calibration_status'):
                text(body.get(k),k,80)
            integer(body.get('sequence'),'sequence',0,2**53-1)
            timestamp(body.get('occurred_at'))
            if body['observation_type'] not in ('barcode_seen','temperature','humidity'):
                raise DomainError('INVALID_INPUT','Unsupported simulated observation type')
            if body['observation_type'] in ('temperature','humidity'):
                value=body.get('value')
                if type(value) not in (int,float) or not -100<=value<=150:
                    raise DomainError('INVALID_INPUT','Implausible or nonfinite sensor value')
                if (body['observation_type']=='humidity' and (body['unit']!='PERCENT_RH' or not 0<=value<=100)) or (body['observation_type']=='temperature' and body['unit']!='CELSIUS'):
                    raise DomainError('INVALID_UNIT','Wrong sensor unit or range')
            if body['observation_type']=='barcode_seen':
                text(body.get('value'),'value',256)
                if body['unit']!='BARCODE':
                    raise DomainError('INVALID_UNIT','Barcode observations require BARCODE unit')
            b=db.execute('SELECT 1 FROM balances WHERE site_id=? AND batch_id=?',(body['site_id'],body['batch_id'])).fetchone()
            if not b:
                raise DomainError('INVALID_BATCH','Batch is not present at this site')
            old=db.execute('SELECT * FROM observations WHERE event_id=?',(body['event_id'],)).fetchone()
            if old:
                if old['payload_hash']!=digest(body) or old['actor_id']!=actor.actor_id:
                    raise DomainError('OBSERVATION_CONFLICT','Event ID reused',409)
                return {'event_id':body['event_id'],'status':'PROVISIONAL_EVIDENCE','duplicate':True,'stock_mutated':False}
            last=-1
            for r in db.execute('SELECT payload FROM observations WHERE actor_id=?',(actor.actor_id,)):
                p=json.loads(r[0])
                if p['device_id']==body['device_id'] and p['boot_session']==body['boot_session']:
                    last=max(last,p['sequence'])
            if body['sequence']<=last:
                raise DomainError('SEQUENCE_REPLAY','Out-of-order/reused sequence; submit for manual conflict review',409)
            flags=['SEQUENCE_GAP'] if last>=0 and body['sequence']!=last+1 else []
            recorded=now()
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',(body['event_id'],body['site_id'],actor.actor_id,canonical(body),digest(body),recorded))
            audit(db,actor.actor_id,'SIMULATED_OBSERVATION',body['event_id'],[body['site_id']],correlation,{'flags':flags,'stock_mutated':False})
            return {'event_id':body['event_id'],'status':'PROVISIONAL_EVIDENCE','stock_mutated':False,'flags':flags,'recorded_at':recorded}
        raise DomainError('NOT_FOUND','Endpoint not found',404)


def strict(body,allowed):
    nontext={'quantity','input_revision','expected_version','site_ids','lines','requested','issued',
             'consumed_if_known','returned','unmet','counted_quantity','missing_flag','stockout_flag','sequence','value','synthetic'}
    for field in set(body)-nontext:
        if body[field] is not None and not isinstance(body[field],str):
            raise DomainError('INVALID_INPUT',field+' must be text')
    extra=set(body)-allowed
    if extra:
        raise DomainError('INVALID_INPUT','Unknown fields: '+', '.join(sorted(extra)))
