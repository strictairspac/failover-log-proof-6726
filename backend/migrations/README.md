# 数据结构
本小型项目首次启动使用 SQLAlchemy metadata 建立 users/nodes/scenarios/drills/audits/proof_store_state/proof_batches/proof_segments 八表。自然键 users.email、nodes.name、scenarios.name、proof_batches.batch_key 唯一，proof_segments 按 (node_name, position) 唯一。drills.scenario_id 与 proof_segments.batch_id 为外键，演练快照与证明版本在入队/落盘时固定。上线结构演进须补充版本化迁移，本项目不支持对既有不同结构数据库自动升级。
