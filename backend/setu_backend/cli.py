"""python -m setu_backend.cli --help"""
import argparse
import json
import os
from pathlib import Path
from .db import initialize,connect,transaction
from .auth import provision
from .recovery import backup,verify


def main():
    p=argparse.ArgumentParser(description='Setu Supply synthetic Track 1 backend')
    p.add_argument('--db',default=os.getenv('SETU_DB','setu.sqlite3'))
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    d=sub.add_parser('demo-users');d.add_argument('--output',default='demo-secrets.env')
    a=sub.add_parser('actor');a.add_argument('actor_id');a.add_argument('--roles',required=True);a.add_argument('--sites',required=True)
    r=sub.add_parser('revoke');r.add_argument('actor_id')
    s=sub.add_parser('serve');s.add_argument('--host',default='127.0.0.1');s.add_argument('--port',type=int,default=8000)
    s.add_argument('--origins',default=os.getenv('SETU_CORS_ORIGINS','http://localhost:5173,http://localhost:3000'))
    b=sub.add_parser('backup');b.add_argument('target')
    sub.add_parser('verify')
    args=p.parse_args()
    if args.command=='init':
        initialize(args.db);print('Initialized synthetic database');return
    if not Path(args.db).is_file():
        p.error('Database does not exist; run init first')
    if args.command=='serve':
        from .server import serve
        serve(args.db,args.host,args.port,[v.strip() for v in args.origins.split(',') if v.strip()]);return
    if args.command=='backup':
        print(json.dumps(backup(args.db,args.target),indent=2));return
    if args.command=='verify':
        result=verify(args.db);print(json.dumps(result,indent=2));raise SystemExit(0 if result['valid'] else 1)
    db=connect(args.db)
    try:
        if args.command=='actor':
            print(provision(db,args.actor_id,args.roles.split(','),args.sites.split(',')))
        elif args.command=='revoke':
            with transaction(db):
                db.execute('UPDATE actors SET active=0 WHERE actor_id=?',(args.actor_id,))
            print('Actor revoked')
        elif args.command=='demo-users':
            # Refuse overwrite, keep generated tokens private, never store them in Git.
            fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:
                for role in ('custodian','storekeeper','planner','approver','dispatcher','receiver','qa','auditor','admin'):
                    token=provision(db,'demo-'+role,[role],['DEMO_A','DEMO_B'])
                    f.write('SETU_'+role.upper()+'_TOKEN='+token+'\n')
            print('Created private token file: '+args.output)
    finally:
        db.close()

if __name__=='__main__':
    main()
