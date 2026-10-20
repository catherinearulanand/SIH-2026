"""python -m setu_integration.cli --help"""
import argparse
import os
from pathlib import Path
from .client import Track1Client
from .service import IntegrationService
from .store import initialize


def main():
    parser=argparse.ArgumentParser(description='Setu Supply Track 4 integration sidecar')
    parser.add_argument('--db',default=os.getenv('SETU_INTEGRATION_DB','setu-integration.sqlite3'))
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    serve_parser=sub.add_parser('serve')
    serve_parser.add_argument('--track1-url',default=os.getenv('SETU_TRACK1_URL','http://127.0.0.1:8000'))
    serve_parser.add_argument('--host',default='127.0.0.1');serve_parser.add_argument('--port',type=int,default=8010)
    args=parser.parse_args()
    if args.command=='init':
        initialize(args.db);print('Initialized Track 4 integration database');return
    if not Path(args.db).is_file():parser.error('Integration database does not exist; run init first')
    from .server import serve
    serve(IntegrationService(args.db,Track1Client(args.track1_url)),args.host,args.port)


if __name__=='__main__':main()
