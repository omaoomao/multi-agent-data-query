"""
长期记忆管理器（纯 ChromaDB 实现）

负责用户偏好、知识的存储、检索和更新。
使用两个 ChromaDB collection：
- user_knowledge: 用户知识（语义搜索）
- user_meta: 用户 profile + 偏好（精确查询）
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Any

import chromadb

import logging
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_MAX_KNOWLEDGE_PER_USER = 100
DEDUP_SIMILARITY_THRESHOLD = 0.9  # cosine similarity 超过此值视为重复


class LongTermMemory:
    """长期记忆管理器 - 跨会话持久化用户信息（纯 ChromaDB）"""

    def __init__(
        self,
        chroma_path: str = "./data/chroma_db",
        max_knowledge_per_user: int = DEFAULT_MAX_KNOWLEDGE_PER_USER,
    ):
        self.max_knowledge_per_user = max_knowledge_per_user

        # ChromaDB client
        self.chroma_client = chromadb.PersistentClient(path=chroma_path)

        # Collection 1: 用户知识（语义搜索）
        self.knowledge_collection = self.chroma_client.get_or_create_collection(
            name="user_knowledge",
            metadata={"hnsw:space": "cosine"},
        )

        # Collection 2: 用户 profile + 偏好（精确查询）
        self.meta_collection = self.chroma_client.get_or_create_collection(
            name="user_meta",
            metadata={"hnsw:space": "cosine"},
        )

        # 自增 knowledge ID 计数器
        self._next_knowledge_id = self._init_next_id()

    def _init_next_id(self) -> int:
        """从现有数据中推算下一个 knowledge_id"""
        try:
            all_ids = self.knowledge_collection.get()["ids"]
            max_id = 0
            for cid in all_ids:
                # 格式: "{user_id}_{knowledge_id}"
                parts = cid.rsplit("_", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    max_id = max(max_id, int(parts[1]))
            return max_id + 1
        except Exception:
            return 1

    def _gen_knowledge_id(self) -> int:
        """生成下一个 knowledge_id"""
        kid = self._next_knowledge_id
        self._next_knowledge_id += 1
        return kid

    # ------------------------------------------------------------------
    # 用户管理
    # ------------------------------------------------------------------

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """获取用户概况"""
        try:
            result = self.meta_collection.get(ids=[f"user_{user_id}"])
            if result["metadatas"] and result["metadatas"][0]:
                meta = result["metadatas"][0]
                return {
                    "user_id": meta.get("user_id"),
                    "created_at": meta.get("created_at"),
                    "last_active": meta.get("last_active"),
                }
        except Exception:
            pass
        return None

    def create_or_update_user(self, user_id: str) -> bool:
        """创建或更新用户记录"""
        try:
            now = datetime.now().isoformat()
            existing = self.meta_collection.get(ids=[f"user_{user_id}"])
            created_at = now
            if existing["metadatas"] and existing["metadatas"][0]:
                created_at = existing["metadatas"][0].get("created_at", now)

            self.meta_collection.upsert(
                ids=[f"user_{user_id}"],
                documents=[""],
                metadatas=[{
                    "type": "user",
                    "user_id": user_id,
                    "created_at": created_at,
                    "last_active": now,
                }],
            )
            return True
        except Exception as e:
            logger.error(f"创建/更新用户失败: {e}")
            return False

    def update_user_activity(self, user_id: str) -> bool:
        """更新用户最后活跃时间"""
        return self.create_or_update_user(user_id)

    # ------------------------------------------------------------------
    # 用户偏好管理
    # ------------------------------------------------------------------

    def save_preference(self, user_id: str, key: str, value: str) -> bool:
        """保存用户偏好（UPSERT）"""
        try:
            # 确保用户存在
            self.create_or_update_user(user_id)

            self.meta_collection.upsert(
                ids=[f"pref_{user_id}_{key}"],
                documents=[f"{key}: {value}"],
                metadatas=[{
                    "type": "preference",
                    "user_id": user_id,
                    "key": key,
                    "value": value,
                    "updated_at": datetime.now().isoformat(),
                }],
            )
            return True
        except Exception as e:
            logger.error(f"保存偏好失败: {e}")
            return False

    def get_preference(self, user_id: str, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取单个用户偏好"""
        try:
            result = self.meta_collection.get(ids=[f"pref_{user_id}_{key}"])
            if result["metadatas"] and result["metadatas"][0]:
                return result["metadatas"][0].get("value", default)
        except Exception:
            pass
        return default

    def get_all_preferences(self, user_id: str) -> Dict[str, str]:
        """获取用户的所有偏好"""
        try:
            result = self.meta_collection.get(
                where={"$and": [
                    {"type": {"$eq": "preference"}},
                    {"user_id": {"$eq": user_id}},
                ]},
            )
            prefs = {}
            for meta in result.get("metadatas", []):
                if meta.get("key"):
                    prefs[meta["key"]] = meta.get("value", "")
            return prefs
        except Exception as e:
            logger.warning(f"获取偏好失败: {e}")
            return {}

    def delete_preference(self, user_id: str, key: str) -> bool:
        """删除用户偏好"""
        try:
            self.meta_collection.delete(ids=[f"pref_{user_id}_{key}"])
            return True
        except Exception as e:
            logger.error(f"删除偏好失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 用户知识管理
    # ------------------------------------------------------------------

    def save_knowledge(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float = 0.8,
    ) -> bool:
        """保存用户知识（写入前去重 + 容量控制）

        Returns:
            True 表示写入成功，False 表示被去重跳过
        """
        if not content or not content.strip():
            return False

        # 1) 去重：语义相似度检查
        try:
            existing = self.knowledge_collection.query(
                query_texts=[content],
                n_results=1,
                where={"user_id": user_id},
            )
            if existing["distances"] and existing["distances"][0]:
                distance = existing["distances"][0][0]
                similarity = 1.0 - distance
                if similarity >= DEDUP_SIMILARITY_THRESHOLD:
                    logger.debug(f"[LTM] 知识去重：跳过相似度 {similarity:.2f} 的内容: {content[:50]}")
                    return False
        except Exception as e:
            logger.debug(f"[LTM] 去重查询失败（继续写入）: {e}")

        # 2) 容量控制
        try:
            count = self.knowledge_collection.count(where={"user_id": user_id})
            if count >= self.max_knowledge_per_user:
                self._evict_oldest_knowledge(user_id)
        except Exception:
            pass

        # 3) 写入
        try:
            knowledge_id = self._gen_knowledge_id()
            now = datetime.now().isoformat()
            self.knowledge_collection.add(
                ids=[f"{user_id}_{knowledge_id}"],
                documents=[content],
                metadatas=[{
                    "user_id": user_id,
                    "category": category,
                    "confidence": confidence,
                    "knowledge_id": knowledge_id,
                    "created_at": now,
                }],
            )
            return True
        except Exception as e:
            logger.error(f"保存知识失败: {e}")
            return False

    def _evict_oldest_knowledge(self, user_id: str):
        """删除该用户最旧且置信度最低的一批 knowledge"""
        try:
            evict_count = max(1, self.max_knowledge_per_user // 10)
            # 获取该用户所有知识，按 confidence ASC, created_at ASC 排序
            all_items = self.knowledge_collection.get(where={"user_id": user_id})
            metas = all_items.get("metadatas", [])
            ids = all_items.get("ids", [])

            if not ids:
                return

            # 按 confidence 升序、created_at 升序排序
            paired = list(zip(ids, metas))
            paired.sort(key=lambda x: (x[1].get("confidence", 0), x[1].get("created_at", "")))

            ids_to_remove = [p[0] for p in paired[:evict_count]]
            self.knowledge_collection.delete(ids=ids_to_remove)

            logger.info(f"[LTM] 容量淘汰：删除用户 {user_id} 的 {len(ids_to_remove)} 条旧知识")
        except Exception as e:
            logger.warning(f"[LTM] 容量淘汰失败: {e}")

    def get_relevant_knowledge(
        self,
        user_id: str,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """检索与查询相关的用户知识（语义检索）"""
        try:
            results = self.knowledge_collection.query(
                query_texts=[query],
                n_results=top_k,
                where={"user_id": user_id},
            )
            items = []
            if results["ids"] and results["ids"][0]:
                for i, cid in enumerate(results["ids"][0]):
                    meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                    doc = results["documents"][0][i] if results.get("documents") else ""
                    items.append({
                        "knowledge_id": meta.get("knowledge_id"),
                        "category": meta.get("category", ""),
                        "content": doc,
                        "confidence": meta.get("confidence", 0.8),
                        "created_at": meta.get("created_at", ""),
                    })
            return items
        except Exception as e:
            logger.warning(f"ChromaDB 检索失败: {e}")
            return []

    def get_knowledge_by_category(
        self,
        user_id: str,
        category: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """按分类获取用户知识"""
        try:
            result = self.knowledge_collection.get(
                where={"$and": [
                    {"user_id": {"$eq": user_id}},
                    {"category": {"$eq": category}},
                ]},
                limit=limit,
            )
            items = []
            for i, cid in enumerate(result.get("ids", [])):
                meta = result["metadatas"][i] if result.get("metadatas") else {}
                doc = result["documents"][i] if result.get("documents") else ""
                items.append({
                    "knowledge_id": meta.get("knowledge_id"),
                    "category": meta.get("category", ""),
                    "content": doc,
                    "confidence": meta.get("confidence", 0.8),
                    "created_at": meta.get("created_at", ""),
                })
            # 按 created_at 降序
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return items[:limit]
        except Exception as e:
            logger.warning(f"按分类获取知识失败: {e}")
            return []

    def get_all_knowledge(self, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取用户的所有知识"""
        try:
            result = self.knowledge_collection.get(
                where={"user_id": user_id},
                limit=limit,
            )
            items = []
            for i, cid in enumerate(result.get("ids", [])):
                meta = result["metadatas"][i] if result.get("metadatas") else {}
                doc = result["documents"][i] if result.get("documents") else ""
                items.append({
                    "knowledge_id": meta.get("knowledge_id"),
                    "category": meta.get("category", ""),
                    "content": doc,
                    "confidence": meta.get("confidence", 0.8),
                    "created_at": meta.get("created_at", ""),
                })
            # 按 created_at 降序
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return items[:limit]
        except Exception as e:
            logger.warning(f"获取全部知识失败: {e}")
            return []

    def delete_knowledge(self, knowledge_id: int) -> bool:
        """删除指定知识"""
        try:
            # 需要找到对应的 ChromaDB ID
            # 从所有数据中搜索 knowledge_id
            all_data = self.knowledge_collection.get()
            for i, cid in enumerate(all_data.get("ids", [])):
                meta = all_data["metadatas"][i] if all_data.get("metadatas") else {}
                if meta.get("knowledge_id") == knowledge_id:
                    self.knowledge_collection.delete(ids=[cid])
                    return True
            logger.warning(f"未找到 knowledge_id={knowledge_id}")
            return False
        except Exception as e:
            logger.error(f"删除知识失败: {e}")
            return False
