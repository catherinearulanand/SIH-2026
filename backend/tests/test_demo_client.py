"""Full HTTP rehearsal using the actual bootstrap CLI and teammate client script."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime,timezone
from unittest.mock import patch
from pathlib import Path
from setu_backend.server import Server
from setu_backend.service import Service
from setu_backend.recovery import backup

BACKEND=Path(__file__).resolve().parents[1]

class DemoClientTest(unittest.TestCase):
    @patch('setu_backend.clock.utcnow',return_value=datetime(2026,10,20,12,0,0,tzinfo=timezone.utc))
    def test_bootstrap_http_demo_and_backup(self,_clock):
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'demo.sqlite3';secrets=Path(directory)/'secrets.env'
            def run(*args):
                return subprocess.run([sys.executable,*args],cwd=BACKEND,check=True,capture_output=True,text=True).stdout
            run('-m','setu_backend.cli','--db',str(db),'init')
            run('-m','setu_backend.cli','--db',str(db),'demo-users','--output',str(secrets))
            server=Server(('127.0.0.1',0),Service(db))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                args=['demo_client.py','--base-url','http://127.0.0.1:'+str(server.server_address[1]),'--secrets',str(secrets)]
                first=run(*args,'--import-only');second=run(*args,'--import-only');flow=run(*args)
                self.assertIn('"accepted_rows": 9',first)
                self.assertIn('"accepted_rows": 0',second)
                self.assertIn('"unchanged_duplicate_rows": 9',second)
                self.assertIn('unresolved: 8',flow);self.assertIn('unresolved: 0',flow)
                self.assertIn('CLOSED',flow)
                self.assertTrue(backup(db,Path(directory)/'backup.sqlite3')['valid'])
            finally:
                server.shutdown();server.server_close();thread.join()
