"""Deterministic election model. Never contacts or promotes production nodes."""
import hashlib, json

def elect(nodes, scenario):
    if not nodes: raise ValueError('至少需要一个节点')
    leaders = [n for n in nodes if n['role'] == 'leader']
    if len(leaders) != 1: raise ValueError('必须且只能配置一个原主节点')
    primary = leaders[0]
    voters = [n for n in nodes if n['vote_enabled']]
    if not voters: raise ValueError('至少需要一个有投票权节点')
    quorum = len(voters) // 2 + 1
    reachable = [n for n in voters if n['available'] and not n['fenced']
                 and not (scenario['fail_primary'] and n['id'] == primary['id'])]
    latest = max(n['log_position'] for n in nodes)
    term = max(n['term'] for n in nodes) + 1
    fenced = primary['fenced'] or scenario['fence_primary']
    checks = [
        {'rule': '故障切换触发', 'pass': scenario['fail_primary'] or not primary['available'], 'evidence': f"fail_primary={scenario['fail_primary']}; available={primary['available']}"},
        {'rule': '多数派', 'pass': len(reachable) >= quorum, 'evidence': f'{len(reachable)} 可达票 / {len(voters)} 配置票，需要 {quorum}'},
        {'rule': '旧主写入隔离 fencing', 'pass': fenced, 'evidence': '已证明写入隔离' if fenced else '缺少 fencing 证明，阻止脑裂'},
        {'rule': '任期门槛', 'pass': term >= scenario['required_term'], 'evidence': f"新任期 {term} / 要求 {scenario['required_term']}"}]
    candidates = []
    for n in nodes:
        lag = latest - n['log_position']
        eligible = (n['role'] == 'follower' and n['available'] and not n['fenced'] and n['vote_enabled'] and lag <= scenario['max_data_loss'])
        candidates.append({'name': n['name'], 'log_position': n['log_position'], 'lag': lag, 'eligible': eligible})
    eligible = sorted([n for n in candidates if n['eligible']], key=lambda n: (-n['log_position'], n['name']))
    checks.append({'rule': 'RPO 合格候选', 'pass': bool(eligible), 'evidence': f"{len(eligible)} 个候选，允许丢失 {scenario['max_data_loss']} 条日志"})
    approved = all(c['pass'] for c in checks)
    source = json.dumps({'nodes': nodes, 'scenario': scenario}, sort_keys=True, ensure_ascii=False)
    return {'decision': 'approved' if approved else 'blocked', 'winner': eligible[0]['name'] if approved else None,
            'new_term': term, 'quorum': quorum, 'reachable_votes': len(reachable), 'checks': checks,
            'candidates': candidates, 'input_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'model_version': 'quorum-fencing-rpo-v1', 'simulation': True,
            'boundary': '受控演练模型；未连接真实复制集群，未执行生产切主。任期、日志位置、fencing 由输入声明。'}
