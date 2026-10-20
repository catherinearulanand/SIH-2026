"""Application service joining Track 2 evidence to Track 1 through public APIs only."""
import json
from .contracts import ContractError,validate_recommendation
from .store import connect,get_recommendation,idempotent,mirror_records,now,save_recommendation,transaction


class IntegrationService:
    def __init__(self,path,track1_client):
        self.path=path;self.track1=track1_client

    @staticmethod
    def require(actor,role=None,sites=()):
        roles=set(actor.get('roles',[]));scope=set(actor.get('sites',[]))
        if role and role not in roles:
            raise ContractError('FORBIDDEN','Insufficient role authority',403)
        if not set(sites)<=scope:
            raise ContractError('FORBIDDEN','Site scope denied',403)

    def create_recommendation(self,token,body,key):
        actor=self.track1.me(token);self.require(actor,'planner')
        data=validate_recommendation(body)
        self.require(actor,sites=[data['source_site_id'],data['destination_site_id']])
        snapshot=self.track1.snapshot(token,data['snapshot_id'])
        if snapshot.get('content_sha256')!=data['snapshot_sha256']:
            raise ContractError('SNAPSHOT_MISMATCH','Snapshot digest does not match Track 1',409)
        snapshot_data=snapshot.get('data',{})
        if snapshot_data.get('revision')!=data['input_revision']:
            raise ContractError('SNAPSHOT_MISMATCH','Snapshot revision does not match Track 2 evidence',409,
                                snapshot_data.get('revision'))
        if not {data['source_site_id'],data['destination_site_id']}<=set(snapshot_data.get('site_ids',[])):
            raise ContractError('SNAPSHOT_MISMATCH','Snapshot does not cover both transfer sites',409)
        db=connect(self.path)
        try:
            return idempotent(db,actor['actor_id'],'create-recommendation',key,data,
                              lambda:save_recommendation(db,actor,data))[0]
        finally:
            db.close()

    def recommendation(self,token,ident):
        actor=self.track1.me(token);db=connect(self.path)
        try:return get_recommendation(db,ident,actor)
        finally:db.close()

    def create_request(self,token,ident,body,key):
        if not isinstance(body,dict) or set(body)!={'reason'} or not isinstance(body['reason'],str) or not 1<=len(body['reason'])<=1000:
            raise ContractError('INVALID_INPUT','reason must be 1..1000 characters')
        actor=self.track1.me(token);self.require(actor,'planner')
        db=connect(self.path)
        try:
            recommendation=get_recommendation(db,ident,actor)
            self.require(actor,sites=[recommendation['source_site_id'],recommendation['destination_site_id']])
            payload={'source_site_id':recommendation['source_site_id'],'destination_site_id':recommendation['destination_site_id'],
                     'item_id':recommendation['item_id'],'quantity':recommendation['proposed_quantity'],
                     'input_revision':recommendation['input_revision'],'snapshot_id':recommendation['snapshot_id'],'reason':body['reason']}
            def action():
                linked=db.execute('SELECT request_id FROM request_links WHERE recommendation_id=?',(ident,)).fetchone()
                if linked:
                    raise ContractError('RECOMMENDATION_ALREADY_USED','Recommendation already created a request',409)
                request=self.track1.create_request(token,payload,'track4-'+key)
                db.execute('INSERT INTO request_links VALUES (?,?,?,?)',(ident,request['request_id'],actor['actor_id'],now()))
                return {'recommendation_id':ident,'request':request}
            return idempotent(db,actor['actor_id'],'create-request:'+ident,key,body,action)[0]
        finally:
            db.close()

    def sync(self,token,body):
        actor=self.track1.me(token)
        if not isinstance(body,dict) or set(body)!={'events'} or not isinstance(body['events'],list) or not 1<=len(body['events'])<=100:
            raise ContractError('INVALID_INPUT','events must contain 1..100 entries')
        results=[]
        for entry in body['events']:
            client_id=entry.get('client_event_id') if isinstance(entry,dict) else None
            result={'client_event_id':client_id,'server_object_id':None,'current_version':None}
            if not isinstance(entry,dict) or set(entry)!={'client_event_id','kind','idempotency_key','payload'}:
                results.append({**result,'outcome':'REJECTED','reason_code':'INVALID_SYNC_ENTRY'});continue
            key=entry['idempotency_key'];payload=entry['payload'];kind=entry['kind']
            try:
                if kind=='observation':
                    db=connect(self.path)
                    try:
                        response,replayed=idempotent(db,actor['actor_id'],'sync-observation',key,payload,
                                                    lambda:self.track1.post_observation(token,payload,key))
                    finally:
                        db.close()
                    results.append({**result,'outcome':'DUPLICATE' if replayed or response.get('duplicate') else 'ACCEPTED',
                                    'reason_code':None,'server_object_id':response.get('event_id')})
                elif kind=='request_draft':
                    if not isinstance(payload,dict) or set(payload)!={'recommendation_id','reason'}:
                        raise ContractError('INVALID_SYNC_ENTRY','request_draft payload is invalid')
                    response=self.create_request(token,payload['recommendation_id'],{'reason':payload['reason']},key)
                    results.append({**result,'outcome':'ACCEPTED','reason_code':None,
                                    'server_object_id':response['request']['request_id'],
                                    'current_version':response['request']['version']})
                else:
                    raise ContractError('OFFLINE_ACTION_DENIED','Only observation and request_draft may be replayed offline',403)
            except ContractError as exc:
                results.append({**result,'outcome':'CONFLICT' if exc.status==409 else 'REJECTED',
                                'reason_code':exc.code,'current_version':exc.current_version})
        return {'results':results,'recorded_at':now(),'actor_id':actor['actor_id']}

    def pull_audit(self,token,limit=100):
        actor=self.track1.me(token);self.require(actor,'auditor')
        db=connect(self.path)
        try:
            cursor=int(db.execute("SELECT value FROM metadata WHERE key='track1_audit_cursor'").fetchone()[0])
            feed=self.track1.audit(token,cursor,limit)
            added=mirror_records(db,feed.get('records',[]))
            return {'mirrored':added,'next_after':feed.get('next_after',cursor)}
        finally:db.close()

    def audit_records(self,token,after=0,limit=100):
        actor=self.track1.me(token);self.require(actor,'auditor')
        if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=500:
            raise ContractError('INVALID_INPUT','after and limit are invalid')
        db=connect(self.path)
        try:
            rows=[]
            for row in db.execute('SELECT * FROM audit_mirror WHERE track1_sequence>? ORDER BY track1_sequence LIMIT ?',(after,limit)):
                value=dict(row);value['payload']=json.loads(value['payload']);rows.append(value)
            return {'records':rows,'next_after':rows[-1]['track1_sequence'] if rows else after}
        finally:db.close()
