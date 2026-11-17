"""Proof-store and proof-aware election tests. Everything runs against a
throwaway SQLite file; no real cluster is ever contacted (仍为沙盘)."""
import hashlib

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.config.database import Base
from src.models.entities import Node, ProofBatch, ProofSegment, ProofStoreState, Scenario, User
from src.schemas.drill import DrillInput
from src.schemas.proof import ProofBatchInput
from src.services.drill_service import create_drill
from src.services.election import elect
from src.services.node_service import list_nodes
from src.services.proof_service import (GENESIS_DIGEST, chain_status, ingest_batch,
                                        snapshot_proofs, store_status)


def make_chain(length, term=6, content=None, start=1, prev=GENESIS_DIGEST):
    content = content or (lambda p: f'log-{p}')
    segs = []
    for p in range(start, start + length):
        c = content(p)
        digest = hashlib.sha256(f'{prev}|{p}|{term}|{c}'.encode()).hexdigest()
        segs.append({'position': p, 'term': term, 'content': c, 'prev_digest': prev, 'digest': digest})
        prev = digest
    return segs


def forked_chain(prefix, total, content):
    prev = prefix[-1]['digest'] if prefix else GENESIS_DIGEST
    start = prefix[-1]['position'] + 1 if prefix else 1
    return prefix + make_chain(total - start + 1, content=content, start=start, prev=prev)


def payload(key, node, segs, committed=0, digest=''):
    return ProofBatchInput.model_validate({
        'batch_key': key, 'node_name': node,
        'committed_position': committed, 'committed_digest': digest,
        'segments': [{k: s[k] for k in ('position', 'term', 'content', 'prev_digest')} for s in segs]})


def add_node(db, name, role='follower', pos=100, term=6):
    node = Node(name=name, role=role, term=term, log_position=pos,
                available=True, fenced=False, vote_enabled=True)
    db.add(node)
    db.flush()
    return node


def three_nodes(db, pos=100):
    add_node(db, 'hs-primary', role='leader', pos=pos)
    add_node(db, 'hs-east', pos=pos)
    add_node(db, 'hs-west', pos=pos)


def scenario(max_loss=0, required_term=7):
    return {'id': 1, 'name': 's', 'fail_primary': True, 'fence_primary': True,
            'max_data_loss': max_loss, 'required_term': required_term}


def candidate(result, name):
    return next(c for c in result['candidates'] if c['name'] == name)


def check(result, rule):
    return next(c for c in result['checks'] if c['rule'] == rule)


# ---------- 批次接收：冲突、暂存、幂等、落盘 ----------

def test_same_position_different_content_rejects_whole_batch(db):
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    ingest_batch(db, payload('batch-key-01', 'hs-east', make_chain(3)))
    db.commit()
    tampered = make_chain(3, content=lambda p: 'tampered' if p == 3 else f'log-{p}')
    with pytest.raises(HTTPException) as exc:
        ingest_batch(db, payload('batch-key-02', 'hs-east', [tampered[2]]))
    assert exc.value.status_code == 409 and '整批拒绝' in exc.value.detail
    db.rollback()
    assert len(db.scalars(select(ProofSegment)).all()) == 3
    assert len(db.scalars(select(ProofBatch)).all()) == 1
    assert db.get(ProofStoreState, 1).version == 1


def test_conflict_inside_batch_rejects_whole_batch(db):
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    segs = make_chain(2)
    alt = dict(segs[1], content='tampered')
    with pytest.raises(HTTPException) as exc:
        ingest_batch(db, payload('batch-dup-01', 'hs-east', [segs[0], segs[1], alt]))
    assert exc.value.status_code == 409 and '批次内部冲突' in exc.value.detail
    db.rollback()
    assert len(db.scalars(select(ProofSegment)).all()) == 0
    state = db.get(ProofStoreState, 1)
    assert state is None or state.version == 0


def test_out_of_order_segments_staged_until_complete(db):
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    full = make_chain(4)
    ingest_batch(db, payload('batch-tail-01', 'hs-east', full[2:4]))  # 乱序先到，缺前段
    db.commit()
    status = chain_status(db, 'hs-east')
    assert status['proven_tip'] == 0 and status['first_gap'] == 1 and status['staged'] == 2
    # 未接齐的暂存段不参与判定
    assert snapshot_proofs(db)['chains']['hs-east']['proven_tip'] == 0
    ingest_batch(db, payload('batch-head-01', 'hs-east', full[0:2]))  # 补齐缺口
    db.commit()
    status = chain_status(db, 'hs-east')
    assert status['proven_tip'] == 4 and status['staged'] == 0


def test_retry_same_batch_key_not_duplicated(db):
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    body = payload('batch-retry-01', 'hs-east', make_chain(3))
    first = ingest_batch(db, body)
    db.commit()
    again = ingest_batch(db, body)  # 写入中断后重试
    db.commit()
    assert not first['deduplicated'] and again['deduplicated']
    assert again['batch']['id'] == first['batch']['id']
    assert len(db.scalars(select(ProofSegment)).all()) == 3
    assert db.get(ProofStoreState, 1).version == 1


def test_persisted_batch_survives_restart(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path}/proofs.db"
    eng = create_engine(url)
    Base.metadata.create_all(eng)
    factory = sessionmaker(bind=eng, expire_on_commit=False)
    with factory() as s:
        add_node(s, 'hs-primary', role='leader', pos=3)
        add_node(s, 'hs-east', pos=3)
        ingest_batch(s, payload('batch-boot-01', 'hs-east', make_chain(3)))
        s.commit()
    eng.dispose()  # 模拟服务重启
    eng2 = create_engine(url)
    factory2 = sessionmaker(bind=eng2, expire_on_commit=False)
    with factory2() as s:
        assert len(s.scalars(select(ProofSegment)).all()) == 3
        assert store_status(s)['version'] == 1
        assert ingest_batch(s, payload('batch-boot-01', 'hs-east', make_chain(3)))['deduplicated']
        s.commit()
    eng2.dispose()


def test_status_explains_first_gap_and_fork(db):
    three_nodes(db)
    main = make_chain(10)
    fork = forked_chain(main[:5], 10, lambda p: f'west-{p}')
    ingest_batch(db, payload('batch-p-0001', 'hs-primary', main))
    ingest_batch(db, payload('batch-w-0001', 'hs-west', fork))
    db.commit()
    status = store_status(db)
    west = next(n for n in status['nodes'] if n['node'] == 'hs-west')
    assert west['fork_position'] == 6 and west['proven_tip'] == 10
    east = next(n for n in status['nodes'] if n['node'] == 'hs-east')
    assert east['proven_tip'] == 0 and east['first_gap'] is None


# ---------- 证明感知选主 ----------

def test_forked_replica_same_position_approved(db):
    """日志位置相同的分叉副本：分叉只在未提交尾部，仍获准切主。"""
    three_nodes(db)
    base = make_chain(90)
    main = forked_chain(base, 100, lambda p: f'log-{p}')
    fork = forked_chain(base, 100, lambda p: f'west-{p}')
    committed_digest = base[-1]['digest']
    ingest_batch(db, payload('batch-primary', 'hs-primary', main, 90, committed_digest))
    ingest_batch(db, payload('batch-east-01', 'hs-east', main, 90, committed_digest))
    ingest_batch(db, payload('batch-west-01', 'hs-west', fork, 90, committed_digest))
    db.commit()
    result = elect(list_nodes(db), scenario(), snapshot_proofs(db))
    assert result['decision'] == 'approved' and result['winner'] == 'hs-east'
    west = candidate(result, 'hs-west')
    assert west['covered'] and west['eligible']
    assert result['proof_mode'] and result['committed_position'] == 90


def test_fork_within_committed_prefix_blocked(db):
    """同位置异内容落在已提交前缀内：该副本不得切主。"""
    three_nodes(db)
    base = make_chain(90)
    main = forked_chain(base, 100, lambda p: f'log-{p}')
    fork = forked_chain(base, 100, lambda p: f'west-{p}')
    committed_digest = main[94]['digest']  # 位置 95
    ingest_batch(db, payload('batch-primary', 'hs-primary', main, 95, committed_digest))
    ingest_batch(db, payload('batch-east-01', 'hs-east', main, 95, committed_digest))
    ingest_batch(db, payload('batch-west-01', 'hs-west', fork, 95, committed_digest))
    db.commit()
    result = elect(list_nodes(db), scenario(), snapshot_proofs(db))
    west = candidate(result, 'hs-west')
    assert not west['covered'] and not west['eligible']
    assert '分叉' in west['note'] and '91' in west['note']
    assert result['decision'] == 'approved' and result['winner'] == 'hs-east'


def test_insufficient_proof_blocks_election(db):
    """证明不足时阻断：没有副本覆盖已提交前缀。"""
    three_nodes(db)
    base = make_chain(90)
    main = forked_chain(base, 100, lambda p: f'log-{p}')
    fork_e = forked_chain(base, 100, lambda p: f'east-{p}')
    fork_w = forked_chain(base, 100, lambda p: f'west-{p}')
    committed_digest = main[94]['digest']
    ingest_batch(db, payload('batch-primary', 'hs-primary', main, 95, committed_digest))
    ingest_batch(db, payload('batch-east-01', 'hs-east', fork_e, 95, committed_digest))
    ingest_batch(db, payload('batch-west-01', 'hs-west', fork_w, 95, committed_digest))
    db.commit()
    result = elect(list_nodes(db), scenario(), snapshot_proofs(db))
    assert result['decision'] == 'blocked'
    assert not check(result, '已提交前缀证明')['pass']


def test_inspection_bump_does_not_count_as_proof(db):
    """巡检调高位置不算补证：落后按证明覆盖位置计算。"""
    add_node(db, 'hs-primary', role='leader', pos=100)
    add_node(db, 'hs-east', pos=100)  # 声明 100，证明只到 80
    add_node(db, 'hs-west', pos=100)
    main = make_chain(100)
    committed_digest = main[69]['digest']  # 位置 70
    ingest_batch(db, payload('batch-primary', 'hs-primary', main, 70, committed_digest))
    ingest_batch(db, payload('batch-east-01', 'hs-east', main[:80], 70, committed_digest))
    ingest_batch(db, payload('batch-west-01', 'hs-west', main, 70, committed_digest))
    db.commit()
    result = elect(list_nodes(db), scenario(max_loss=0), snapshot_proofs(db))
    east = candidate(result, 'hs-east')
    assert east['proven_tip'] == 80 and east['lag'] == 20 and not east['eligible']
    assert result['winner'] == 'hs-west'


def test_loss_allowance_only_covers_uncommitted_tail(db):
    """损失额度只用于未提交尾部：提交点之后允许落后，提交点之前必须一致。"""
    three_nodes(db)
    main = make_chain(100)
    short = main[:95]  # 尾部少 5 条未提交日志
    committed_digest = main[89]['digest']  # 位置 90
    ingest_batch(db, payload('batch-primary', 'hs-primary', main, 90, committed_digest))
    ingest_batch(db, payload('batch-east-01', 'hs-east', short, 90, committed_digest))
    ingest_batch(db, payload('batch-west-01', 'hs-west', main, 90, committed_digest))
    db.commit()
    result = elect(list_nodes(db), scenario(max_loss=5), snapshot_proofs(db))
    east = candidate(result, 'hs-east')
    assert east['covered'] and east['lag'] == 5 and east['eligible']
    blocked = elect(list_nodes(db), scenario(max_loss=4), snapshot_proofs(db))
    assert not candidate(blocked, 'hs-east')['eligible']


def test_conflicting_commit_declarations_block(db):
    three_nodes(db)
    main = make_chain(100)
    other = make_chain(100, content=lambda p: f'alt-{p}')
    ingest_batch(db, payload('batch-key-01', 'hs-east', main, 90, main[89]['digest']))
    ingest_batch(db, payload('batch-key-02', 'hs-west', other, 90, other[89]['digest']))
    db.commit()
    result = elect(list_nodes(db), scenario(), snapshot_proofs(db))
    assert result['decision'] == 'blocked'
    assert '冲突' in check(result, '已提交前缀证明')['evidence']


def test_legacy_mode_without_proofs_still_works(db):
    add_node(db, 'hs-primary', role='leader', pos=8100)
    add_node(db, 'hs-east', pos=8100)
    add_node(db, 'hs-west', pos=8098)
    result = elect(list_nodes(db), scenario())
    assert result['decision'] == 'approved' and result['winner'] == 'hs-east'
    assert result['proof_mode'] is False and result['committed_position'] == 0


# ---------- 冻结版本与沙盘边界 ----------

def test_drill_freezes_one_complete_proof_version(db):
    """证明接收与入队并发时冻结同一完整版本；历史结论保留原依据。"""
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    sc = Scenario(name='s1', fail_primary=True, fence_primary=True, max_data_loss=0, required_term=7)
    db.add(sc)
    db.flush()
    full = make_chain(5)
    ingest_batch(db, payload('batch-key-01', 'hs-east', full[:3]))
    db.commit()
    drill = create_drill(db, DrillInput(scenario_id=sc.id, label='晚班演练'))
    db.commit()
    frozen = drill.snapshot['proofs']
    assert frozen['version'] == 1
    assert frozen['chains']['hs-east']['proven_tip'] == 3
    ingest_batch(db, payload('batch-key-02', 'hs-east', full[3:]))  # 之后到达的批次
    db.commit()
    assert store_status(db)['version'] == 2
    db.refresh(drill)
    assert drill.snapshot['proofs']['version'] == 1  # 历史快照不变
    result = elect(drill.snapshot['nodes'], drill.snapshot['scenario'], drill.snapshot['proofs'])
    assert result['proof_version'] == 1
    assert candidate(result, 'hs-east')['proven_tip'] == 3


def test_result_remains_sandbox(db):
    three_nodes(db)
    main = make_chain(100)
    ingest_batch(db, payload('batch-key-01', 'hs-east', main, 90, main[89]['digest']))
    db.commit()
    result = elect(list_nodes(db), scenario(), snapshot_proofs(db))
    assert result['simulation'] is True
    assert '未连接真实复制集群' in result['boundary']
    assert result['model_version'] == 'quorum-fencing-rpo-proof-v2'
    assert result['proof_version'] == 1


# ---------- API 层 ----------

def test_proof_api_auth_conflict_and_dedup(db):
    from starlette.testclient import TestClient
    from src.main import app
    from src.utils.security import token
    db.add(User(email='operator@hengshi.local', role='operator', password_hash='x'))
    add_node(db, 'hs-primary', role='leader')
    add_node(db, 'hs-east')
    db.commit()
    user = db.scalar(select(User).where(User.email == 'operator@hengshi.local'))
    headers = {'Authorization': f'Bearer {token(user)}'}
    db.rollback()  # 释放读事务，避免与请求线程的写相互阻塞
    client = TestClient(app)
    segs = make_chain(3)
    body = {'batch_key': 'batch-api-01', 'node_name': 'hs-east', 'committed_position': 3,
            'committed_digest': segs[-1]['digest'],
            'segments': [{k: s[k] for k in ('position', 'term', 'content', 'prev_digest')} for s in segs]}
    assert client.post('/proofs', json=body).status_code == 401
    created = client.post('/proofs', json=body, headers=headers)
    assert created.status_code == 201 and created.json()['deduplicated'] is False
    retry = client.post('/proofs', json=body, headers=headers)
    assert retry.status_code == 201 and retry.json()['deduplicated'] is True
    tampered = make_chain(3, content=lambda p: 'tampered' if p == 3 else f'log-{p}')
    conflict = dict(body, batch_key='batch-api-02',
                    segments=[{k: tampered[2][k] for k in ('position', 'term', 'content', 'prev_digest')}])
    assert client.post('/proofs', json=conflict, headers=headers).status_code == 409
    status = client.get('/proofs/status', headers=headers).json()
    assert status['version'] == 1
    east = next(n for n in status['nodes'] if n['node'] == 'hs-east')
    assert east['proven_tip'] == 3
