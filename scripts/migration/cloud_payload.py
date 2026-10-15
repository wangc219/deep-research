#!/usr/bin/env python3
"""用逻辑格式迁移对象和向量，避免跨架构复制数据库文件。"""

import argparse
from array import array
import gzip
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from minio import Minio
from minio.error import S3Error
import psycopg
from psycopg import sql
from pymilvus import Collection, CollectionSchema, connections, db, utility


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["export", "restore", "verify"])
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    endpoint = urlsplit(os.environ.get("MINIO_URI", "http://minio:9000"))
    objects = Minio(
        endpoint.netloc,
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=endpoint.scheme == "https",
    )
    connections.connect(alias="migration", uri=os.environ.get("MILVUS_URI", "http://milvus:19530"))
    if args.action == "export":
        export_payload(root, objects)
    else:
        restore_or_verify(root, objects, restore=args.action == "restore")


def export_payload(root, objects):
    """保存 SQL 行数、对象字节和全部向量，不输出业务正文或密钥。"""
    manifest = {"tables": {}, "buckets": [], "collections": []}
    uri = os.environ["POSTGRES_URL"].replace("+asyncpg", "").replace("+psycopg", "")
    with psycopg.connect(uri) as conn:
        tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
        for (name,) in tables:
            manifest["tables"][name] = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))).fetchone()[0]

    (root / "objects").mkdir(exist_ok=True)
    for bucket in objects.list_buckets():
        try:
            policy = objects.get_bucket_policy(bucket.name)
        except S3Error as exc:
            if exc.code != "NoSuchBucketPolicy":
                raise
            policy = None
        entry = {"name": bucket.name, "policy": policy, "objects": []}
        for item in objects.list_objects(bucket.name, recursive=True):
            stat = objects.stat_object(bucket.name, item.object_name)
            response = objects.get_object(bucket.name, item.object_name)
            try:
                content = response.read()
            finally:
                response.close()
                response.release_conn()
            digest = hashlib.sha256(content).hexdigest()
            (root / "objects" / digest).write_bytes(content)
            entry["objects"].append({
                "name": item.object_name, "sha256": digest, "size": len(content),
                "content_type": stat.content_type,
                "metadata": {k: v for k, v in stat.metadata.items() if k.lower().startswith("x-amz-meta-")},
            })
        manifest["buckets"].append(entry)

    (root / "vectors").mkdir(exist_ok=True)
    for database in db.list_database(using="migration"):
        db.using_database(database, using="migration")
        for name in utility.list_collections(using="migration"):
            collection = Collection(name, using="migration")
            collection.flush()
            count = collection.num_entities
            if not count:
                continue
            collection.load()
            schema = collection.schema.to_dict()
            fields = [f["name"] for f in schema["fields"] if not f.get("is_function_output")]
            iterator = collection.query_iterator(batch_size=128, expr="", output_fields=fields)
            rows = []
            try:
                while batch := iterator.next():
                    rows.extend(batch)
            finally:
                iterator.close()
            assert len(rows) == count, (database, name, count, len(rows))
            filename = hashlib.sha256((database + "/" + name).encode()).hexdigest() + ".json.gz"
            with gzip.open(root / "vectors" / filename, "wt") as output:
                json.dump(rows, output, ensure_ascii=False, default=lambda x: x.tolist() if hasattr(x, "tolist") else x.item())
            manifest["collections"].append({
                "database": database, "name": name, "count": count, "schema": schema,
                "file": filename,
                "indexes": [{"field": i.field_name, "name": i.index_name, "params": i.params} for i in collection.indexes],
            })
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"tables": len(manifest["tables"]), "buckets": len(manifest["buckets"]), "collections": len(manifest["collections"])}))


def restore_or_verify(root, objects, *, restore):
    """恢复后逐个核对对象 SHA-256 和向量集合主键、数量。"""
    manifest = json.loads((root / "manifest.json").read_text())
    for bucket in manifest["buckets"]:
        if restore and not objects.bucket_exists(bucket["name"]):
            objects.make_bucket(bucket["name"])
        for item in bucket["objects"]:
            source = root / "objects" / item["sha256"]
            assert hashlib.sha256(source.read_bytes()).hexdigest() == item["sha256"]
            if restore:
                objects.fput_object(bucket["name"], item["name"], str(source), content_type=item["content_type"], metadata=item["metadata"])
            response = objects.get_object(bucket["name"], item["name"])
            try:
                assert hashlib.sha256(response.read()).hexdigest() == item["sha256"]
            finally:
                response.close()
                response.release_conn()
        if restore and bucket["policy"]:
            objects.set_bucket_policy(bucket["name"], bucket["policy"])

    available = set(db.list_database(using="migration"))
    # 历史索引位于 yuxi，当前代码使用 deep_research；原库与当前库均保留。
    targets = [(item["database"], item) for item in manifest["collections"]]
    targets += [("deep_research", item) for item in manifest["collections"] if item["database"] == "yuxi"]
    for database, item in targets:
        if database not in available:
            if not restore:
                raise RuntimeError(f"向量数据库缺失：{database}")
            db.create_database(database, using="migration")
            available.add(database)
        db.using_database(database, using="migration")
        exists = utility.has_collection(item["name"], using="migration")
        if not exists:
            if not restore:
                raise RuntimeError(f"向量集合缺失：{item['name']}")
            schema = CollectionSchema.construct_from_dict(item["schema"])
            collection = Collection(item["name"], schema, using="migration")
        else:
            collection = Collection(item["name"], using="migration")
        with gzip.open(root / "vectors" / item["file"], "rt") as source:
            rows = json.load(source)
        if restore:
            if collection.num_entities:
                raise RuntimeError(f"目标向量集合非空，拒绝覆盖：{database}/{item['name']}")
            for start in range(0, len(rows), 128):
                collection.insert(rows[start:start + 128])
            collection.flush()
            for index in item["indexes"]:
                collection.create_index(index["field"], index["params"], index_name=index["name"])
        assert collection.num_entities == item["count"], (database, item["name"], collection.num_entities)
        collection.load()
        primary = next(f["name"] for f in item["schema"]["fields"] if f.get("is_primary"))
        fields = [f["name"] for f in item["schema"]["fields"] if not f.get("is_function_output")]
        actual = collection.query(expr="", output_fields=fields, limit=item["count"] + 1)
        by_id = {str(r[primary]): r for r in actual}
        assert set(by_id) == {str(r[primary]) for r in rows}
        for row in rows:
            for field in fields:
                value = by_id[str(row[primary])][field]
                if field == "embedding":
                    assert array("f", value).tobytes() == array("f", row[field]).tobytes()
                else:
                    assert value == row[field], (database, item["name"], field)
    print(json.dumps({"object_hashes": "passed", "vector_counts_and_ids": "passed", "restored": restore}))


if __name__ == "__main__":
    main()
