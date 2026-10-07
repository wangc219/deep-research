"""知识库运行时单例。"""

import os

from platform_core.config import get_runtime_dir
from platform_core.knowledge.factory import KnowledgeBaseFactory
from platform_core.knowledge.implementations.dify import DifyKB
from platform_core.knowledge.implementations.milvus import MilvusKB
from platform_core.knowledge.implementations.notion import NotionKB
from platform_core.knowledge.manager import KnowledgeBaseManager

KnowledgeBaseFactory.register(MilvusKB)
KnowledgeBaseFactory.register(DifyKB)
KnowledgeBaseFactory.register(NotionKB)

knowledge_base = KnowledgeBaseManager(os.path.join(get_runtime_dir(), "knowledge_base_data"))
