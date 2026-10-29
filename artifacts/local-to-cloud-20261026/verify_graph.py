"""只输出图谱整体指纹，比较所有节点、关系和属性，不输出资料正文。"""

import hashlib
import json
import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(os.getenv('NEO4J_URI', 'bolt://graph:7687'),
    auth=(os.getenv('NEO4J_USERNAME') or 'neo4j', os.getenv('NEO4J_PASSWORD') or '0123456789'))
result = {}
with driver.session(fetch_size=256) as session:
    for kind, query in (
        ('nodes', 'MATCH (n) RETURN id(n) AS id, labels(n) AS labels, properties(n) AS properties ORDER BY id(n)'),
        ('relationships', 'MATCH (a)-[r]->(b) RETURN id(r) AS id,id(a) AS source,id(b) AS target,type(r) AS type,properties(r) AS properties ORDER BY id(r)'),
    ):
        digest = hashlib.sha256()
        count = 0
        for record in session.run(query):
            value = dict(record)
            if 'labels' in value:
                value['labels'].sort()
            digest.update(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()+b'\n')
            count += 1
        result[kind] = {'count': count, 'sha256': digest.hexdigest()}
driver.close()
print(json.dumps(result))
