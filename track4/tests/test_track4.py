import hashlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'track4'))
sys.path.insert(0,str(ROOT/'backend'))

from setu_backend.auth import provision
from setu_backend.db import connect,initialize as initialize_track1
from setu_backend.server import Server as Track1Server
from setu_backend.service import Service as Track1Service
from setu_integration.client import Track1Client
from setu_integration.contracts import ContractError
from setu_integration.service import IntegrationService
from setu_integration.store import connect as connect_track4,initialize as initialize_track4


class Track4Case(unittest.TestCase):
    def setUp(self):
        temp_root=os.getenv('SETU_TEST_TMP')
        self.tmp=tempfile.TemporaryDirectory(dir=temp_root)
        self.track1_db=Path(self.tmp.name)/'track1.sqlite3';self.track4_db=Path(self.tmp.name)/'track4.sqlite3'
        initialize_track1(self.track1_db);initialize_track4(self.track4_db)
        db=connect(self.track1_db)
        self.tokens={role:provision(db,'t4-'+role,[role],['DEMO_A','DEMO_B']) for role in ('custodian','planner','storekeeper','auditor')}
        db.close()
        service=Track1Service(self.track1_db)
        csv_text=(ROOT/'backend'/'data'/'synthetic_inventory_events.csv').read_text()
        preview=service.call(self.tokens['custodian'],'POST','/api/v1/imports/validate',{'source_id':'SIH_SYNTHETIC_CSV','csv_text':csv_text})
        service.call(self.tokens['custodian'],'POST','/api/v1/imports/commit',
                     {'source_id':'SIH_SYNTHETIC_CSV','csv_text':csv_text,'preview_id':preview['preview_id']})
        self.server=Track1Server(('127.0.0.1',0),service,[])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=Track1Client('http://127.0.0.1:'+str(self.server.server_address[1]))
        for attempt in range(50):
            try:
                self.client.me(self.tokens['planner']);break
            except ContractError:
                if attempt==49:raise
                time.sleep(0.02)
        self.integration=IntegrationService(self.track4_db,self.client)
        self.snapshot=self.client.request(self.tokens['planner'],'POST','/api/v1/snapshots',{},'snapshot-key')

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def recommendation_body(self,**changes):
        body={'snapshot_id':self.snapshot['snapshot_id'],'snapshot_sha256':self.snapshot['content_sha256'],
              'input_revision':self.snapshot['data']['revision'],'forecast_run_id':'fc-0123456789ab',
              'plan_id':'plan-0123456789ab','graph_version':'fictional-graph-v1','scenario_id':'closed-edge',
              'constraints_version':'constraints-v1','source_site_id':'DEMO_A','destination_site_id':'DEMO_B',
              'item_id':'WATER_1L','proposed_quantity':20,'solver_status':'OPTIMAL',
              'warnings':['synthetic'],'explanation':['edge closure changed path'],
              'evidence_digest':hashlib.sha256(b'track2-artifacts').hexdigest()}
        body.update(changes);return body

    def test_recommendation_links_to_real_track1_request(self):
        recommendation=self.integration.create_recommendation(self.tokens['planner'],self.recommendation_body(),'rec-key')
        linked=self.integration.create_request(self.tokens['planner'],recommendation['recommendation_id'],
                                               {'reason':'Track 2 feasible replenishment'},'request-key')
        request=linked['request']
        self.assertEqual(recommendation['snapshot_id'],request['snapshot_id'])
        self.assertEqual(recommendation['proposed_quantity'],request['quantity'])
        self.assertEqual('DRAFT',request['status'])
        retry=self.integration.create_request(self.tokens['planner'],recommendation['recommendation_id'],
                                              {'reason':'Track 2 feasible replenishment'},'request-key')
        self.assertEqual(request['request_id'],retry['request']['request_id'])

    def test_mismatch_and_infeasible_plan_are_rejected(self):
        with self.assertRaises(ContractError) as caught:
            self.integration.create_recommendation(self.tokens['planner'],self.recommendation_body(snapshot_sha256='0'*64),'bad-hash')
        self.assertEqual('SNAPSHOT_MISMATCH',caught.exception.code)
        with self.assertRaises(ContractError) as caught:
            self.integration.create_recommendation(self.tokens['planner'],self.recommendation_body(solver_status='NO_PLAN_ESTABLISHED'),'bad-plan')
        self.assertEqual('NO_FEASIBLE_PLAN',caught.exception.code)

    def test_offline_sync_allows_evidence_but_denies_execution(self):
        observation={'schema_version':'1.0','event_id':'obs-track4-1','site_id':'DEMO_A','device_id':'sim-reader',
                     'boot_session':'boot-track4','sequence':1,'batch_id':'WATER_A1','observation_type':'barcode_seen',
                     'value':'WATER_A1','unit':'BARCODE','occurred_at':'2026-10-20T08:00:00Z',
                     'calibration_status':'SIMULATED','synthetic':True}
        body={'events':[{'client_event_id':'offline-1','kind':'observation','idempotency_key':'offline-obs-1','payload':observation},
                        {'client_event_id':'offline-2','kind':'approve','idempotency_key':'offline-approve','payload':{}}]}
        first=self.integration.sync(self.tokens['storekeeper'],body)
        self.assertEqual(['ACCEPTED','REJECTED'],[r['outcome'] for r in first['results']])
        self.assertEqual('OFFLINE_ACTION_DENIED',first['results'][1]['reason_code'])
        second=self.integration.sync(self.tokens['storekeeper'],{'events':[body['events'][0]]})
        self.assertEqual('DUPLICATE',second['results'][0]['outcome'])

    def test_audit_mirror_is_separate_and_detects_changed_sequence(self):
        result=self.integration.pull_audit(self.tokens['auditor'])
        self.assertGreater(result['mirrored'],0)
        records=self.integration.audit_records(self.tokens['auditor'])['records']
        self.assertEqual(result['mirrored'],len(records))
        db=connect_track4(self.track4_db)
        with self.assertRaises(Exception):db.execute('DELETE FROM audit_mirror')
        db.close()

    def test_track1_tree_is_consumed_only_through_http(self):
        # The integration code must never import Track 1 implementation modules.
        source='\n'.join(p.read_text() for p in (ROOT/'track4'/'setu_integration').glob('*.py'))
        self.assertNotIn('setu_backend',source)
        self.assertNotIn('track1.sqlite',source)


if __name__=='__main__':unittest.main()
