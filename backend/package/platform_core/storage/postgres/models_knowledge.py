"""PostgreSQL 知识库模型 - KnowledgeBase、KnowledgeFile、评估相关表"""

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from platform_core.utils.datetime_utils import utc_now

Base = declarative_base()
JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class KnowledgeBase(Base):
    """知识库模型"""

    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("kb_id", name="uq_knowledge_bases_kb_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    kb_id = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    description = Column(Text)
    kb_type = Column(String(32), nullable=False, index=True)
    embedding_model_spec = Column(String(512))
    llm_model_spec = Column(String(512))
    query_params = Column(JSON_VALUE)
    additional_params = Column(JSON_VALUE)
    share_config = Column(JSON_VALUE)
    mindmap = Column(JSON_VALUE)
    mindmap_file_ids = Column(JSON_VALUE)
    mindmap_metadata = Column(JSON_VALUE)
    sample_questions = Column(JSON_VALUE)
    created_by = Column(String(64))
    category_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"), index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeFile(Base):
    """知识文件模型"""

    __tablename__ = "knowledge_files"
    __table_args__ = (UniqueConstraint("file_id", name="uq_knowledge_files_file_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(64), unique=True, nullable=False, index=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="SET NULL"), index=True)
    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512))
    file_type = Column(String(64))
    path = Column(String(1024))
    minio_url = Column(String(1024))
    markdown_file = Column(String(1024))
    status = Column(String(32), default="uploaded", index=True)
    content_hash = Column(String(128), index=True)
    file_size = Column(BigInteger)
    chunk_count = Column(Integer, default=0)
    token_count = Column(BigInteger, default=0)
    content_type = Column(String(64))
    processing_params = Column(JSON_VALUE)
    is_folder = Column(Boolean, default=False)
    error_message = Column(Text)
    processing_task_id = Column(String(64), index=True)
    processing_owner = Column(String(128))
    created_by = Column(String(64))
    updated_by = Column(String(64))
    category_id = Column(String(64), ForeignKey("knowledge_categories.id", ondelete="RESTRICT"), index=True)
    source_id = Column(String(64), ForeignKey("knowledge_sources.id", ondelete="SET NULL"), index=True)
    source_item_id = Column(String(64), ForeignKey("knowledge_source_items.id", ondelete="SET NULL"), index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class WechatChannel(Base):
    """每个用户独立保存的视频号列表及同步状态。"""

    __tablename__ = "wechat_channels"
    __table_args__ = (UniqueConstraint("owner_uid", "username", name="uq_wechat_channel_owner_username"),)

    id = Column(String(64), primary_key=True)
    owner_uid = Column(String(64), nullable=False, index=True)
    username = Column(String(200), nullable=False)
    account = Column(String(200), nullable=False)
    history_complete = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class WechatChannelVideo(Base):
    """只保存视频元数据，不缓存媒体或带签名的下载地址。"""

    __tablename__ = "wechat_channel_videos"
    __table_args__ = (Index("ix_wechat_channel_video_date", "channel_id", "published_at"),)

    channel_id = Column(String(64), ForeignKey("wechat_channels.id", ondelete="CASCADE"), primary_key=True)
    oid = Column(String(128), primary_key=True)
    title = Column(Text, nullable=False, default="")
    published_at = Column(BigInteger, nullable=False, default=0)


class VideoCollectorDevice(Base):
    """配对到单个用户的本机微信采集端；令牌仅保存摘要。"""

    __tablename__ = "wechat_collector_devices"

    device_id = Column(String(64), primary_key=True)
    owner_uid = Column(String(64), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    platform = Column(String(16), nullable=False)
    token_digest = Column(String(64), nullable=False, unique=True)
    state = Column(JSON_VALUE, nullable=False, default=dict)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class VideoCollectorCapture(Base):
    """本机采集回传的交接物，由持有任务租约的 Worker 提交归档。"""

    __tablename__ = "wechat_collector_captures"
    __table_args__ = (UniqueConstraint("task_id", "execution_id", "sequence", name="uq_wechat_capture_sequence"),)

    capture_id = Column(String(64), primary_key=True)
    task_id = Column(String(32), nullable=False, index=True)
    execution_id = Column(String(128), nullable=False)
    device_id = Column(String(64), ForeignKey("wechat_collector_devices.device_id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    detail = Column(JSON_VALUE, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeChunk(Base):
    """知识库 Chunk 模型"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("chunk_id", name="uq_knowledge_chunks_chunk_id"),
        Index("ix_knowledge_chunks_file_id", "file_id"),
        Index("ix_knowledge_chunks_kb_id", "kb_id"),
        Index("ix_knowledge_chunks_graph_indexed", "graph_indexed"),
        Index("ix_knowledge_chunks_graph_structure_indexed", "graph_structure_indexed"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chunk_id = Column(String(128), nullable=False)
    file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    start_char_pos = Column(Integer)
    end_char_pos = Column(Integer)
    start_token_pos = Column(Integer)
    end_token_pos = Column(Integer)
    document_version = Column(Integer, nullable=False, default=1)
    page_number = Column(Integer)
    block_type = Column(String(64))
    heading_path = Column(JSON_VALUE, nullable=False, default=list)
    bbox = Column(JSON_VALUE)
    parser_name = Column(String(128))
    parser_version = Column(String(128))
    source_metadata = Column(JSON_VALUE)
    graph_structure_indexed = Column(Boolean, default=False, nullable=False)
    graph_indexed = Column(Boolean, default=False)
    graph_excluded = Column(Boolean, default=False, nullable=False)
    graph_exclusion_reason = Column(Text)
    graph_extraction_details = Column(
        JSON_VALUE,
        default=lambda: {"status": "pending", "attempt_count": 0},
        nullable=False,
    )
    ent_ids = Column(JSON_VALUE)
    tags = Column(JSON_VALUE)
    extraction_result = Column(JSON_VALUE)
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeSourceDocument(Base):
    """纳入图谱构建的论文、专利或其他来源文档。"""

    __tablename__ = "knowledge_source_documents"
    __table_args__ = (UniqueConstraint("kb_id", "file_id", name="uq_knowledge_source_document_file"),)

    document_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(32), nullable=False, default="unknown")
    language = Column(String(32), nullable=False, default="unknown")
    domain = Column(String(256), nullable=False, default="")
    content_hash = Column(String(128))
    current_version = Column(Integer, nullable=False, default=1)
    source_metadata = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeDocumentVersion(Base):
    """来源文档的不可变内容与解析器版本快照。"""

    __tablename__ = "knowledge_document_versions"

    document_id = Column(
        String(64),
        ForeignKey("knowledge_source_documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    version = Column(Integer, primary_key=True)
    content_hash = Column(String(128), nullable=False)
    parser_name = Column(String(128))
    parser_version = Column(String(128))
    input_hash = Column(String(128), nullable=False)
    source_metadata = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeDocumentTriage(Base):
    """文档进入知识抽取前的可审计研究资料分流结果。"""

    __tablename__ = "knowledge_document_triage"
    __table_args__ = (
        Index("ix_knowledge_document_triage_eligibility", "kb_id", "eligible_for_extraction", "triage_level"),
    )

    document_id = Column(
        String(64),
        ForeignKey("knowledge_source_documents.document_id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_version = Column(Integer, primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    document_kind = Column(String(32), nullable=False)
    triage_level = Column(String(32), nullable=False)
    eligible_for_extraction = Column(Boolean, nullable=False, default=True)
    reason = Column(Text, nullable=False, default="")
    signals = Column(JSON_VALUE, nullable=False, default=dict)
    evidence = Column(JSON_VALUE, nullable=False, default=list)
    rule_version = Column(String(128), nullable=False)
    input_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeResearchThread(Base):
    """由权威实体、关系和证据归纳的文档研究主线或辅线。"""

    __tablename__ = "knowledge_research_threads"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "document_version",
            "thread_key",
            "pipeline_revision",
            name="uq_knowledge_research_thread_revision",
        ),
        Index("ix_knowledge_research_thread_document", "kb_id", "document_id", "document_version"),
    )

    thread_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    document_id = Column(
        String(64), ForeignKey("knowledge_source_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    document_version = Column(Integer, nullable=False)
    thread_key = Column(String(512), nullable=False)
    thread_type = Column(String(16), nullable=False)
    title = Column(Text, nullable=False)
    technical_line = Column(JSON_VALUE, nullable=False, default=list)
    capability_direction = Column(JSON_VALUE, nullable=False, default=list)
    application_direction = Column(JSON_VALUE, nullable=False, default=list)
    military_value = Column(JSON_VALUE, nullable=False, default=dict)
    innovation_signals = Column(JSON_VALUE, nullable=False, default=list)
    entity_ids = Column(JSON_VALUE, nullable=False, default=list)
    relation_ids = Column(JSON_VALUE, nullable=False, default=list)
    evidence_refs = Column(JSON_VALUE, nullable=False, default=list)
    uncertainty = Column(Text, nullable=False, default="")
    confidence = Column(Float, nullable=False)
    pipeline_revision = Column(String(128), nullable=False)
    governance_status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeDocumentCard(Base):
    """面向人工审计和平台集成的文档级知识卡。"""

    __tablename__ = "knowledge_document_cards"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "document_version",
            "pipeline_revision",
            name="uq_knowledge_document_card_revision",
        ),
        Index("ix_knowledge_document_card_status", "kb_id", "governance_status", "updated_at"),
    )

    card_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    document_id = Column(
        String(64), ForeignKey("knowledge_source_documents.document_id", ondelete="CASCADE"), nullable=False
    )
    document_version = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    source_summary = Column(JSON_VALUE, nullable=False, default=dict)
    triage = Column(JSON_VALUE, nullable=False, default=dict)
    content_overview = Column(Text, nullable=False, default="")
    main_thread_id = Column(String(64))
    sub_thread_ids = Column(JSON_VALUE, nullable=False, default=list)
    core_entity_ids = Column(JSON_VALUE, nullable=False, default=list)
    core_relation_ids = Column(JSON_VALUE, nullable=False, default=list)
    technology_families = Column(JSON_VALUE, nullable=False, default=list)
    capability_gains = Column(JSON_VALUE, nullable=False, default=list)
    application_directions = Column(JSON_VALUE, nullable=False, default=list)
    evidence_refs = Column(JSON_VALUE, nullable=False, default=list)
    maturity = Column(JSON_VALUE, nullable=False, default=dict)
    heat_signals = Column(JSON_VALUE, nullable=False, default=dict)
    innovation_potential = Column(JSON_VALUE, nullable=False, default=dict)
    key_metrics = Column(JSON_VALUE, nullable=False, default=list)
    transfer_potential = Column(JSON_VALUE, nullable=False, default=dict)
    graph_rag_hints = Column(JSON_VALUE, nullable=False, default=dict)
    narrative_report = Column(JSON_VALUE, nullable=False, default=dict)
    uncertainty = Column(Text, nullable=False, default="")
    pipeline_revision = Column(String(128), nullable=False)
    ontology_version = Column(String(128), nullable=False)
    governance_status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphEntity(Base):
    """知识图谱实体"""

    __tablename__ = "knowledge_graph_entities"
    __table_args__ = (
        UniqueConstraint("entity_id", name="uq_knowledge_graph_entities_entity_id"),
        UniqueConstraint("kb_id", "normalized_name", "label", name="uq_knowledge_graph_entities_identity"),
        Index("ix_knowledge_graph_entities_kb_id", "kb_id"),
        Index("ix_knowledge_graph_entities_vector_pending", "kb_id", "vector_status", "vector_next_retry_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(64), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    normalized_name = Column(String(512), nullable=False)
    label = Column(String(128), nullable=False)
    name = Column(String(512), nullable=False)
    attributes = Column(JSON_VALUE)
    lifecycle_status = Column(String(32), nullable=False, default="active")
    superseded_by_entity_id = Column(String(64))
    valid_from = Column(DateTime(timezone=True), default=utc_now)
    valid_to = Column(DateTime(timezone=True))
    entity_version = Column(Integer, nullable=False, default=1)
    vector_status = Column(String(16), nullable=False, default="pending")
    vector_attempt_count = Column(Integer, nullable=False, default=0)
    vector_last_error = Column(Text)
    vector_next_retry_at = Column(DateTime(timezone=True))
    vector_locked_until = Column(DateTime(timezone=True))
    vector_lock_token = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeGraphEntityMention(Base):
    """知识图谱实体在 chunk 中的引用"""

    __tablename__ = "knowledge_graph_entity_mentions"
    __table_args__ = (
        Index(
            "uq_kg_entity_mentions_span",
            "entity_id",
            "chunk_id",
            "start_char",
            "end_char",
            unique=True,
            postgresql_where=text("start_char IS NOT NULL AND end_char IS NOT NULL"),
            sqlite_where=text("start_char IS NOT NULL AND end_char IS NOT NULL"),
        ),
        Index(
            "uq_kg_entity_mentions_unspanned",
            "entity_id",
            "chunk_id",
            unique=True,
            postgresql_where=text("start_char IS NULL OR end_char IS NULL"),
            sqlite_where=text("start_char IS NULL OR end_char IS NULL"),
        ),
        Index("ix_knowledge_graph_entity_mentions_kb_id", "kb_id"),
        Index("ix_knowledge_graph_entity_mentions_file_id", "file_id"),
        Index("ix_knowledge_graph_entity_mentions_chunk_id", "chunk_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(String(128), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), nullable=False)
    mention_text = Column(String(512))
    start_char = Column(Integer)
    end_char = Column(Integer)
    confidence = Column(Float)
    model_version = Column(String(256))
    ontology_version = Column(String(128))
    review_status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), default=utc_now)


class KnowledgeGraphTriple(Base):
    """知识图谱三元组"""

    __tablename__ = "knowledge_graph_triples"
    __table_args__ = (
        UniqueConstraint("triple_id", name="uq_knowledge_graph_triples_triple_id"),
        Index("ix_knowledge_graph_triples_kb_id", "kb_id"),
        Index("ix_kg_triple_lifecycle", "kb_id", "lifecycle_status", "updated_at"),
        Index(
            "ix_kg_triple_superseded_by",
            "kb_id",
            "superseded_by_triple_id",
            postgresql_where=text("superseded_by_triple_id IS NOT NULL"),
            sqlite_where=text("superseded_by_triple_id IS NOT NULL"),
        ),
        CheckConstraint(
            "lifecycle_status IN ('active', 'invalid', 'superseded')",
            name="ck_kg_triple_lifecycle_status",
        ),
        CheckConstraint("relation_version >= 1", name="ck_kg_triple_relation_version"),
        CheckConstraint(
            "(lifecycle_status = 'superseded' AND superseded_by_triple_id IS NOT NULL AND valid_to IS NOT NULL) "
            "OR (lifecycle_status = 'invalid' AND superseded_by_triple_id IS NULL AND valid_to IS NOT NULL) "
            "OR (lifecycle_status = 'active' AND superseded_by_triple_id IS NULL AND valid_to IS NULL)",
            name="ck_kg_triple_supersession",
        ),
        Index("ix_knowledge_graph_triples_vector_pending", "kb_id", "vector_status", "vector_next_retry_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    triple_id = Column(String(64), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    source_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    relation_type = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    lifecycle_status = Column(String(32), nullable=False, default="active")
    superseded_by_triple_id = Column(String(64))
    valid_from = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    valid_to = Column(DateTime(timezone=True))
    relation_version = Column(Integer, nullable=False, default=1)
    vector_status = Column(String(16), nullable=False, default="pending")
    vector_attempt_count = Column(Integer, nullable=False, default=0)
    vector_last_error = Column(Text)
    vector_next_retry_at = Column(DateTime(timezone=True))
    vector_locked_until = Column(DateTime(timezone=True))
    vector_lock_token = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class KnowledgeGraphTripleMention(Base):
    """知识图谱三元组在 chunk 中的引用"""

    __tablename__ = "knowledge_graph_triple_mentions"
    __table_args__ = (
        UniqueConstraint("triple_id", "chunk_id", name="uq_knowledge_graph_triple_mentions_triple_chunk"),
        Index("ix_knowledge_graph_triple_mentions_kb_id", "kb_id"),
        Index("ix_knowledge_graph_triple_mentions_file_id", "file_id"),
        Index("ix_knowledge_graph_triple_mentions_chunk_id", "chunk_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    triple_id = Column(String(64), ForeignKey("knowledge_graph_triples.triple_id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String(64), ForeignKey("knowledge_files.file_id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(String(128), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), nullable=False)
    text = Column(Text)
    extractor_type = Column(String(128))
    claim_level = Column(String(32))
    confidence = Column(Float)
    evidence_quote = Column(Text)
    evidence_spans = Column(JSON_VALUE)
    reasoning_basis = Column(Text)
    applicable_conditions = Column(JSON_VALUE, nullable=False, default=list, server_default="[]")
    secondary_review = Column(JSON_VALUE)
    uncertainty = Column(Text)
    expert_review_required = Column(Boolean, nullable=False, default=True)
    review_status = Column(String(32), nullable=False, default="pending")
    model_version = Column(String(256))
    ontology_version = Column(String(128))
    pipeline_revision = Column(String(128))
    created_at = Column(DateTime(timezone=True), default=utc_now)


class KnowledgeGraphEntityAlias(Base):
    """实体别名与中英文名称映射。"""

    __tablename__ = "knowledge_graph_entity_aliases"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", "language", name="uq_knowledge_graph_entity_alias"),
        Index("ix_knowledge_graph_entity_alias_lookup", "normalized_alias", "language"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    entity_id = Column(String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(512), nullable=False)
    normalized_alias = Column(String(512), nullable=False)
    language = Column(String(32), nullable=False, default="unknown")
    source = Column(String(128), nullable=False, default="extraction")
    confidence = Column(Float)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphRevision(Base):
    """可追溯的图谱变更版本。"""

    __tablename__ = "knowledge_graph_revisions"

    revision_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    parent_revision_id = Column(String(64))
    ontology_version = Column(String(128), nullable=False)
    reason = Column(Text, nullable=False, default="")
    summary = Column(JSON_VALUE, nullable=False, default=dict)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphEntityRedirect(Base):
    """实体合并或拆分后的稳定 ID 跳转。"""

    __tablename__ = "knowledge_graph_entity_redirects"
    __table_args__ = (
        UniqueConstraint("kb_id", "source_entity_id", name="uq_kg_entity_redirect_source"),
        Index("ix_kg_redirect_target", "kb_id", "target_entity_id"),
    )

    redirect_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    source_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    operation = Column(String(32), nullable=False)
    reason = Column(Text, nullable=False, default="")
    redirect_metadata = Column("metadata", JSON_VALUE, nullable=False, default=dict)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphChangeEvent(Base):
    """实体、关系、审核和演化状态的不可变变更事件。"""

    __tablename__ = "knowledge_graph_change_events"
    __table_args__ = (
        Index("ix_kg_change_target", "kb_id", "target_type", "target_id"),
        Index("ix_kg_change_revision", "kb_id", "graph_revision"),
    )

    event_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    graph_revision = Column(String(64), nullable=False)
    event_type = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(128), nullable=False)
    before_payload = Column(JSON_VALUE)
    after_payload = Column(JSON_VALUE)
    reason = Column(Text, nullable=False, default="")
    source_ref = Column(JSON_VALUE, nullable=False, default=dict)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphHypothesis(Base):
    """由图路径推导且尚未成为事实的创新关联候选。"""

    __tablename__ = "knowledge_graph_hypotheses"
    __table_args__ = (
        UniqueConstraint(
            "kb_id",
            "source_entity_id",
            "target_entity_id",
            "relation_type",
            "algorithm_version",
            name="uq_kg_hypothesis_identity",
        ),
        Index("ix_kg_hypothesis_review", "kb_id", "review_status", "score"),
    )

    hypothesis_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    source_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    target_entity_id = Column(
        String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False
    )
    relation_type = Column(String(256), nullable=False)
    discovery_mode = Column(String(32), nullable=False)
    claim_level = Column(String(32), nullable=False, default="Hypothesis")
    score = Column(Float, nullable=False)
    evidence_path = Column(JSON_VALUE, nullable=False)
    mechanism_hypothesis = Column(Text, nullable=False, default="")
    feasibility_basis = Column(JSON_VALUE, nullable=False, default=list)
    expected_effects = Column(JSON_VALUE, nullable=False, default=list)
    applicable_conditions = Column(JSON_VALUE, nullable=False, default=list, server_default="[]")
    uncertainties = Column(JSON_VALUE, nullable=False, default=list)
    algorithm_version = Column(String(128), nullable=False)
    review_status = Column(String(32), nullable=False, default="pending")
    reviewed_by = Column(String(64))
    reviewed_at = Column(DateTime(timezone=True))
    review_reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphTrendSnapshot(Base):
    """可复现的技术前沿度、成熟度和爆发趋势快照。"""

    __tablename__ = "knowledge_graph_trend_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "kb_id",
            "entity_id",
            "as_of",
            "algorithm_version",
            name="uq_kg_trend_snapshot",
        ),
        Index("ix_kg_trend_entity_time", "kb_id", "entity_id", "as_of"),
    )

    snapshot_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(String(64), ForeignKey("knowledge_graph_entities.entity_id", ondelete="CASCADE"), nullable=False)
    as_of = Column(DateTime(timezone=True), nullable=False)
    algorithm_version = Column(String(128), nullable=False)
    frontier_score = Column(Float, nullable=False)
    maturity_stage = Column(String(32), nullable=False)
    burst_level = Column(String(32), nullable=False)
    component_scores = Column(JSON_VALUE, nullable=False)
    time_series = Column(JSON_VALUE, nullable=False)
    evidence = Column(JSON_VALUE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphBuildRun(Base):
    """一次可复现的知识图谱构建运行。"""

    __tablename__ = "knowledge_graph_build_runs"

    run_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_revision = Column(String(128), nullable=False)
    ontology_version = Column(String(128), nullable=False)
    model_versions = Column(JSON_VALUE, nullable=False, default=dict)
    input_hash = Column(String(128))
    output_hash = Column(String(128))
    status = Column(String(32), nullable=False, default="pending")
    scope = Column(String(32), nullable=False, default="pending")
    document_ids = Column(JSON_VALUE, nullable=False, default=list)
    rule_version = Column(String(128))
    started_by = Column(String(64))
    attempt_count = Column(Integer, nullable=False, default=1)
    metrics = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at = Column(DateTime(timezone=True))


class KnowledgeGraphBuildStageRun(Base):
    """一次构建运行中可审计的处理阶段。"""

    __tablename__ = "knowledge_graph_build_stage_runs"
    __table_args__ = (
        UniqueConstraint("run_id", "stage_code", "attempt_count", name="uq_kg_build_stage_attempt"),
        Index("ix_kg_build_stage_run_order", "run_id", "stage_order", "attempt_count"),
        Index("ix_kg_build_stage_kb_status", "kb_id", "status", "started_at"),
        CheckConstraint("stage_order >= 0", name="ck_kg_build_stage_order"),
        CheckConstraint("attempt_count >= 1", name="ck_kg_build_stage_attempt"),
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'cancelled', 'skipped')",
            name="ck_kg_build_stage_status",
        ),
    )

    stage_run_id = Column(String(64), primary_key=True)
    run_id = Column(String(64), ForeignKey("knowledge_graph_build_runs.run_id", ondelete="CASCADE"), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    stage_code = Column(String(64), nullable=False)
    stage_order = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="processing")
    input_hash = Column(String(64), nullable=False)
    output_hash = Column(String(64))
    model_versions = Column(JSON_VALUE, nullable=False, default=dict)
    ontology_version = Column(String(128), nullable=False)
    rule_version = Column(String(128), nullable=False)
    metrics = Column(JSON_VALUE, nullable=False, default=dict)
    error = Column(Text, nullable=False, default="")
    attempt_count = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at = Column(DateTime(timezone=True))


class KnowledgeGraphEvaluationRun(Base):
    """密封测试与 Pilot 验收报告的权威登记。"""

    __tablename__ = "knowledge_graph_evaluation_runs"

    evaluation_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_revision = Column(String(128), nullable=False)
    gold_manifest_sha256 = Column(String(64), nullable=False)
    prediction_sha256 = Column(String(64), nullable=False)
    report = Column(JSON_VALUE, nullable=False)
    status = Column(String(32), nullable=False)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphProjectionOutbox(Base):
    """PostgreSQL 权威提交后的 Neo4j 投影事件。"""

    __tablename__ = "knowledge_graph_projection_outbox"
    __table_args__ = (
        UniqueConstraint("chunk_id", "graph_revision", name="uq_knowledge_graph_projection_chunk_revision"),
        Index("ix_kg_projection_outbox_pending", "status", "next_retry_at", "created_at"),
    )

    event_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    chunk_id = Column(String(128), ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), nullable=False)
    graph_revision = Column(String(64))
    payload = Column(JSON_VALUE, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(Text)
    next_retry_at = Column(DateTime(timezone=True))
    locked_until = Column(DateTime(timezone=True))
    lock_token = Column(String(32))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class OntologyVersion(Base):
    """版本化本体定义。"""

    __tablename__ = "ontology_versions"

    version = Column(String(128), primary_key=True)
    name = Column(String(255), nullable=False)
    definition = Column(JSON_VALUE, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    previous_version = Column(String(128))
    change_reason = Column(Text, nullable=False, default="")
    created_by = Column(String(64))
    effective_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class OntologyEntityType(Base):
    """本体实体类型快照。"""

    __tablename__ = "ontology_entity_types"

    ontology_version = Column(
        String(128), ForeignKey("ontology_versions.version", ondelete="CASCADE"), primary_key=True
    )
    code = Column(String(128), primary_key=True)
    name_zh = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    definition = Column(JSON_VALUE, nullable=False, default=dict)


class OntologyRelationType(Base):
    """本体关系类型与端点约束快照。"""

    __tablename__ = "ontology_relation_types"

    ontology_version = Column(
        String(128), ForeignKey("ontology_versions.version", ondelete="CASCADE"), primary_key=True
    )
    code = Column(String(256), primary_key=True)
    name_zh = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    head_types = Column(JSON_VALUE, nullable=False)
    tail_types = Column(JSON_VALUE, nullable=False)
    directed = Column(Boolean, nullable=False, default=True)
    allow_self = Column(Boolean, nullable=False, default=False)
    hypothesis_only = Column(Boolean, nullable=False, default=False)
    definition = Column(JSON_VALUE, nullable=False, default=dict)


class KnowledgeGraphReviewDecision(Base):
    """不可变人工审核决定。"""

    __tablename__ = "knowledge_graph_review_decisions"

    decision_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)
    target_id = Column(String(128), nullable=False)
    decision = Column(String(32), nullable=False)
    previous_payload = Column(JSON_VALUE)
    decided_payload = Column(JSON_VALUE)
    reason = Column(Text, nullable=False, default="")
    reviewer_uid = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphConflict(Base):
    """知识候选之间或候选自身的可裁决冲突。"""

    __tablename__ = "knowledge_graph_conflicts"
    __table_args__ = (
        UniqueConstraint("kb_id", "fingerprint", name="uq_kg_conflict_fingerprint"),
        Index("ix_kg_conflict_queue", "kb_id", "status", "severity", "created_at"),
        Index("ix_kg_conflict_left_target", "kb_id", "left_target_type", "left_target_id", "status"),
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed', 'superseded')",
            name="ck_kg_conflict_status",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_kg_conflict_severity",
        ),
        CheckConstraint(
            "left_target_type IN ('entity_mention', 'relation_mention', 'entity', 'relation')",
            name="ck_kg_conflict_left_target",
        ),
        CheckConstraint(
            "right_target_type IS NULL "
            "OR right_target_type IN ('entity_mention', 'relation_mention', 'entity', 'relation')",
            name="ck_kg_conflict_right_target",
        ),
        CheckConstraint(
            "(right_target_type IS NULL AND right_target_id IS NULL) "
            "OR (right_target_type IS NOT NULL AND right_target_id IS NOT NULL)",
            name="ck_kg_conflict_right_pair",
        ),
    )

    conflict_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    conflict_type = Column(String(64), nullable=False)
    left_target_type = Column(String(32), nullable=False)
    left_target_id = Column(String(128), nullable=False)
    right_target_type = Column(String(32))
    right_target_id = Column(String(128))
    status = Column(String(32), nullable=False, default="open")
    severity = Column(String(16), nullable=False, default="medium")
    summary = Column(Text, nullable=False)
    details = Column(JSON_VALUE, nullable=False, default=dict)
    detected_by = Column(String(64), nullable=False)
    resolution = Column(Text, nullable=False, default="")
    resolved_by = Column(String(64))
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphAnnotationCampaign(Base):
    """固定本体、规范和文档切分的双标活动。"""

    __tablename__ = "knowledge_graph_annotation_campaigns"
    __table_args__ = (
        Index("ix_kg_annotation_campaign_kb_status", "kb_id", "status", "created_at"),
        CheckConstraint(
            "status IN ('draft', 'active', 'adjudicating', 'completed', 'sealed')",
            name="ck_kg_annotation_campaign_status",
        ),
    )

    campaign_id = Column(String(64), primary_key=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    guideline_version = Column(String(128), nullable=False)
    ontology_version = Column(String(128), nullable=False)
    pilot_mode = Column(Boolean, nullable=False, default=True)
    acceptance_languages = Column(JSON_VALUE, nullable=False, default=lambda: ["en", "zh"])
    status = Column(String(32), nullable=False, default="active")
    created_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphAnnotationAssignment(Base):
    """一篇来源文档的两名独立标注员与第三名仲裁专家。"""

    __tablename__ = "knowledge_graph_annotation_assignments"
    __table_args__ = (
        UniqueConstraint("campaign_id", "document_id", name="uq_kg_annotation_campaign_document"),
        ForeignKeyConstraint(
            ["document_id", "document_version"],
            ["knowledge_document_versions.document_id", "knowledge_document_versions.version"],
            name="fk_kg_annotation_assignment_document_version",
            ondelete="CASCADE",
        ),
        Index("ix_kg_annotation_assignment_campaign_status", "campaign_id", "status"),
        Index("ix_kg_annotation_assignment_annotator_a", "annotator_a_uid", "status"),
        Index("ix_kg_annotation_assignment_annotator_b", "annotator_b_uid", "status"),
        Index("ix_kg_annotation_assignment_arbitrator", "arbitrator_uid", "status"),
        CheckConstraint(
            "document_version > 0",
            name="ck_kg_annotation_assignment_document_version",
        ),
        CheckConstraint("split IN ('train', 'dev', 'test')", name="ck_kg_annotation_assignment_split"),
        CheckConstraint(
            "status IN ('assigned', 'annotating', 'awaiting_adjudication', 'adjudicating', 'completed')",
            name="ck_kg_annotation_assignment_status",
        ),
        CheckConstraint(
            "annotator_a_uid <> annotator_b_uid "
            "AND annotator_a_uid <> arbitrator_uid "
            "AND annotator_b_uid <> arbitrator_uid",
            name="ck_kg_annotation_assignment_distinct_roles",
        ),
    )

    assignment_id = Column(String(64), primary_key=True)
    campaign_id = Column(
        String(64),
        ForeignKey("knowledge_graph_annotation_campaigns.campaign_id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id = Column(
        String(64),
        nullable=False,
    )
    document_version = Column(Integer, nullable=False)
    split = Column(String(16), nullable=False)
    annotator_a_uid = Column(String(128), nullable=False)
    annotator_b_uid = Column(String(128), nullable=False)
    arbitrator_uid = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False, default="assigned")
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphAnnotationSubmission(Base):
    """标注员每次提交的不可变版本。"""

    __tablename__ = "knowledge_graph_annotation_submissions"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "annotator_uid",
            "revision",
            name="uq_kg_annotation_submission_revision",
        ),
        Index("ix_kg_annotation_submission_latest", "assignment_id", "annotator_uid", "revision"),
        CheckConstraint("revision > 0", name="ck_kg_annotation_submission_revision"),
    )

    submission_id = Column(String(64), primary_key=True)
    assignment_id = Column(
        String(64),
        ForeignKey("knowledge_graph_annotation_assignments.assignment_id", ondelete="CASCADE"),
        nullable=False,
    )
    annotator_uid = Column(String(128), nullable=False)
    revision = Column(Integer, nullable=False)
    annotation_payload = Column(JSON_VALUE, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    submitted_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class KnowledgeGraphAnnotationDraft(Base):
    """标注员本人可反复保存、尚未形成正式 revision 的工作草稿。"""

    __tablename__ = "knowledge_graph_annotation_drafts"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "annotator_uid",
            name="uq_kg_annotation_draft_assignment_annotator",
        ),
        Index("ix_kg_annotation_draft_annotator_updated", "annotator_uid", "updated_at"),
        CheckConstraint(
            "source_kind IN ('ai_prelabel', 'manual')",
            name="ck_kg_annotation_draft_source_kind",
        ),
    )

    draft_id = Column(String(64), primary_key=True)
    assignment_id = Column(
        String(64),
        ForeignKey("knowledge_graph_annotation_assignments.assignment_id", ondelete="CASCADE"),
        nullable=False,
    )
    annotator_uid = Column(String(128), nullable=False)
    annotation_payload = Column(JSON_VALUE, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    source_kind = Column(String(32), nullable=False, default="manual")
    provenance = Column(JSON_VALUE, nullable=False, default=dict)
    last_submitted_draft_sha256 = Column(String(64))
    last_submitted_revision = Column(Integer)
    last_submitted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class KnowledgeGraphAnnotationAdjudication(Base):
    """第三名专家对两份独立标注形成的不可变金标终稿。"""

    __tablename__ = "knowledge_graph_annotation_adjudications"
    __table_args__ = (UniqueConstraint("assignment_id", name="uq_kg_annotation_adjudication_assignment"),)

    adjudication_id = Column(String(64), primary_key=True)
    assignment_id = Column(
        String(64),
        ForeignKey("knowledge_graph_annotation_assignments.assignment_id", ondelete="CASCADE"),
        nullable=False,
    )
    arbitrator_uid = Column(String(128), nullable=False)
    final_payload = Column(JSON_VALUE, nullable=False)
    payload_sha256 = Column(String(64), nullable=False)
    disagreement_summary = Column(JSON_VALUE, nullable=False, default=dict, server_default="{}")
    adjudicated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class EvaluationDataset(Base):
    """评估数据集模型"""

    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("dataset_id", name="uq_evaluation_datasets_dataset_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(64), unique=True, nullable=False, index=True)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    item_count = Column(Integer, default=0)
    has_gold_chunks = Column(Boolean, default=False)
    has_gold_answers = Column(Boolean, default=False)
    build_metadata = Column(JSON_VALUE)
    created_by = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utc_now)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class EvaluationDatasetItem(Base):
    """评估数据集题目模型"""

    __tablename__ = "evaluation_dataset_items"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_evaluation_dataset_items_item_id"),
        UniqueConstraint("dataset_id", "item_index", name="uq_evaluation_dataset_items_dataset_index"),
        Index("ix_evaluation_dataset_items_dataset_index", "dataset_id", "item_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), unique=True, nullable=False, index=True)
    dataset_id = Column(
        String(64),
        ForeignKey("evaluation_datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    item_index = Column(Integer, nullable=False)
    query_text = Column(Text, nullable=False)
    gold_chunk_ids = Column(JSON_VALUE)
    gold_answer = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utc_now)


class EvaluationRun(Base):
    """评估运行模型"""

    __tablename__ = "evaluation_runs"
    __table_args__ = (UniqueConstraint("run_id", name="uq_evaluation_runs_run_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    kb_id = Column(String(80), ForeignKey("knowledge_bases.kb_id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_id = Column(
        String(64),
        ForeignKey("evaluation_datasets.dataset_id", ondelete="SET NULL"),
        index=True,
    )
    status = Column(String(32), default="running", index=True)
    retrieval_config = Column(JSON_VALUE)
    metrics = Column(JSON_VALUE)
    overall_score = Column(Float)
    total_items = Column(Integer, default=0)
    completed_items = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), default=utc_now, index=True)
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(String(64))


class EvaluationRunItem(Base):
    """评估逐题结果模型"""

    __tablename__ = "evaluation_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "item_index", name="uq_evaluation_run_items_run_index"),
        Index("ix_evaluation_run_items_run_index", "run_id", "item_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(
        String(64),
        ForeignKey("evaluation_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_item_id = Column(
        String(64), ForeignKey("evaluation_dataset_items.item_id", ondelete="SET NULL"), index=True
    )
    item_index = Column(Integer, nullable=False)
    query_text = Column(Text, nullable=False)
    gold_chunk_ids = Column(JSON_VALUE)
    gold_answer = Column(Text)
    generated_answer = Column(Text)
    retrieved_chunks = Column(JSON_VALUE)
    metrics = Column(JSON_VALUE)
    created_at = Column(DateTime(timezone=True), default=utc_now)
