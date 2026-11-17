# 数据结构
本小型项目首次启动使用 SQLAlchemy metadata 建立 users/nodes/scenarios/drills/audits 五表。自然键 users.email、nodes.name、scenarios.name 唯一。drills.scenario_id 为外键，快照在入队时固定。上线结构演进须补充版本化迁移，本项目不支持对既有不同结构数据库自动升级。
