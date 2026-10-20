"""Dependency-free OpenAPI 3.1 contract, exported to docs/openapi.json."""


def specification():
    string={'type':'string','minLength':1}
    qty={'type':'integer','minimum':1,'maximum':10000000}
    zero={'type':'integer','minimum':0,'maximum':10000000}
    ver={'type':'integer','minimum':1}
    integer={'type':'integer','minimum':0}
    paths={}
    error={'description':'Structured domain error','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Error'}}}}
    def route(path,method,summary,properties=None,required=None,parameters=None):
        params=list(parameters or [])
        for var in ('request_id','shipment_id','snapshot_id'):
            if '{'+var+'}' in path:
                params.append({'name':var,'in':'path','required':True,'schema':string})
        if method=='post' and '/imports/' not in path:
            params.append({'name':'Idempotency-Key','in':'header','required':True,'schema':{'type':'string','minLength':1,'maxLength':128}})
        operation={'summary':summary,'operationId':method+'_'+path.strip('/').replace('/','_').replace('{','').replace('}','').replace('-','_'),
                   'security':[{'bearerAuth':[]}],'parameters':params,
                   'responses':{'200':{'description':'Success; see docs/TRACK1_HANDOFF.md for field semantics','content':{'application/json':{'schema':{'type':'object'}}}},
                                **{str(c):error for c in (401,403,404,409,422,413,503)}}}
        if properties is not None:
            operation['requestBody']={'required':True,'content':{'application/json':{'schema':{'type':'object','additionalProperties':False,
                'properties':properties,'required':list(properties) if required is None else required}}}}
        paths.setdefault(path,{})[method]=operation
    root='/api/v1'
    for name in ('me','catalog','sources','requests','shipments'):
        route(root+'/'+name,'get','Read scoped '+name)
    params=[{'name':n,'in':'query','schema':string} for n in ('site_id','item_id')]
    route(root+'/inventory','get','Batch stock, allocatable quantities, freshness and revision',parameters=params)
    route(root+'/demand','get','Demand observations; empty unless explicitly supplied',parameters=params[:1])
    for name in ('events','audit'):
        route(root+'/'+name,'get','Scoped ledger cursor' if name=='events' else 'Auditor-only scoped audit cursor',parameters=[
            {'name':'after','in':'query','schema':integer},{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':500}}])
    for entity,var in (('requests','request_id'),('shipments','shipment_id'),('snapshots','snapshot_id')):
        route(root+'/'+entity+'/{'+var+'}','get','Read scoped '+entity)
    imp={'source_id':{'type':'string','const':'SIH_SYNTHETIC_CSV'},'csv_text':{'type':'string','maxLength':2000000}}
    route(root+'/imports/validate','post','Validate all rows without committing stock; preview expires in 15 minutes',imp)
    route(root+'/imports/commit','post','Commit original actor-bound preview atomically',dict(imp,preview_id=string,preview_sha256=string),['source_id','csv_text','preview_id'])
    route(root+'/requests','post','Create DRAFT using current revision',{'source_site_id':string,'destination_site_id':string,'item_id':string,'quantity':qty,
        'input_revision':integer,'snapshot_id':string,'reason':string},['source_site_id','destination_site_id','item_id','quantity','input_revision','reason'])
    for action in ('submit','approve','reject','cancel','close'):
        route(root+'/requests/{request_id}/'+action,'post','Transition request: '+action+(' and atomically reserve FEFO stock' if action=='approve' else ''),
              {'expected_version':ver,'reason':string},['expected_version','reason'] if action in ('approve','reject') else ['expected_version'])
    route(root+'/requests/{request_id}/dispatch','post','Record partial authorized dispatch',{'expected_version':ver,'quantity':qty})
    disposition={'type':'object','additionalProperties':False,'properties':{'batch_id':string,'accepted':zero,'quarantined':zero,'damaged':zero,'rejected':zero},
                 'required':['batch_id','accepted','quarantined','damaged','rejected']}
    route(root+'/shipments/{shipment_id}/receipt-parts','post','Append a partial receipt; dispositions partition physical quantity',
          {'expected_version':ver,'receipt_part_id':string,'lines':{'type':'array','minItems':1,'maxItems':100,'items':disposition}})
    route(root+'/shipments/{shipment_id}/reconcile','post','Acknowledge complete physical receipt and dispositions',{'expected_version':ver,'reason':string})
    route(root+'/snapshots','post','Freeze immutable scoped planning inputs',{'site_ids':{'type':'array','minItems':1,'uniqueItems':True,'items':string}},[])
    fields={k:string for k in ('event_id','site_id','item_id','batch_id','event_type','base_unit','occurred_at','expiry_date','source_ref')}
    fields['quantity']=qty;fields['expected_version']=integer
    route(root+'/inventory-events','post','Append authorized stock event; RELEASE requires qa',dict(fields,source_id=string),list(fields))
    route(root+'/physical-counts','post','Verify an attributable physical count without replacing ledger balances',
          {'count_id':string,'site_id':string,'batch_id':string,'counted_quantity':zero,'occurred_at':string,'source_ref':string,'expected_version':integer})
    demand={k:string for k in ('record_id','site_id','item_id','period','source_ref')}
    demand.update({k:{'type':['integer','null'],'minimum':0,'maximum':10000000} for k in ('requested','issued','consumed_if_known','returned','unmet')})
    demand.update(missing_flag={'type':'boolean'},stockout_flag={'type':'boolean'})
    route(root+'/demand','post','Append sourced daily demand observation; quantities null when missing',demand)
    observation={k:string for k in ('schema_version','event_id','site_id','device_id','boot_session','batch_id','observation_type','unit','occurred_at','calibration_status')}
    observation.update(sequence=integer,value={'type':['string','number','null']},synthetic={'type':'boolean','const':True})
    route(root+'/observations','post','Actor-attributed simulated evidence only; never changes stock',observation)
    for path in ('/api/v1/health','/openapi.json'):
        paths[path]={'get':{'summary':'Public health' if 'health' in path else 'OpenAPI contract','security':[],
                            'responses':{'200':{'description':'Success'}}}}
    spec = {'openapi':'3.1.0','info':{'title':'Setu Supply — Track 1','version':'1.0.0',
           'description':'Synthetic ordinary-supply demonstration. No Army connector. Local SQLite transaction authority.'},
           'servers':[{'url':'http://127.0.0.1:8000'}],'paths':paths,
           'components':{'securitySchemes':{'bearerAuth':{'type':'http','scheme':'bearer'}},
                         'schemas':{'Error':{'type':'object','properties':{'code':{'type':'string'},'message':{'type':'string'},
                          'field_errors':{'type':'array','items':{'type':'object'}},'correlation_id':{'type':'string'},'current_version':{'type':['integer','null']}}}}}}

    schemas=spec['components']['schemas']
    def obj(properties,required=None):
        return {'type':'object','properties':properties,'required':list(properties) if required is None else required}
    def ref(name):
        return {'$ref':'#/components/schemas/'+name}
    def array(item):
        return {'type':'array','items':item}
    nullable_time={'type':['string','null']}
    schemas['StockBatch']=obj({**{k:string for k in ('site_id','item_id','batch_id','base_unit','expiry_date')},
        **{k:integer for k in ('usable','quarantined','quality_quarantined','damaged','rejected','expired','reserved','version','allocatable','physical_on_hand','quality_unavailable')},
        'expiry_blocked':{'type':'boolean'},**{k:nullable_time for k in ('last_observed_at','last_posted_at','last_physical_count_at','last_synchronization_at')},
        'synchronization_warning':string})
    schemas['Inventory']=obj({'schema_version':string,'revision':integer,'as_of':string,'synthetic':{'const':True},'batches':array(ref('StockBatch'))})
    schemas['Decision']=obj({**{k:string for k in ('decision_id','request_id','actor_id','action','reason','policy_version','server_time')},
        **{k:integer for k in ('before_version','after_version','input_revision')}})
    schemas['Reservation']=obj({'request_id':string,'batch_id':string,'quantity':integer,'dispatched':integer})
    schemas['SupplyRequest']=obj({**{k:string for k in ('request_id','creator_id','source_site_id','destination_site_id','item_id','policy_version','reason','created_at','updated_at')},
        'quantity':qty,'version':ver,'input_revision':integer,'snapshot_id':nullable_time,'approver_id':nullable_time,
        'status':{'enum':['DRAFT','SUBMITTED','APPROVED','REJECTED','CANCELLED','CLOSED']},
        'reserved_quantity':integer,'dispatched_quantity':integer,'reservations':array(ref('Reservation')),'decisions':array(ref('Decision'))})
    schemas['ShipmentLine']=obj({'shipment_id':string,'batch_id':string,'quantity':qty,'received':integer})
    schemas['Shipment']=obj({**{k:string for k in ('shipment_id','request_id','source_site_id','destination_site_id','item_id','created_at')},
        'version':ver,'status':{'enum':['DISPATCH_RECORDED','PARTIALLY_RECEIVED','RECONCILED']},
        'unresolved_quantity':integer,'lines':array(ref('ShipmentLine')),'receipt_parts':array({'type':'object'})})
    schemas['DemandRecords']=obj({'schema_version':string,'records':array({'type':'object'}),'warnings':array(string)})
    schemas['SnapshotData']=obj({'schema_version':string,'synthetic':{'const':True},'created_at':string,'revision':integer,'site_ids':array(string),
        'inventory':ref('Inventory'),'ledger_cutoff_sequence':integer,'demand':ref('DemandRecords'),'policy_version':string,
        'sources':array({'type':'object'}),'outbound_commitments':array({'type':'object'}),'confirmed_inbound':array({'type':'object'}),'warnings':array(string)})
    schemas['Snapshot']=obj({'snapshot_id':string,'content_sha256':string,'data':ref('SnapshotData')})
    schemas['ImportPreview']=obj({'valid':{'type':'boolean'},'accepted_rows':integer,'unchanged_duplicate_rows':integer,'errors':array({'type':'object'}),
        'source_id':string,'preview_id':nullable_time,'preview_sha256':nullable_time,'revision':integer})
    def response(path,method,schema):
        paths[path][method]['responses']['200']['content']['application/json']['schema']=schema
    response(root+'/inventory','get',ref('Inventory'))
    response(root+'/demand','get',ref('DemandRecords'))
    response(root+'/requests','get',obj({'requests':array(ref('SupplyRequest'))}))
    response(root+'/shipments','get',obj({'shipments':array(ref('Shipment'))}))
    response(root+'/requests','post',ref('SupplyRequest'))
    response(root+'/requests/{request_id}','get',ref('SupplyRequest'))
    response(root+'/shipments/{shipment_id}','get',ref('Shipment'))
    response(root+'/snapshots/{snapshot_id}','get',ref('Snapshot'))
    response(root+'/snapshots','post',ref('Snapshot'))
    response(root+'/imports/validate','post',ref('ImportPreview'))
    for action in ('submit','approve','reject','cancel','close'):
        response(root+'/requests/{request_id}/'+action,'post',ref('SupplyRequest'))
    response(root+'/requests/{request_id}/dispatch','post',ref('Shipment'))
    for action in ('receipt-parts','reconcile'):
        response(root+'/shipments/{shipment_id}/'+action,'post',ref('Shipment'))
    return spec
