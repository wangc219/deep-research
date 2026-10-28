"""用户私有视频号目录与视频元数据的事务存储。"""

import hashlib

from sqlalchemy import String, all_, bindparam, delete, func, or_, select
from sqlalchemy.dialects.postgresql import ARRAY, insert

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import WechatChannel, WechatChannelVideo
from platform_core.utils.datetime_utils import utc_now


class WechatChannelRepository:
    """所有目录读取、合并和删除都使用服务端身份过滤。"""

    async def find(self, owner_uid: str, account: str):
        """账号 ID 优先匹配；昵称对应已保存的视频号。"""
        async with pg_manager.get_async_session_context() as session:
            row = await session.scalar(
                select(WechatChannel)
                .where(
                    WechatChannel.owner_uid == owner_uid,
                    or_(WechatChannel.username == account, WechatChannel.account == account),
                )
                .order_by((WechatChannel.username == account).desc(), WechatChannel.updated_at.desc())
                .limit(1)
            )
            if row is None:
                return None
            known = (
                await session.scalars(
                    select(WechatChannelVideo.oid)
                    .where(WechatChannelVideo.channel_id == row.id)
                    .order_by(WechatChannelVideo.published_at.desc())
                    .limit(5000)
                )
            ).all()
            return {**self.present(row), "known_oids": list(known)}

    async def merge(self, owner_uid: str, account: str, username: str, videos: list[dict], *, complete: bool):
        """串行合并同一用户账号，重复页和并发同步不会覆盖历史。"""
        channel_id = hashlib.sha256(f"{owner_uid}\0{username}".encode()).hexdigest()
        unique = list({item["oid"]: item for item in videos}.values())
        async with pg_manager.get_async_session_context() as session:
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(channel_id))))
            row = await session.get(WechatChannel, channel_id)
            if row is None:
                row = WechatChannel(
                    id=channel_id, owner_uid=owner_uid, username=username, account=account, history_complete=False
                )
                session.add(row)
                await session.flush()
            before = await session.scalar(
                select(func.count()).select_from(WechatChannelVideo).where(WechatChannelVideo.channel_id == channel_id)
            )
            for offset in range(0, len(unique), 500):
                batch = unique[offset : offset + 500]
                statement = insert(WechatChannelVideo).values(
                    [
                        {
                            "channel_id": channel_id,
                            "oid": item["oid"],
                            "title": item.get("title", ""),
                            "published_at": item.get("published_at", 0),
                        }
                        for item in batch
                    ]
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=[WechatChannelVideo.channel_id, WechatChannelVideo.oid],
                        set_={"title": statement.excluded.title, "published_at": statement.excluded.published_at},
                    )
                )
            if account != username:
                row.account = account
            row.history_complete = row.history_complete or complete
            row.updated_at = utc_now()
            count = await session.scalar(
                select(func.count()).select_from(WechatChannelVideo).where(WechatChannelVideo.channel_id == channel_id)
            )
            return {**self.present(row), "video_count": count, "new_count": count - before}

    async def list_owned(self, owner_uid: str):
        """返回当前用户目录摘要，不加载所有历史视频。"""
        async with pg_manager.get_async_session_context() as session:
            rows = (
                await session.execute(
                    select(WechatChannel, func.count(WechatChannelVideo.oid))
                    .outerjoin(WechatChannelVideo, WechatChannelVideo.channel_id == WechatChannel.id)
                    .where(WechatChannel.owner_uid == owner_uid)
                    .group_by(WechatChannel.id)
                    .order_by(WechatChannel.updated_at.desc())
                )
            ).all()
            return [{**self.present(row), "video_count": count} for row, count in rows]

    async def videos(
        self,
        owner_uid: str,
        channel_id: str,
        *,
        offset: int = 0,
        limit: int | None = 50,
        keyword: str = "",
        published_after: int | None = None,
        published_before: int | None = None,
    ):
        """分页读取本人保存的视频列表，其他用户的 ID 不可见。"""
        async with pg_manager.get_async_session_context() as session:
            row = await session.scalar(
                select(WechatChannel).where(WechatChannel.id == channel_id, WechatChannel.owner_uid == owner_uid)
            )
            if row is None:
                return None
            query = select(WechatChannelVideo).where(WechatChannelVideo.channel_id == channel_id)
            if keyword:
                query = query.where(WechatChannelVideo.title.icontains(keyword, autoescape=True))
            if published_after is not None:
                query = query.where(WechatChannelVideo.published_at >= published_after)
            if published_before is not None:
                query = query.where(WechatChannelVideo.published_at <= published_before)
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            rows = (
                await session.scalars(
                    query.order_by(WechatChannelVideo.published_at.desc(), WechatChannelVideo.oid)
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return {
                **self.present(row),
                "total_count": total,
                "videos": [{"oid": item.oid, "title": item.title, "published_at": item.published_at} for item in rows],
            }

    async def pending_videos(self, owner_uid: str, channel_id: str, completed: set[str], limit: int | None):
        """在数据库内跳过完成项并限量，避免每次更新都传输全部历史。"""
        async with pg_manager.get_async_session_context() as session:
            query = (
                select(WechatChannelVideo)
                .join(WechatChannel)
                .where(
                    WechatChannel.owner_uid == owner_uid,
                    WechatChannel.id == channel_id,
                )
            )
            total = await session.scalar(select(func.count()).select_from(query.subquery()))
            pending = query.where(
                WechatChannelVideo.oid != all_(bindparam("completed_oids", sorted(completed), type_=ARRAY(String)))
            )
            remaining = await session.scalar(select(func.count()).select_from(pending.subquery()))
            rows = (
                await session.scalars(
                    pending.order_by(WechatChannelVideo.published_at.desc(), WechatChannelVideo.oid).limit(limit)
                )
            ).all()
            return {
                "total_count": total,
                "completed_count": total - remaining,
                "videos": [{"oid": row.oid, "title": row.title, "published_at": row.published_at} for row in rows],
            }

    async def delete(self, owner_uid: str, channel_id: str):
        """只删除本人目录及其视频索引，转录文档保持独立。"""
        async with pg_manager.get_async_session_context() as session:
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(channel_id))))
            result = await session.execute(
                delete(WechatChannel).where(WechatChannel.id == channel_id, WechatChannel.owner_uid == owner_uid)
            )
            return bool(result.rowcount)

    @staticmethod
    def present(row):
        """统一目录对外字段。"""
        return {
            "id": row.id,
            "account": row.account,
            "username": row.username,
            "history_complete": row.history_complete,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
