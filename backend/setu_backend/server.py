"""Bounded standard-library JSON transport. Local synthetic demo; TLS at approved proxy."""
import json
import logging
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .auth import DomainError
from .db import uid
from .service import Service

MAX_BODY=2_100_000
LOG=logging.getLogger('setu')


def unique_object(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:
            raise ValueError('Duplicate JSON key')
        obj[k]=v
    return obj


class Server(ThreadingHTTPServer):
    daemon_threads=True
    request_queue_size=32
    def __init__(self,address,service,origins=()):
        self.service=service
        self.origins=frozenset(origins)
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)

    def process_request(self,request,client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request,client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self,request,client_address):
        try:
            super().process_request_thread(request,client_address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version='SetuSupply/1.0'
    sys_version=''
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self,format,*args):
        # No headers, bodies, bearer tokens, URL query strings or user text in logs.
        pass

    def reply(self,status,data,correlation):
        payload=json.dumps(data,separators=(',',':'),allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('X-Correlation-ID',correlation)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        origin=self.headers.get('Origin')
        if origin in self.server.origins:
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
            self.send_header('Access-Control-Expose-Headers','X-Correlation-ID')
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        corr=uid('corr')
        if self.headers.get('Origin') not in self.server.origins:
            return self.reply(403,{'code':'ORIGIN_DENIED','message':'Origin not allowed','correlation_id':corr},corr)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',self.headers['Origin'])
        self.send_header('Vary','Origin')
        self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type, Idempotency-Key')
        self.send_header('Access-Control-Max-Age','600')
        self.send_header('Content-Length','0')
        self.end_headers()

    def do_GET(self):
        self.handle_api('GET')

    def do_POST(self):
        self.handle_api('POST')

    def handle_api(self,method):
        corr=uid('corr')
        try:
            url=urlsplit(self.path)
            if len(self.path)>2048:
                raise DomainError('INVALID_INPUT','URL too long',414)
            if self.headers.get('Origin') and self.headers['Origin'] not in self.server.origins:
                raise DomainError('ORIGIN_DENIED','Origin not allowed',403)
            if method=='GET' and url.path=='/api/v1/health':
                return self.reply(200,{'status':'ok','schema_version':'1.0','synthetic':True},corr)
            if method=='GET' and url.path=='/openapi.json':
                from .openapi import specification
                return self.reply(200,specification(),corr)
            auth=self.headers.get('Authorization','')
            if not auth.startswith('Bearer '):
                raise DomainError('UNAUTHENTICATED','Bearer token required',401)
            query=parse_qs(url.query,keep_blank_values=True,max_num_fields=12)
            if any(len(v)!=1 for v in query.values()):
                raise DomainError('INVALID_INPUT','Repeated query fields are not supported')
            allowed_query={'site_id','item_id','after','limit'}
            if set(query)-allowed_query:
                raise DomainError('INVALID_INPUT','Unknown query fields')
            body=None
            if method=='POST':
                if self.headers.get('Transfer-Encoding'):
                    raise DomainError('INVALID_INPUT','Chunked requests are unsupported',400)
                lengths=self.headers.get_all('Content-Length') or []
                if len(lengths)!=1 or not lengths[0].isdigit():
                    raise DomainError('INVALID_INPUT','One valid Content-Length required',411)
                length=int(lengths[0])
                if length>MAX_BODY:
                    raise DomainError('PAYLOAD_TOO_LARGE','Request exceeds 2.1 MB',413)
                if self.headers.get_content_type()!='application/json':
                    raise DomainError('INVALID_INPUT','Content-Type must be application/json',415)
                raw=self.rfile.read(length)
                if len(raw)!=length:
                    raise DomainError('INVALID_INPUT','Incomplete request',400)
                try:
                    body=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_object,
                                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                except (UnicodeError,ValueError,RecursionError):
                    raise DomainError('INVALID_JSON','Malformed, duplicate-key or nonfinite JSON',400) from None
            result=self.server.service.call(auth[7:],method,url.path,body,self.headers.get('Idempotency-Key'),
                                            {k:v[0] for k,v in query.items()},corr)
            self.reply(200,result,corr)
        except DomainError as exc:
            self.reply(exc.status,{'code':exc.code,'message':exc.message,'field_errors':exc.field_errors,
                                   'correlation_id':corr,'current_version':exc.current_version},corr)
        except (BrokenPipeError,ConnectionResetError,socket.timeout):
            pass
        except (ValueError,TypeError):
            self.reply(422,{'code':'INVALID_INPUT','message':'Invalid request value','field_errors':[],
                            'correlation_id':corr,'current_version':None},corr)
        except Exception:
            LOG.exception('Internal error correlation=%s',corr)
            self.reply(500,{'code':'INTERNAL_ERROR','message':'Operation failed; no partial transaction committed',
                            'field_errors':[],'correlation_id':corr,'current_version':None},corr)


def serve(path,host='127.0.0.1',port=8000,origins=()):
    server=Server((host,port),Service(path),origins)
    print(f'Setu Supply synthetic API: http://{host}:{port}; schema: /openapi.json',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
