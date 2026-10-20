"""Run a real HTTP import and fulfilment demonstration. Never prints credentials."""
import argparse
import json
import uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--base-url',default='http://127.0.0.1:8000')
    p.add_argument('--secrets',default='demo-secrets.env')
    p.add_argument('--csv',default=str(Path(__file__).parent/'data/synthetic_inventory_events.csv'))
    p.add_argument('--import-only',action='store_true')
    args=p.parse_args()
    tokens={}
    for line in Path(args.secrets).read_text().splitlines():
        if line and not line.startswith('#'):
            k,v=line.split('=',1);tokens[k]=v
    def call(role,method,path,body=None,key=None):
        data=json.dumps(body).encode() if body is not None else None
        headers={'Authorization':'Bearer '+tokens['SETU_'+role.upper()+'_TOKEN']}
        if data is not None:
            headers.update({'Content-Type':'application/json','Idempotency-Key':key or uuid.uuid4().hex})
        req=Request(args.base_url+'/api/v1/'+path,data=data,headers=headers,method=method)
        try:
            with urlopen(req,timeout=20) as response:
                return json.load(response)
        except HTTPError as exc:
            raise SystemExit(f'HTTP {exc.code}: {exc.read().decode()}') from None
    body={'source_id':'SIH_SYNTHETIC_CSV','csv_text':Path(args.csv).read_text()}
    preview=call('custodian','POST','imports/validate',body)
    if not preview['valid']:
        raise SystemExit(json.dumps(preview,indent=2))
    result=call('custodian','POST','imports/commit',{**body,'preview_id':preview['preview_id']})
    print('Import:',json.dumps(result))
    if args.import_only:
        return
    snap=call('planner','POST','snapshots',{})
    request=call('planner','POST','requests',{'source_site_id':'DEMO_A','destination_site_id':'DEMO_B','item_id':'WATER_1L',
            'quantity':20,'input_revision':snap['data']['revision'],'snapshot_id':snap['snapshot_id'],'reason':'Synthetic general-supply demonstration'})
    rid=request['request_id']
    request=call('planner','POST','requests/'+rid+'/submit',{'expected_version':request['version']})
    request=call('approver','POST','requests/'+rid+'/approve',{'expected_version':request['version'],'reason':'Independent demo review'})
    shipment=call('dispatcher','POST','requests/'+rid+'/dispatch',{'expected_version':request['version'],'quantity':20})
    sid=shipment['shipment_id'];batch=shipment['lines'][0]['batch_id']
    for quantity in (12,8):
        shipment=call('receiver','POST','shipments/'+sid+'/receipt-parts',{'expected_version':shipment['version'],
              'receipt_part_id':'part_'+uuid.uuid4().hex,'lines':[{'batch_id':batch,'accepted':quantity,'quarantined':0,'damaged':0,'rejected':0}]})
        print('Receipt:',quantity,'unresolved:',shipment['unresolved_quantity'])
    call('approver','POST','shipments/'+sid+'/reconcile',{'expected_version':shipment['version'],'reason':'Both physical parts reconciled'})
    request=call('planner','GET','requests/'+rid)
    request=call('approver','POST','requests/'+rid+'/close',{'expected_version':request['version']})
    print('Request:',rid,request['status'],'Shipment:',sid)
    print('Audit records:',len(call('auditor','GET','audit')['records']))

if __name__=='__main__':main()
