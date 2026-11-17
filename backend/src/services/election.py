"""Deterministic election model. Never contacts or promotes production nodes."""
import hashlib, json

def _usable_digests(chain):
    # Only the contiguous, fully linked prefix counts; staged segments past a
    # gap stay unusable until the chain is completed.
    return {s['position']: s['digest'] for s in chain['segments']
            if s['position'] <= chain['proven_tip']}

def _coverage_note(chain, committed, committed_digest, reference):
    if chain is None:
        return False, '未提供日志证明，无法覆盖已提交前缀'
    if chain['proven_tip'] < committed:
        if chain.get('break_position') is not None:
            return False, f"证明链在位置 {chain['break_position']} 前序摘要断裂，仅覆盖至 {chain['proven_tip']}"
        return False, f"证明仅覆盖至 {chain['proven_tip']}，首个缺段 {chain.get('first_gap') or chain['proven_tip'] + 1}"
    if _usable_digests(chain).get(committed) != committed_digest:
        own = _usable_digests(chain)
        fork = next((p for p in sorted(own) if p <= committed and p in reference and own[p] != reference[p]), None)
        if fork is not None:
            return False, f'位置 {fork} 起与原主日志分叉（同位置异内容），未覆盖已提交前缀'
        return False, f'位置 {committed} 摘要与原主声明提交摘要不符'
    return True, '已提交前缀证明完整'

def elect(nodes, scenario, proofs=None):
    if not nodes: raise ValueError('至少需要一个节点')
    leaders = [n for n in nodes if n['role'] == 'leader']
    if len(leaders) != 1: raise ValueError('必须且只能配置一个原主节点')
    primary = leaders[0]
    voters = [n for n in nodes if n['vote_enabled']]
    if not voters: raise ValueError('至少需要一个有投票权节点')
    quorum = len(voters) // 2 + 1
    reachable = [n for n in voters if n['available'] and not n['fenced']
                 and not (scenario['fail_primary'] and n['id'] == primary['id'])]
    proofs = proofs or {}
    chains = proofs.get('chains', {})
    declarations = [d for d in proofs.get('declarations', []) if d['committed_position'] > 0]
    committed = max((d['committed_position'] for d in declarations), default=0)
    digests_at_committed = {d['committed_digest'] for d in declarations
                            if d['committed_position'] == committed}
    declaration_conflict = committed > 0 and len(digests_at_committed) > 1
    committed_digest = next(iter(digests_at_committed)) if len(digests_at_committed) == 1 else None
    proof_mode = committed > 0
    # Latest known position: inspection claims plus proven chain tips.
    latest = max([n['log_position'] for n in nodes]
                 + [c['proven_tip'] for c in chains.values()] + [0])
    term = max(n['term'] for n in nodes) + 1
    fenced = primary['fenced'] or scenario['fence_primary']
    checks = [
        {'rule': '故障切换触发', 'pass': scenario['fail_primary'] or not primary['available'], 'evidence': f"fail_primary={scenario['fail_primary']}; available={primary['available']}"},
        {'rule': '多数派', 'pass': len(reachable) >= quorum, 'evidence': f'{len(reachable)} 可达票 / {len(voters)} 配置票，需要 {quorum}'},
        {'rule': '旧主写入隔离 fencing', 'pass': fenced, 'evidence': '已证明写入隔离' if fenced else '缺少 fencing 证明，阻止脑裂'},
        {'rule': '任期门槛', 'pass': term >= scenario['required_term'], 'evidence': f"新任期 {term} / 要求 {scenario['required_term']}"}]
    reference = {}
    if proof_mode and not declaration_conflict:
        for chain in [chains.get(primary['name']), *chains.values()]:
            if chain and _usable_digests(chain).get(committed) == committed_digest:
                reference = _usable_digests(chain)
                break
    candidates = []
    for n in nodes:
        chain = chains.get(n['name'])
        proven_tip = chain['proven_tip'] if chain else None
        if proof_mode:
            covered, note = (False, '提交点声明冲突，需人工核对') if declaration_conflict else \
                _coverage_note(chain, committed, committed_digest, reference)
            # Inspection claims are not proof: the loss allowance is measured
            # from the proven tip, only over the uncommitted tail.
            effective = proven_tip or 0
        else:
            covered, note, effective = True, '未声明提交点，按巡检声明位置评估', n['log_position']
        lag = latest - effective
        eligible = (n['role'] == 'follower' and n['available'] and not n['fenced']
                    and n['vote_enabled'] and covered and lag <= scenario['max_data_loss'])
        candidates.append({'name': n['name'], 'log_position': n['log_position'],
                           'proven_tip': proven_tip, 'lag': lag, 'covered': covered,
                           'note': note, 'effective_position': effective, 'eligible': eligible})
    eligible = sorted([c for c in candidates if c['eligible']],
                      key=lambda c: (-c['effective_position'], c['name']))
    if declaration_conflict:
        checks.append({'rule': '已提交前缀证明', 'pass': False,
                       'evidence': f'提交点 {committed} 存在 {len(digests_at_committed)} 种冲突声明摘要，需人工核对'})
    elif proof_mode:
        covering = [c for c in candidates if c['covered'] and c['name'] != primary['name']]
        checks.append({'rule': '已提交前缀证明', 'pass': bool(covering),
                       'evidence': f"提交点 {committed}，{len(covering)} 个副本证明覆盖已提交前缀" if covering
                                   else f'提交点 {committed}，无副本证明覆盖已提交前缀，证明不足'})
    else:
        checks.append({'rule': '已提交前缀证明', 'pass': True,
                       'evidence': '未声明提交点，按巡检声明位置评估（教学简化）'})
    checks.append({'rule': 'RPO 合格候选', 'pass': bool(eligible),
                   'evidence': f"{len(eligible)} 个候选，允许丢失 {scenario['max_data_loss']} 条未提交尾部日志"
                               + ('，落后按证明覆盖位置计算' if proof_mode else '')})
    approved = all(c['pass'] for c in checks)
    source = json.dumps({'nodes': nodes, 'scenario': scenario, 'proofs': proofs},
                        sort_keys=True, ensure_ascii=False)
    return {'decision': 'approved' if approved else 'blocked', 'winner': eligible[0]['name'] if approved else None,
            'new_term': term, 'quorum': quorum, 'reachable_votes': len(reachable), 'checks': checks,
            'candidates': candidates, 'proof_mode': proof_mode, 'committed_position': committed,
            'proof_version': proofs.get('version'),
            'input_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'model_version': 'quorum-fencing-rpo-proof-v2', 'simulation': True,
            'boundary': '受控演练模型；未连接真实复制集群，未执行生产切主。任期、日志位置、fencing 与日志证明由输入声明。'}
