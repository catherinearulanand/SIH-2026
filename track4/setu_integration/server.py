"""Small local HTTP transport for the Track 4 sidecar."""
import json
import socket
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import parse_qs,urlsplit
from .contracts import ContractError


MAX_BODY=1_000_000


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,service):
        self.service=service
        super().__init__(address,Handler)


class Handler(BaseHTTPRequestHandler):
    server_version='SetuIntegration/0.1';sys_version=''
    def log_message(self,format,*args):pass

    def reply(self,status,value):
        raw=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)

    def do_GET(self):self.handle_api('GET')
    def do_POST(self):self.handle_api('POST')

    def handle_api(self,method):
        try:
            url=urlsplit(self.path)
            if method=='GET' and url.path=='/api/v1/integration/health':
                return self.reply(200,{'status':'ok','track':'integration-security','version':'0.1.0'})
            auth=self.headers.get('Authorization','')
            if not auth.startswith('Bearer '):raise ContractError('UNAUTHENTICATED','Bearer token required',401)
            token=auth[7:];body=None
            if method=='POST':
                length=self.headers.get('Content-Length')
                if not length or not length.isdigit():raise ContractError('INVALID_INPUT','Valid Content-Length required',411)
                if int(length)>MAX_BODY:raise ContractError('PAYLOAD_TOO_LARGE','Request too large',413)
                if self.headers.get_content_type()!='application/json':raise ContractError('INVALID_INPUT','JSON required',415)
                body=json.loads(self.rfile.read(int(length)).decode(),object_pairs_hook=unique_object)
            key=self.headers.get('Idempotency-Key')
            parts=url.path.split('/')
            if method=='POST' and url.path=='/api/v1/integration/recommendations':
                result=self.server.service.create_recommendation(token,body,key)
            elif method=='GET' and len(parts)==6 and parts[4]=='recommendations':
                result=self.server.service.recommendation(token,parts[5])
            elif method=='POST' and len(parts)==7 and parts[4]=='recommendations' and parts[6]=='requests':
                result=self.server.service.create_request(token,parts[5],body,key)
            elif method=='POST' and url.path=='/api/v1/integration/sync':
                result=self.server.service.sync(token,body)
            elif method=='POST' and url.path=='/api/v1/integration/audit/pull':
                result=self.server.service.pull_audit(token)
            elif method=='GET' and url.path=='/api/v1/integration/audit':
                query=parse_qs(url.query);result=self.server.service.audit_records(token,int(query.get('after',['0'])[0]),int(query.get('limit',['100'])[0]))
            else:raise ContractError('NOT_FOUND','Endpoint not found',404)
            self.reply(200,result)
        except ContractError as exc:
            self.reply(exc.status,{'code':exc.code,'message':exc.message,'current_version':exc.current_version,'field_errors':[]})
        except (json.JSONDecodeError,UnicodeError,ValueError,TypeError):
            self.reply(400,{'code':'INVALID_INPUT','message':'Malformed request','current_version':None,'field_errors':[]})
        except (BrokenPipeError,ConnectionResetError,socket.timeout):pass


def serve(service,host='127.0.0.1',port=8010):
    server=Server((host,port),service)
    print(f'Setu Track 4 integration API: http://{host}:{port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
