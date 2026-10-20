import concurrent.futures
import csv
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, timedelta, datetime, timezone
from unittest.mock import patch
from setu_backend import clock
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from setu_backend.db import initialize,connect,transaction,now,canonical,digest
from setu_backend.auth import provision,DomainError
from setu_backend.service import Service
from setu_backend.recovery import verify,backup
from setu_backend.server import Server
from setu_backend.csv_schema import COLUMNS

CSV=Path(__file__).resolve().parents[1]/'data/synthetic_inventory_events.csv'


class BackendCase(unittest.TestCase):
    def setUp(self):
        self.clock_patch=patch('setu_backend.clock.utcnow',return_value=datetime(2026,10,20,12,0,0,tzinfo=timezone.utc))
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'test.sqlite3'
        initialize(self.path)
        self.svc=Service(self.path)
        self.tokens={}
        db=connect(self.path)
        for role in ('custodian','storekeeper','planner','approver','dispatcher','receiver','qa','auditor','admin'):
            self.tokens[role]=provision(db,role,[role],['DEMO_A','DEMO_B'])
        self.tokens['single']=provision(db,'single',['storekeeper','custodian','planner','auditor','receiver'],['DEMO_A'])
        self.tokens['self']=provision(db,'self',['planner','approver'],['DEMO_A','DEMO_B'])
        db.close()
        self.counter=0

    def tearDown(self):
        self.tmp.cleanup()

    def call(self,role,method,path,body=None,key=None,query=None):
        self.counter+=1
        return self.svc.call(self.tokens.get(role,role),method,'/api/v1/'+path,body,key or 'test-'+str(self.counter),query)

    def post(self,role,path,body,key=None):
        return self.call(role,'POST',path,body,key)

    def read(self,path='inventory',role='planner',query=None):
        return self.call(role,'GET',path,query=query)

    def imported(self,csv_text=None,role='custodian'):
        data={'source_id':'SIH_SYNTHETIC_CSV','csv_text':csv_text or CSV.read_text()}
        preview=self.post(role,'imports/validate',data)
        self.assertTrue(preview['valid'],preview)
        return self.post(role,'imports/commit',{**data,'preview_id':preview['preview_id']})

    def draft(self,qty=50,role='planner'):
        return self.post(role,'requests',{'source_site_id':'DEMO_A','destination_site_id':'DEMO_B','item_id':'WATER_1L',
                    'quantity':qty,'input_revision':self.read()['revision'],'reason':'Synthetic replenishment'})

    def submitted(self,qty=50,role='planner'):
        r=self.draft(qty,role)
        return self.post(role,'requests/'+r['request_id']+'/submit',{'expected_version':r['version']})

    def approved(self,qty=50):
        r=self.submitted(qty)
        return self.post('approver','requests/'+r['request_id']+'/approve',{'expected_version':r['version'],'reason':'Reviewed physical evidence'})

    def shipment(self,qty=50):
        r=self.approved(qty)
        return self.post('dispatcher','requests/'+r['request_id']+'/dispatch',{'expected_version':r['version'],'quantity':qty})

    def receipt(self,s,accepted,quarantined=0,damaged=0,rejected=0,key=None,part='part-1'):
        return self.post('receiver','shipments/'+s['shipment_id']+'/receipt-parts',{
            'expected_version':s['version'],'receipt_part_id':part,
            'lines':[{'batch_id':s['lines'][0]['batch_id'],'accepted':accepted,'quarantined':quarantined,'damaged':damaged,'rejected':rejected}]},key)

    def assertCode(self,code,fn):
        with self.assertRaises(DomainError) as cm:
            fn()
        self.assertEqual(code,cm.exception.code,str(cm.exception))
        return cm.exception

    def event(self,kind='RECEIPT',qty=4,batch='WATER_A1',eid='MANUAL_1'):
        return {'event_id':eid,'site_id':'DEMO_A','item_id':'WATER_1L','batch_id':batch,'event_type':kind,
                'quantity':qty,'base_unit':'BOTTLE','occurred_at':now(),'expiry_date':'2027-04-30',
                'source_ref':'manual-evidence','expected_version':self.read()['revision']}

    def test_supplied_csv_expected_stock_and_duplicates(self):
        first=self.imported();self.assertEqual(9,first['accepted_rows'])
        inv=self.read();by={b['batch_id']:b for b in inv['batches']}
        self.assertEqual(265,by['WATER_A1']['usable']);self.assertEqual(60,by['WATER_A2']['usable'])
        self.assertEqual(90,by['WATER_B1']['usable']);self.assertEqual(134,by['RATIONS_A1']['usable'])
        self.assertEqual(108,by['MED_A1']['usable']);self.assertEqual(12,by['MED_A1']['quarantined'])
        second=self.imported();self.assertEqual(0,second['accepted_rows']);self.assertEqual(9,second['unchanged_duplicate_rows'])
        self.assertEqual(inv['revision'],self.read()['revision']);self.assertTrue(verify(self.path)['valid'])

    def test_preview_has_no_stock_effect(self):
        self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()})
        self.assertEqual([],self.read()['batches'])

    def test_invalid_import_atomic(self):
        bad=CSV.read_text().replace('ISSUE,35','ISSUE,999999')
        p=self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':bad})
        self.assertFalse(p['valid']);self.assertIsNone(p['preview_id']);self.assertEqual([],self.read()['batches'])

    def test_changed_duplicate_rejected(self):
        self.imported()
        p=self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text().replace('OPENING,300','OPENING,301')})
        self.assertFalse(p['valid']);self.assertEqual(9,len(self.read('events')['records']))

    def test_preview_bound_to_actor_and_payload(self):
        p=self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()})
        self.assertCode('PREVIEW_MISMATCH',lambda:self.post('single','imports/commit',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text(),'preview_id':p['preview_id']}))
        self.assertCode('PREVIEW_MISMATCH',lambda:self.post('custodian','imports/commit',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()+'\n','preview_id':p['preview_id']}))

    def test_commit_retry_returns_original(self):
        body={'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()}
        p=self.post('custodian','imports/validate',body);body['preview_id']=p['preview_id']
        self.assertEqual(self.post('custodian','imports/commit',body),self.post('custodian','imports/commit',body))
        self.assertEqual(9,len(self.read('events')['records']))

    def test_stale_preview_rejected(self):
        body={'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()}
        p=self.post('custodian','imports/validate',body)
        self.imported()
        self.assertCode('STALE_VERSION',lambda:self.post('custodian','imports/commit',{**body,'preview_id':p['preview_id']}))

    def test_invalid_csv_types_and_shape(self):
        for text in [None,'',CSV.read_text().replace('BOTTLE','LITRE'),CSV.read_text().replace('OPENING,300','OPENING,NaN'),
                     CSV.read_text().replace('EV002','EV001'),CSV.read_text().replace('2026-10-01T09:00:00Z','2026-10-01T09:00:00'),
                     CSV.read_text().replace('DEMO_A','UNKNOWN'),CSV.read_text().replace('OPENING,300','OPENING,-3'),CSV.read_text()+'\x00']:
            with self.subTest(text=str(text)[:40]):
                p=self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':text})
                self.assertFalse(p['valid'])
        self.assertEqual([],self.read()['batches'])

    def test_unauthenticated_and_admin_cannot_operate(self):
        self.assertCode('UNAUTHENTICATED',lambda:self.read(role='invalid-token-value'))
        self.assertCode('FORBIDDEN',lambda:self.post('admin','requests',{}))
        self.assertCode('FORBIDDEN',lambda:self.post('planner','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()}))

    def test_cross_site_reads_and_imports(self):
        self.imported()
        self.assertEqual({'DEMO_A'},{r['site_id'] for r in self.read(role='single')['batches']})
        self.assertCode('FORBIDDEN',lambda:self.read(role='single',query={'site_id':'DEMO_B'}))
        self.assertCode('FORBIDDEN',lambda:self.post('single','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':CSV.read_text()}))
        self.assertCode('FORBIDDEN',lambda:self.post('single','snapshots',{'site_ids':['DEMO_A','DEMO_B']}))
        self.assertEqual({'DEMO_A'},{r['site_id'] for r in self.read('events',role='single')['records']})

    def test_self_approval_is_denied(self):
        self.imported();r=self.submitted(role='self')
        self.assertCode('SELF_APPROVAL',lambda:self.post('self','requests/'+r['request_id']+'/approve',{'expected_version':r['version'],'reason':'self'}))
        self.assertEqual(0,sum(b['reserved'] for b in self.read()['batches']))

    def test_stale_approval(self):
        self.imported();r=self.submitted()
        self.post('storekeeper','inventory-events',self.event())
        self.assertCode('STALE_VERSION',lambda:self.post('approver','requests/'+r['request_id']+'/approve',{'expected_version':r['version'],'reason':'reviewed'}))

    def test_atomic_fefo_reservation(self):
        self.imported()
        self.post('custodian','physical-counts',{'count_id':'count-a2','site_id':'DEMO_A','batch_id':'WATER_A2',
                  'counted_quantity':60,'occurred_at':now(),'source_ref':'observed-receipt-count','expected_version':self.read()['revision']})
        r=self.approved(280)
        by={b['batch_id']:b for b in self.read()['batches']}
        self.assertEqual(265,by['WATER_A1']['reserved']);self.assertEqual(15,by['WATER_A2']['reserved'])
        self.assertEqual(0,by['WATER_A1']['allocatable']);self.assertEqual(45,by['WATER_A2']['allocatable'])
        self.assertEqual(280,r['reserved_quantity']);self.assertTrue(verify(self.path)['valid'])

    def test_insufficient_reservation_rolls_back(self):
        self.imported()
        self.assertCode('INSUFFICIENT_STOCK',lambda:self.approved(326))
        self.assertEqual(0,sum(b['reserved'] for b in self.read()['batches']))
        self.assertTrue(verify(self.path)['valid'])

    def test_concurrent_last_stock_cannot_double_reserve(self):
        self.imported();a=self.submitted(250);b=self.submitted(250)
        barrier=threading.Barrier(2)
        def reserve(r):
            barrier.wait()
            try:
                return self.svc.call(self.tokens['approver'],'POST','/api/v1/requests/'+r['request_id']+'/approve',
                    {'expected_version':r['version'],'reason':'race'},r['request_id'])['status']
            except DomainError as e:
                return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            result=list(pool.map(reserve,[a,b]))
        self.assertEqual(1,result.count('APPROVED'));self.assertIn('STALE_VERSION',result)
        self.assertEqual(250,sum(b['reserved'] for b in self.read()['batches']))
        self.assertTrue(verify(self.path)['valid'])

    def test_dispatch_requires_approval_and_role(self):
        self.imported();r=self.submitted()
        self.assertCode('INVALID_STATE',lambda:self.post('dispatcher','requests/'+r['request_id']+'/dispatch',{'expected_version':r['version'],'quantity':50}))
        self.assertCode('FORBIDDEN',lambda:self.post('planner','requests/'+r['request_id']+'/dispatch',{'expected_version':r['version'],'quantity':50}))

    def test_partial_dispatch_receipt_reconcile_close(self):
        self.imported();r=self.approved(50)
        a=self.post('dispatcher','requests/'+r['request_id']+'/dispatch',{'expected_version':r['version'],'quantity':30})
        r=self.read('requests/'+r['request_id'])
        self.assertEqual(20,r['reserved_quantity']);self.assertEqual(30,r['dispatched_quantity'])
        b=self.post('dispatcher','requests/'+r['request_id']+'/dispatch',{'expected_version':r['version'],'quantity':20})
        a=self.receipt(a,20,quarantined=4,damaged=3,rejected=2)
        self.assertEqual(1,a['unresolved_quantity']);self.assertEqual('PARTIALLY_RECEIVED',a['status'])
        self.assertCode('UNRESOLVED',lambda:self.post('approver','shipments/'+a['shipment_id']+'/reconcile',{'expected_version':a['version'],'reason':'premature'}))
        a=self.receipt(a,1,part='part-2')
        self.post('approver','shipments/'+a['shipment_id']+'/reconcile',{'expected_version':a['version'],'reason':'Damage and rejection accepted as recorded dispositions'})
        b=self.receipt(b,20,part='part-3')
        self.post('approver','shipments/'+b['shipment_id']+'/reconcile',{'expected_version':b['version'],'reason':'received'})
        r=self.read('requests/'+r['request_id'])
        closed=self.post('approver','requests/'+r['request_id']+'/close',{'expected_version':r['version']})
        self.assertEqual('CLOSED',closed['status'])
        moved=next(x for x in self.read()['batches'] if x['site_id']=='DEMO_B' and x['batch_id']=='WATER_A1')
        self.assertEqual(50,moved['physical_on_hand']);self.assertEqual(41,moved['usable']);self.assertEqual(4,moved['quarantined'])
        self.assertEqual(3,moved['damaged']);self.assertEqual(2,moved['rejected'])
        self.assertTrue(verify(self.path)['valid'])

    def test_over_receipt_no_partial_writes(self):
        self.imported();s=self.shipment()
        before=self.read()
        self.assertCode('OVER_RECEIPT',lambda:self.receipt(s,51))
        self.assertEqual(before['batches'],self.read()['batches']);self.assertEqual(before['revision'],self.read()['revision'])

    def test_duplicate_receipt_and_conflicting_key(self):
        self.imported();s=self.shipment()
        first=self.receipt(s,25,key='receipt-once')
        second=self.receipt(s,25,key='receipt-once')
        self.assertEqual(first,second)
        self.assertCode('IDEMPOTENCY_CONFLICT',lambda:self.receipt(s,26,key='receipt-once'))
        self.assertEqual(25,self.read('shipments/'+s['shipment_id'])['unresolved_quantity'])

    def test_cancel_releases_reservations(self):
        self.imported();r=self.approved()
        r=self.post('planner','requests/'+r['request_id']+'/cancel',{'expected_version':r['version']})
        self.assertEqual('CANCELLED',r['status']);self.assertEqual(0,sum(b['reserved'] for b in self.read()['batches']))

    def test_cannot_cancel_after_dispatch(self):
        self.imported();s=self.shipment();r=self.read('requests/'+s['request_id'])
        self.assertCode('INVALID_STATE',lambda:self.post('planner','requests/'+r['request_id']+'/cancel',{'expected_version':r['version']}))

    def test_qa_only_release(self):
        self.imported();e=self.event('RELEASE',5,'MED_A1');e.update(item_id='BANDAGE_STD',base_unit='PACK',expiry_date='2027-01-31')
        self.assertCode('FORBIDDEN',lambda:self.post('storekeeper','inventory-events',e))
        self.post('qa','inventory-events',e)
        med=next(b for b in self.read()['batches'] if b['batch_id']=='MED_A1')
        self.assertEqual(113,med['usable']);self.assertEqual(7,med['quarantined'])

    def test_expired_stock_is_never_allocatable(self):
        old=(clock.today()-timedelta(days=3)).isoformat();expiry=(clock.today()-timedelta(days=1)).isoformat()
        text='event_id,site_id,item_id,batch_id,event_type,quantity,base_unit,occurred_at,expiry_date,source_ref\n'
        text+=f'OLD,DEMO_A,WATER_1L,OLD,OPENING,10,BOTTLE,{old}T00:00:00Z,{expiry},old\n'
        self.imported(text)
        b=self.read()['batches'][0]
        self.assertEqual(10,b['physical_on_hand']);self.assertEqual(0,b['usable']);self.assertEqual(10,b['expired'])
        self.assertCode('INSUFFICIENT_STOCK',lambda:self.approved(1))
        self.assertCode('INVALID_EVENT',lambda:self.post('storekeeper','inventory-events',dict(self.event('ISSUE',1,'OLD'),expiry_date=expiry)))

    def test_reserved_stock_cannot_be_issued(self):
        self.imported();self.approved(265)
        self.assertCode('INSUFFICIENT_STOCK',lambda:self.post('storekeeper','inventory-events',self.event('ISSUE',1)))

    def test_batch_metadata_immutable(self):
        self.imported();e=self.event();e['expiry_date']='2027-05-30'
        self.assertCode('BATCH_CONFLICT',lambda:self.post('storekeeper','inventory-events',e))

    def test_immutable_snapshot_and_no_fabricated_demand(self):
        self.imported();snap=self.post('planner','snapshots',{})
        self.assertEqual([],snap['data']['demand']['records'])
        self.assertIn('NO_DEMAND_HISTORY',snap['data']['demand']['warnings'][0])
        self.post('storekeeper','inventory-events',self.event())
        self.assertEqual(snap,self.read('snapshots/'+snap['snapshot_id']))
        self.assertEqual(digest(snap['data']),snap['content_sha256'])
        self.assertCode('NOT_FOUND',lambda:self.read('snapshots/'+snap['snapshot_id'],role='single'))

    def test_inbound_separate_and_reserved_not_double_subtracted(self):
        self.imported();s=self.shipment(20)
        snap=self.post('planner','snapshots',{})['data']
        self.assertEqual(20,snap['confirmed_inbound'][0]['outstanding_quantity'])
        self.assertIsNone(snap['confirmed_inbound'][0]['arrival_at'])
        self.assertEqual(90,sum(b['usable'] for b in snap['inventory']['batches'] if b['site_id']=='DEMO_B'))
        self.assertTrue(snap['outbound_commitments'][0]['already_subtracted_from_allocatable'])

    def test_missing_demand_is_null_and_consumed_is_distinct(self):
        body={'record_id':'D1','site_id':'DEMO_A','item_id':'WATER_1L','period':'2026-10-19','requested':None,'issued':None,
              'consumed_if_known':None,'returned':None,'unmet':None,'missing_flag':True,'stockout_flag':False,'source_ref':'synthetic-test'}
        self.post('custodian','demand',body)
        self.assertIsNone(self.read('demand')['records'][0]['consumed_if_known'])
        self.assertCode('INVALID_INPUT',lambda:self.post('custodian','demand',dict(body,record_id='D2',period='2026-10-18',issued=0)))

    def test_fault_during_audit_rolls_back_business_and_idempotency(self):
        self.imported();db=connect(self.path)
        db.execute("CREATE TRIGGER fail_test BEFORE INSERT ON audit WHEN NEW.action='INVENTORY_EVENT' BEGIN SELECT RAISE(ABORT,'injected failure'); END;")
        db.close();before=self.read()
        self.assertCode('CONFLICT',lambda:self.post('storekeeper','inventory-events',self.event(),key='failed-event'))
        self.assertEqual(before['batches'],self.read()['batches']);self.assertEqual(before['revision'],self.read()['revision'])
        db=connect(self.path);self.assertEqual(0,db.execute("SELECT count(*) FROM idempotency WHERE key='failed-event'").fetchone()[0]);db.close()

    def test_restart_and_backup_restore(self):
        self.imported();r=self.approved();self.svc=Service(self.path)
        self.assertEqual('APPROVED',self.read('requests/'+r['request_id'])['status'])
        target=Path(self.tmp.name)/'restored.sqlite3';self.assertTrue(backup(self.path,target)['valid'])
        restored=Service(target).call(self.tokens['planner'],'GET','/api/v1/inventory')
        self.assertEqual(self.read()['batches'],restored['batches'])
        self.assertEqual(self.read()['revision'],restored['revision'])

    def test_append_only_and_audit_verification(self):
        self.imported();db=connect(self.path)
        with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM events')
        with self.assertRaises(sqlite3.IntegrityError): db.execute("UPDATE audit SET outcome='X'")
        db.close();self.assertTrue(verify(self.path)['valid'])

    def test_detect_projection_tampering(self):
        self.imported();db=connect(self.path)
        db.execute("UPDATE balances SET usable=usable+1 WHERE batch_id='WATER_A1'");db.close()
        self.assertFalse(verify(self.path)['valid'])

    def observation(self,seq=1,eid='obs-1'):
        return {'schema_version':'1.0','event_id':eid,'site_id':'DEMO_A','device_id':'sim-reader','boot_session':'boot-1',
                'sequence':seq,'batch_id':'WATER_A1','observation_type':'barcode_seen','value':'WATER_A1','unit':'BARCODE',
                'occurred_at':now(),'calibration_status':'SIMULATED','synthetic':True}

    def test_simulated_observation_no_stock_mutation_and_sequence_replay(self):
        self.imported();before=self.read();body=self.observation()
        self.post('storekeeper','observations',body,key='obs-one')
        dup=self.post('storekeeper','observations',body,key='obs-dup')
        self.assertTrue(dup['duplicate']);self.assertFalse(dup['stock_mutated'])
        self.assertCode('SEQUENCE_REPLAY',lambda:self.post('storekeeper','observations',self.observation(1,'obs-2')))
        gap=self.post('storekeeper','observations',self.observation(3,'obs-3'))
        self.assertIn('SEQUENCE_GAP',gap['flags']);self.assertEqual(before['batches'],self.read()['batches'])
        self.assertEqual(before['revision'],self.read()['revision'])

    def test_observation_rejects_real_and_implausible(self):
        self.imported();body=self.observation()
        self.assertCode('SIMULATION_ONLY',lambda:self.post('storekeeper','observations',dict(body,synthetic=False)))
        self.assertCode('INVALID_INPUT',lambda:self.post('storekeeper','observations',dict(body,observation_type='temperature',value=1000,unit='CELSIUS')))

    def test_wrong_types_and_forged_actor(self):
        self.imported()
        self.assertCode('INVALID_INPUT',lambda:self.post('planner','requests',{'item_id':[]}))
        self.assertCode('INVALID_INPUT',lambda:self.post('storekeeper','inventory-events',dict(self.event(),actor_id='approver')))
        self.assertCode('INVALID_INPUT',lambda:self.post('planner','snapshots',{'site_ids':[[]]}))

    def test_auditor_scope_and_revocation(self):
        self.imported()
        self.assertCode('FORBIDDEN',lambda:self.read('audit',role='planner'))
        self.assertTrue(self.read('audit',role='auditor')['records'])
        db=connect(self.path);db.execute("UPDATE actors SET active=0 WHERE actor_id='planner'");db.close()
        self.assertCode('UNAUTHENTICATED',lambda:self.read())

    def test_matching_physical_count_and_mismatch_no_overwrite(self):
        self.imported()
        body={'count_id':'PC-1','site_id':'DEMO_A','batch_id':'WATER_A2','counted_quantity':59,
              'occurred_at':now(),'source_ref':'human-count','expected_version':self.read()['revision']}
        self.assertCode('COUNT_DISCREPANCY',lambda:self.post('custodian','physical-counts',body))
        before=self.read()
        result=self.post('custodian','physical-counts',dict(body,counted_quantity=60,occurred_at=now()))
        self.assertFalse(result['stock_mutated'])
        after=self.read();self.assertGreater(after['revision'],before['revision'])
        self.assertEqual(sum(b['physical_on_hand'] for b in before['batches']),sum(b['physical_on_hand'] for b in after['batches']))
        self.assertTrue(next(b for b in after['batches'] if b['batch_id']=='WATER_A2')['last_physical_count_at'])

    def test_count_cannot_certify_late_observation(self):
        self.imported()
        self.assertCode('STALE_COUNT',lambda:self.post('custodian','physical-counts',{
            'count_id':'old-count','site_id':'DEMO_A','batch_id':'WATER_A2','counted_quantity':60,
            'occurred_at':'2026-10-15T12:01:00Z','source_ref':'late-count','expected_version':self.read()['revision']}))

    def test_batch_without_count_blocks_allocation(self):
        self.imported()
        self.assertCode('STALE_COUNT',lambda:self.approved(280))
        self.assertEqual(0,sum(b['reserved'] for b in self.read()['batches']))

    def test_stale_posting_blocks_approval(self):
        self.imported();r=self.submitted()
        db=connect(self.path);db.execute("UPDATE balances SET last_posted_at='2026-10-01T10:00:00Z'");db.close()
        self.assertCode('STALE_DATA',lambda:self.post('approver','requests/'+r['request_id']+'/approve',{'expected_version':r['version'],'reason':'stale'}))

    def test_concurrent_identical_approval_returns_one_result(self):
        self.imported();r=self.submitted(50);barrier=threading.Barrier(2)
        def approve(_):
            barrier.wait()
            return self.svc.call(self.tokens['approver'],'POST','/api/v1/requests/'+r['request_id']+'/approve',
                                  {'expected_version':r['version'],'reason':'once'},'one-key')
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(approve,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(50,sum(b['reserved'] for b in self.read()['batches']))
        self.assertEqual(1,sum(d['action']=='approve' for d in results[0]['decisions']))

    def test_concurrent_receipts_cannot_over_receive(self):
        self.imported();s=self.shipment(50);barrier=threading.Barrier(2)
        def receive(i):
            barrier.wait()
            body={'expected_version':s['version'],'receipt_part_id':'parallel-'+str(i),
                  'lines':[{'batch_id':s['lines'][0]['batch_id'],'accepted':30,'quarantined':0,'damaged':0,'rejected':0}]}
            try:
                return self.svc.call(self.tokens['receiver'],'POST','/api/v1/shipments/'+s['shipment_id']+'/receipt-parts',body,'receipt-'+str(i))['unresolved_quantity']
            except DomainError as e:return e.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:result=list(pool.map(receive,range(2)))
        self.assertCountEqual([20,'STALE_VERSION'],result);self.assertTrue(verify(self.path)['valid'])

    def test_destination_only_receiver_and_denied_wrong_destination(self):
        self.imported();s=self.shipment()
        db=connect(self.path)
        self.tokens['dest']=provision(db,'dest',['receiver'],['DEMO_B']);db.close()
        body={'expected_version':s['version'],'receipt_part_id':'scoped-receipt',
              'lines':[{'batch_id':s['lines'][0]['batch_id'],'accepted':10,'quarantined':0,'damaged':0,'rejected':0}]}
        self.assertCode('FORBIDDEN',lambda:self.post('single','shipments/'+s['shipment_id']+'/receipt-parts',body))
        result=self.post('dest','shipments/'+s['shipment_id']+'/receipt-parts',body)
        self.assertEqual(40,result['unresolved_quantity'])
        self.assertCode('FORBIDDEN',lambda:self.read(role='dest',query={'site_id':'DEMO_A'}))

    def test_approval_reason_does_not_overwrite_request_reason(self):
        self.imported();r=self.approved()
        self.assertEqual('Synthetic replenishment',r['reason'])
        decision=next(d for d in r['decisions'] if d['action']=='approve')
        self.assertEqual('Reviewed physical evidence',decision['reason'])
        self.assertEqual('approver',decision['actor_id'])

    def test_snapshots_and_decisions_are_append_only(self):
        self.imported();self.post('planner','snapshots',{});self.approved()
        db=connect(self.path)
        for table in ('snapshots','decisions'):
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM '+table)
        db.close()

    def test_oversize_csv_is_bounded(self):
        p=self.post('custodian','imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':'x'*2_000_001})
        self.assertFalse(p['valid']);self.assertEqual([],self.read()['batches'])

    def test_expiry_cannot_be_backdated_to_shrink_stock_early(self):
        self.imported()
        self.assertCode('INVALID_EXPIRY',lambda:self.post('storekeeper','inventory-events',self.event('EXPIRE',1)))

    def test_http_contract_auth_errors_and_cors(self):
        server=Server(('127.0.0.1',0),self.svc,['http://localhost:5173'])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_address[1])
        try:
            with urlopen(base+'/api/v1/health') as response:
                self.assertTrue(json.load(response)['synthetic'])
            with urlopen(base+'/openapi.json') as response:
                spec=json.load(response);self.assertIn('/api/v1/requests/{request_id}/approve',spec['paths'])
            for headers,body,code in [({},None,401),({'Authorization':'Bearer '+self.tokens['planner'],'Origin':'http://evil.test'},None,403),
                ({'Authorization':'Bearer '+self.tokens['planner'],'Content-Type':'application/json'},b'{"site_ids":[],"site_ids":[]}',400)]:
                req=Request(base+'/api/v1/'+('snapshots' if body else 'inventory'),data=body,headers=headers)
                with self.assertRaises(HTTPError) as cm:urlopen(req)
                self.assertEqual(code,cm.exception.code);payload=json.load(cm.exception);self.assertIn('correlation_id',payload)
            with urlopen(Request(base+'/api/v1/inventory',headers={'Authorization':'Bearer '+self.tokens['planner'],'Origin':'http://localhost:5173'})) as response:
                self.assertEqual('http://localhost:5173',response.headers['Access-Control-Allow-Origin'])
                self.assertEqual('no-store',response.headers['Cache-Control'])
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
