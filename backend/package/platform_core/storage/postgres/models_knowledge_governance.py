"""知识分类、来源采集、简报与采集成果的持久化模型。"""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from platform_core.storage.postgres.models_knowledge import Base, JSON_VALUE
from platform_core.utils.datetime_utils import utc_now


class KnowledgeCategory(Base):
    """组织内共用的单主分类树节点。"""

    __tablename__ = "knowledge_categories"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, default="default", index=True)
    parent_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"), index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True, index=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    __table_args__ = (
        Index(
            "uq_knowledge_category_sibling_normalized",
            tenant_id,
            func.coalesce(parent_id, ""),
            name,
            unique=True,
        ),
        Index("ix_knowledge_category_tree", "tenant_id", "parent_id", "sort_order"),
    )


class KnowledgeSourceCredential(Base):
    """来源连接凭据密文；公开接口只返回是否已配置。"""

    __tablename__ = "knowledge_source_credentials"

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    encrypted_secret = Column(Text, nullable=False)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeSource(Base):
    """知识库统一来源配置与增量采集游标。"""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('upload', 'postgresql', 'mysql', 'website', 'web_search')",
            name="ck_knowledge_source_type",
        ),
        Index("ix_knowledge_source_owner", "tenant_id", "kb_id", "enabled"),
    )

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"), index=True)
    name = Column(String(255), nullable=False)
    source_type = Column(String(32), nullable=False, index=True)
    config = Column(JSON_VALUE, nullable=False, default=dict)
    credential_id = Column(
        String(64), ForeignKey("knowledge_source_credentials.id", ondelete="SET NULL"), nullable=True
    )
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    notify_on_new = Column(Boolean, nullable=False, default=False)
    cron_expression = Column(String(100))
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    cursor = Column(JSON_VALUE, nullable=False, default=dict)
    last_status = Column(String(32), nullable=False, default="idle")
    last_error = Column(Text, nullable=False, default="")
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True), index=True)
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeSourceRun(Base):
    """一次来源采集的不可变运行入口和结果统计。"""

    __tablename__ = "knowledge_source_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_knowledge_source_run_status",
        ),
        Index("ix_knowledge_source_run_recent", "source_id", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False)
    owner_uid = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), index=True)
    trigger = Column(String(32), nullable=False, default="manual")
    status = Column(String(32), nullable=False, default="pending", index=True)
    config_snapshot = Column(JSON_VALUE, nullable=False, default=dict)
    stats = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeSourceItem(Base):
    """规范化为 Markdown 的暂存证据及其版本谱系。"""

    __tablename__ = "knowledge_source_items"
    __table_args__ = (
        UniqueConstraint("source_id", "external_key", "version", name="uq_knowledge_source_item_version"),
        UniqueConstraint("source_id", "content_hash", name="uq_knowledge_source_item_hash"),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected', 'duplicate', 'failed')",
            name="ck_knowledge_source_item_review",
        ),
        Index("ix_knowledge_source_item_queue", "kb_id", "review_status", "discovered_at"),
    )

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(String(64), ForeignKey("knowledge_source_runs.id", ondelete="SET NULL"), index=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"), index=True)
    external_key = Column(String(1024), nullable=False)
    canonical_url = Column(String(2048), nullable=False, default="")
    title = Column(Text, nullable=False)
    markdown = Column(Text, nullable=False)
    metadata_json = Column(JSON_VALUE, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    previous_item_id = Column(String(64), ForeignKey("knowledge_source_items.id", ondelete="SET NULL"))
    review_status = Column(String(32), nullable=False, default="pending", index=True)
    review_note = Column(Text, nullable=False, default="")
    reviewed_by = Column(String(64))
    reviewed_at = Column(DateTime(timezone=True))
    minio_url = Column(String(1024))
    knowledge_file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="SET NULL"))
    ingest_task_id = Column(String(64), index=True)
    discovered_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class InnovationBriefSubscription(Base):
    """用户的前沿技术深度挖掘订阅。"""

    __tablename__ = "innovation_brief_subscriptions"
    __table_args__ = (Index("ix_innovation_subscription_owner", "owner_uid", "enabled"),)

    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    owner_uid = Column(String(64), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    topics = Column(JSON_VALUE, nullable=False, default=list)
    keywords = Column(JSON_VALUE, nullable=False, default=list)
    knowledge_ids = Column(JSON_VALUE, nullable=False, default=list)
    source_ids = Column(JSON_VALUE, nullable=False, default=list)
    languages = Column(JSON_VALUE, nullable=False, default=lambda: ["zh-CN", "en"])
    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    daily_enabled = Column(Boolean, nullable=False, default=True)
    weekly_enabled = Column(Boolean, nullable=False, default=True)
    daily_cron = Column(String(100), nullable=False, default="0 8 * * *")
    weekly_cron = Column(String(100), nullable=False, default="0 9 * * 1")
    reminder_sensitivity = Column(String(16), nullable=False, default="standard")
    significance_threshold = Column(Float, nullable=False, default=70.0)
    open_discovery_enabled = Column(Boolean, nullable=False, default=True)
    research_explorer_enabled = Column(Boolean, nullable=False, default=True)
    next_daily_at = Column(DateTime(timezone=True), index=True)
    next_weekly_at = Column(DateTime(timezone=True), index=True)
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class InnovationBriefRun(Base):
    """一次日简报或周报生成运行。"""

    __tablename__ = "innovation_brief_runs"
    __table_args__ = (Index("ix_innovation_brief_run_recent", "subscription_id", "created_at"),)

    id = Column(String(64), primary_key=True)
    subscription_id = Column(
        String(64), ForeignKey("innovation_brief_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    owner_uid = Column(String(64), nullable=False, index=True)
    task_id = Column(String(64), index=True)
    brief_type = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending", index=True)
    query_plan = Column(JSON_VALUE, nullable=False, default=list)
    stats = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    scheduled_for = Column(DateTime(timezone=True), index=True)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class InnovationBrief(Base):
    """结构化简报正文及显著性结论。"""

    __tablename__ = "innovation_briefs"
    __table_args__ = (Index("ix_innovation_brief_feed", "owner_uid", "created_at"),)

    id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("innovation_brief_runs.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(
        String(64), ForeignKey("innovation_brief_subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    owner_uid = Column(String(64), nullable=False, index=True)
    brief_type = Column(String(32), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    summary = Column(Text, nullable=False)
    sections = Column(JSON_VALUE, nullable=False, default=dict)
    evidence = Column(JSON_VALUE, nullable=False, default=list)
    max_score = Column(Float, nullable=False, default=0.0)
    significant = Column(Boolean, nullable=False, default=False)
    unread = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    published_at = Column(DateTime(timezone=True), index=True)
    read_at = Column(DateTime(timezone=True))


class BriefDeliveryOutbox(Base):
    """简报投递 Outbox；企业微信首版只保留禁用记录。"""

    __tablename__ = "brief_delivery_outbox"
    __table_args__ = (
        UniqueConstraint("brief_id", "provider", name="uq_brief_delivery_provider"),
        CheckConstraint("provider IN ('in_app', 'wecom')", name="ck_brief_delivery_provider"),
        Index("ix_brief_delivery_pending", "status", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    brief_id = Column(String(64), ForeignKey("innovation_briefs.id", ondelete="CASCADE"), nullable=False)
    owner_uid = Column(String(64), nullable=False, index=True)
    provider = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    payload = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    scheduled_for = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    delivered_at = Column(DateTime(timezone=True))


class CollectionArtifactRecord(Base):
    """沙盒采集成果的数据库事实投影。"""

    __tablename__ = "collection_artifact_records"
    __table_args__ = (
        UniqueConstraint("owner_uid", "source", "artifact_key", name="uq_collection_artifact_owner_key"),
        Index("ix_collection_artifact_owner_status", "owner_uid", "source", "status"),
    )

    id = Column(String(64), primary_key=True)
    owner_uid = Column(String(64), nullable=False, index=True)
    source = Column(String(32), nullable=False)
    artifact_key = Column(String(64), nullable=False)
    title = Column(Text, nullable=False)
    account = Column(String(255), nullable=False, default="")
    canonical_url = Column(String(2048), nullable=False, default="")
    content_hash = Column(String(64))
    primary_path = Column(String(1024), nullable=False)
    import_path = Column(String(1024), nullable=False)
    files = Column(JSON_VALUE, nullable=False, default=list)
    status = Column(String(32), nullable=False, default="downloaded", index=True)
    failure_stage = Column(String(32))
    error = Column(Text, nullable=False, default="")
    downloaded_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class CollectionArtifactIngestion(Base):
    """成果进入目标知识库的一次幂等尝试。"""

    __tablename__ = "collection_artifact_ingestions"
    __table_args__ = (
        UniqueConstraint("artifact_id", "kb_id", "content_hash", name="uq_collection_artifact_ingestion_content"),
        Index("ix_collection_artifact_ingestion_task", "task_id", "status"),
    )

    id = Column(String(64), primary_key=True)
    artifact_id = Column(String(64), ForeignKey("collection_artifact_records.id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    category_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"))
    content_hash = Column(String(64), nullable=False)
    task_id = Column(String(64), nullable=False, index=True)
    knowledge_file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="SET NULL"))
    status = Column(String(32), nullable=False, default="importing", index=True)
    error = Column(Text, nullable=False, default="")
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
