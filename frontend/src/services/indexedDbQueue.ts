/**
 * Setu Supply (SIH26251) — IndexedDB Offline Evidence Queue & Snapshot Cache (Section 5 & 10)
 *
 * Implements:
 * 1. Last verified site snapshot cache with conspicuous timestamps.
 * 2. Provisional offline evidence queue (requests, counts, receipt parts, simulated scans,
 *    and blank supervised evidence when cached authority expires).
 * 3. Bounded offline authorization lease state.
 */

import { OfflineEvidenceItem, SiteSnapshot } from '../contracts/api';

const DB_NAME = 'setu_supply_offline_db';
const DB_VERSION = 1;
const STORE_QUEUE = 'evidence_queue';
const STORE_SNAPSHOTS = 'site_snapshots';

const FALLBACK_QUEUE_KEY = 'setu_supply_fallback_queue_v1';
const FALLBACK_SNAP_KEY = 'setu_supply_fallback_snapshots_v1';

function openDatabase(): Promise<IDBDatabase | null> {
  if (typeof indexedDB === 'undefined') {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    try {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE_QUEUE)) {
          const queueStore = db.createObjectStore(STORE_QUEUE, { keyPath: 'queue_id' });
          queueStore.createIndex('by_client_event_id', 'client_event_id', { unique: false });
          queueStore.createIndex('by_site_id', 'site_id', { unique: false });
        }
        if (!db.objectStoreNames.contains(STORE_SNAPSHOTS)) {
          db.createObjectStore(STORE_SNAPSHOTS, { keyPath: 'site_id' });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

export async function cacheSiteSnapshot(snapshot: SiteSnapshot): Promise<void> {
  const db = await openDatabase();
  if (db) {
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE_SNAPSHOTS, 'readwrite');
      tx.objectStore(STORE_SNAPSHOTS).put(snapshot);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }
  try {
    const raw = localStorage.getItem(FALLBACK_SNAP_KEY);
    const map: Record<string, SiteSnapshot> = raw ? JSON.parse(raw) : {};
    map[snapshot.site_id] = snapshot;
    localStorage.setItem(FALLBACK_SNAP_KEY, JSON.stringify(map));
  } catch {
    // Ignore storage quota errors
  }
}

export async function getCachedSiteSnapshot(siteId: string): Promise<SiteSnapshot | null> {
  const db = await openDatabase();
  if (db) {
    const found = await new Promise<SiteSnapshot | null>((resolve) => {
      const tx = db.transaction(STORE_SNAPSHOTS, 'readonly');
      const req = tx.objectStore(STORE_SNAPSHOTS).get(siteId);
      req.onsuccess = () => resolve((req.result as SiteSnapshot) || null);
      req.onerror = () => resolve(null);
    });
    if (found) return found;
  }
  try {
    const raw = localStorage.getItem(FALLBACK_SNAP_KEY);
    if (!raw) return null;
    const map: Record<string, SiteSnapshot> = JSON.parse(raw);
    return map[siteId] || null;
  } catch {
    return null;
  }
}

export async function listOfflineEvidenceQueue(): Promise<OfflineEvidenceItem[]> {
  const db = await openDatabase();
  if (db) {
    const items = await new Promise<OfflineEvidenceItem[] | null>((resolve) => {
      const tx = db.transaction(STORE_QUEUE, 'readonly');
      const req = tx.objectStore(STORE_QUEUE).getAll();
      req.onsuccess = () => resolve((req.result as OfflineEvidenceItem[]) || []);
      req.onerror = () => resolve(null);
    });
    if (items) {
      return items.sort((a, b) => b.created_at_local.localeCompare(a.created_at_local));
    }
  }
  try {
    const raw = localStorage.getItem(FALLBACK_QUEUE_KEY);
    const items: OfflineEvidenceItem[] = raw ? JSON.parse(raw) : [];
    return items.sort((a, b) => b.created_at_local.localeCompare(a.created_at_local));
  } catch {
    return [];
  }
}

export async function enqueueOfflineEvidence(item: OfflineEvidenceItem): Promise<OfflineEvidenceItem> {
  const existing = await listOfflineEvidenceQueue();
  const nextList = [item, ...existing.filter((x) => x.queue_id !== item.queue_id)];

  const db = await openDatabase();
  if (db) {
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE_QUEUE, 'readwrite');
      tx.objectStore(STORE_QUEUE).put(item);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }
  try {
    localStorage.setItem(FALLBACK_QUEUE_KEY, JSON.stringify(nextList));
  } catch {
    // Ignore
  }
  return item;
}

export async function updateOfflineEvidenceItems(items: OfflineEvidenceItem[]): Promise<void> {
  const db = await openDatabase();
  if (db) {
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE_QUEUE, 'readwrite');
      const store = tx.objectStore(STORE_QUEUE);
      for (const item of items) {
        store.put(item);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }
  try {
    const existing = await listOfflineEvidenceQueue();
    const map = new Map<string, OfflineEvidenceItem>();
    for (const ex of existing) map.set(ex.queue_id, ex);
    for (const updated of items) map.set(updated.queue_id, updated);
    localStorage.setItem(FALLBACK_QUEUE_KEY, JSON.stringify(Array.from(map.values())));
  } catch {
    // Ignore
  }
}

export async function clearOfflineQueueStore(): Promise<void> {
  const db = await openDatabase();
  if (db) {
    await new Promise<void>((resolve) => {
      const tx = db.transaction(STORE_QUEUE, 'readwrite');
      tx.objectStore(STORE_QUEUE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    });
  }
  try {
    localStorage.removeItem(FALLBACK_QUEUE_KEY);
  } catch {
    // Ignore
  }
}
