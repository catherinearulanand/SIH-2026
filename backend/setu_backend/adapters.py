"""Connector boundary only. No Army, CICP, MISO or ERP connector is implemented."""
from typing import Protocol
from pathlib import Path

class InventorySourceAdapter(Protocol):
    source_id: str
    def read_csv(self) -> str: ...

class SyntheticCSVAdapter:
    source_id='SIH_SYNTHETIC_CSV'
    def __init__(self,path):
        self.path=Path(path)
    def read_csv(self):
        # Caller still must run the authenticated preview/commit API. Reading is not authority.
        if self.path.stat().st_size>2_000_000:
            raise ValueError('CSV exceeds 2 MB')
        return self.path.read_text(encoding='utf-8-sig')
