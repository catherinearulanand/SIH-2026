"""HTTP-only adapter for the frozen Track 1 public contract."""
import json
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .contracts import ContractError


class Track1Client:
    def __init__(self,base_url,timeout=10):
        self.base_url=base_url.rstrip('/');self.timeout=timeout

    def request(self,token,method,path,body=None,idempotency_key=None,query=None):
        url=self.base_url+path
        if query:
            url+='?'+urlencode(query)
        headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
        raw=None
        if method=='POST':
            raw=json.dumps(body,separators=(',',':'),allow_nan=False).encode()
            headers['Content-Type']='application/json'
            if idempotency_key:
                headers['Idempotency-Key']=idempotency_key
        try:
            with urlopen(Request(url,data=raw,headers=headers,method=method),timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                payload=json.load(exc)
            except Exception:
                payload={}
            raise ContractError(payload.get('code','TRACK1_ERROR'),payload.get('message','Track 1 request failed'),
                                exc.code,payload.get('current_version')) from None
        except URLError:
            raise ContractError('TRACK1_UNAVAILABLE','Track 1 service is unavailable',503) from None

    def me(self,token):
        return self.request(token,'GET','/api/v1/me')

    def snapshot(self,token,snapshot_id):
        return self.request(token,'GET','/api/v1/snapshots/'+snapshot_id)

    def create_request(self,token,body,key):
        return self.request(token,'POST','/api/v1/requests',body,key)

    def post_observation(self,token,body,key):
        return self.request(token,'POST','/api/v1/observations',body,key)

    def audit(self,token,after=0,limit=100):
        return self.request(token,'GET','/api/v1/audit',query={'after':str(after),'limit':str(limit)})
