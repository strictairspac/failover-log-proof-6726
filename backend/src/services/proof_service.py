"""Segmented log-proof store. All data is user-declared drill input; nothing
here contacts a real replication cluster."""
import hashlib
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Node, ProofBatch, ProofSegment, ProofStoreState
from src.utils.serialize import record

# Digest chain anchor for position 1. digest(p) = sha256(prev|position|term|content).
GENESIS_DIGEST = '0' * 64

def segment_digest(prev_digest, position, term, content):
    return hashlib.sha256(f'{prev_digest}|{position}|{term}|{content}'.encode()).hexdigest()

def evaluate_chain(segments):
    """Walk a node's stored segments from position 1. Only the contiguous,
    correctly linked prefix is usable; anything past a gap or a broken link
    stays staged until the missing pieces arrive."""
    by_pos = {s.position: s for s in segments}
    tip, expected, first_gap, break_position = 0, GENESIS_DIGEST, None, None
    for position in sorted(by_pos):
        seg = by_pos[position]
        if position != tip + 1:
            first_gap = tip + 1
            break
        if seg.prev_digest != expected:
            break_position = position
            break
        expected = seg.digest
        tip = position
    staged = sum(1 for p in by_pos if p > tip)
    return {'proven_tip': tip, 'tip_digest': expected, 'first_gap': first_gap,
            'break_position': break_position, 'staged': staged}

def fork_position(own_segments, reference_segments):
    """First position where two nodes hold different content (digest)."""
    reference = {s.position: s.digest for s in reference_segments}
    for seg in sorted(own_segments, key=lambda s: s.position):
        if seg.position in reference and reference[seg.position] != seg.digest:
            return seg.position
    return None

def lock_state(db):
    """Lock the singleton version row; ingest and drill enqueue serialize on it
    so a drill snapshot always freezes one complete proof version."""
    state = db.scalar(select(ProofStoreState).where(ProofStoreState.id == 1).with_for_update())
    if state is None:
        with db.begin_nested():
            db.add(ProofStoreState(id=1, version=0))
        state = db.scalar(select(ProofStoreState).where(ProofStoreState.id == 1).with_for_update())
    return state

def node_segments(db, node_name):
    return db.scalars(select(ProofSegment).where(ProofSegment.node_name == node_name)
                      .order_by(ProofSegment.position)).all()

def chain_status(db, node_name):
    segments = node_segments(db, node_name)
    status = evaluate_chain(segments)
    primary = db.scalar(select(Node).where(Node.role == 'leader'))
    fork = None
    if primary and primary.name != node_name:
        fork = fork_position(segments, node_segments(db, primary.name))
    declared = db.scalars(select(ProofBatch).where(ProofBatch.node_name == node_name)
                          .order_by(ProofBatch.id.desc())).first()
    return {'node': node_name, **status, 'fork_position': fork,
            'committed_position': declared.committed_position if declared else None,
            'committed_digest': declared.committed_digest if declared else None}

def store_status(db):
    state = db.get(ProofStoreState, 1)
    nodes = db.scalars(select(Node).order_by(Node.id)).all()
    return {'version': state.version if state else 0,
            'nodes': [chain_status(db, n.name) for n in nodes]}

def list_batches(db):
    rows = db.scalars(select(ProofBatch).order_by(ProofBatch.id.desc()).limit(100)).all()
    return [record(b) for b in rows]

def ingest_batch(db, payload):
    """Persist one proof batch atomically. Any conflict rejects the whole
    batch; retries with the same batch_key return the stored batch instead of
    duplicating segments."""
    if not db.scalar(select(Node).where(Node.name == payload.node_name)):
        raise HTTPException(404, '节点不存在，请先在节点状态页配置')
    existing = db.scalar(select(ProofBatch).where(ProofBatch.batch_key == payload.batch_key))
    if existing:
        return {'batch': record(existing), 'deduplicated': True,
                'chain': chain_status(db, payload.node_name)}
    unique = {}
    for seg in payload.segments:
        key = (seg.term, seg.content, seg.prev_digest)
        if seg.position in unique and unique[seg.position][0] != key:
            raise HTTPException(409, f'批次内部冲突：位置 {seg.position} 出现两份不同内容，整批拒绝')
        unique.setdefault(seg.position, (key, seg))
    stored = {s.position: s for s in node_segments(db, payload.node_name)}
    pending = []
    for position, (_, seg) in unique.items():
        digest = segment_digest(seg.prev_digest, seg.position, seg.term, seg.content)
        old = stored.get(position)
        if old and old.digest != digest:
            raise HTTPException(409, f'位置 {position} 与已落盘证明冲突（同位置异内容），整批拒绝')
        if not old:
            pending.append((seg, digest))
    state = lock_state(db)
    batch = ProofBatch(batch_key=payload.batch_key, node_name=payload.node_name,
                       committed_position=payload.committed_position,
                       committed_digest=payload.committed_digest,
                       segment_count=len(unique), version=state.version + 1)
    db.add(batch)
    db.flush()
    for seg, digest in pending:
        db.add(ProofSegment(batch_id=batch.id, node_name=payload.node_name,
                            position=seg.position, term=seg.term, content=seg.content,
                            prev_digest=seg.prev_digest, digest=digest))
    state.version += 1
    db.flush()
    return {'batch': record(batch), 'deduplicated': False,
            'chain': chain_status(db, payload.node_name)}

def snapshot_proofs(db):
    """Freeze the complete proof store at the current version into a drill
    snapshot. Caller holds the version-row lock until commit."""
    state = lock_state(db)
    chains = {}
    for row in db.scalars(select(ProofSegment.node_name).distinct()):
        segments = node_segments(db, row)
        status = evaluate_chain(segments)
        chains[row] = {'proven_tip': status['proven_tip'], 'first_gap': status['first_gap'],
                       'break_position': status['break_position'],
                       'segments': [{'position': s.position, 'term': s.term, 'content': s.content,
                                     'prev_digest': s.prev_digest, 'digest': s.digest}
                                    for s in segments]}
    declarations = [{'node_name': b.node_name, 'committed_position': b.committed_position,
                     'committed_digest': b.committed_digest, 'batch_key': b.batch_key}
                    for b in db.scalars(select(ProofBatch).order_by(ProofBatch.id))]
    return {'version': state.version, 'chains': chains, 'declarations': declarations}
