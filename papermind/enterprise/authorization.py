from dataclasses import replace

from fastapi import HTTPException

from papermind.models import SearchFilter
from papermind.service import validate_collection


def authorize(access, actor, collection, write=False, document_id=None):
    validate_collection(collection)
    if actor is None or not access.allowed(actor, collection, write, document_id):
        access.audit(actor.id if actor else "anonymous", "permission.denied", document_id or collection, {"write": write})
        raise HTTPException(403, "你没有访问此知识库或资料的权限。")


def require_admin(access, actor):
    if actor is None or (access.enabled() and actor.role != "admin"):
        raise HTTPException(403, "此操作仅允许管理员执行。")
    if not access.allowed(actor, "default") and actor.role == "admin":
        raise HTTPException(403, "管理员账号不可用。")


def allowed_documents(service, access, actor, collection):
    authorize(access, actor, collection)
    return [row for row in service.store.list_documents(collection)
            if access.allowed(actor, collection, document_id=row["document_id"])]


def authorized_filter(service, access, actor, collection, filters=None):
    allowed = {row["document_id"] for row in allowed_documents(service, access, actor, collection)}
    filters = filters or SearchFilter()
    selected = allowed if filters.document_ids is None else allowed.intersection(filters.document_ids)
    return replace(filters, document_ids=tuple(sorted(selected)))


class AuthorizedStore:
    def __init__(self, service, access, actor, collection, scope_ids=None):
        self._service, self._access, self._actor, self._collection = service, access, actor, collection
        self._scope_ids = frozenset(scope_ids) if scope_ids is not None else None

    def _check(self, collection, identity=None):
        if collection != self._collection:
            raise HTTPException(403, "工具不能切换知识库。")
        if identity and self._scope_ids is not None and identity not in self._scope_ids:
            raise HTTPException(403, "资料不在本次任务范围内。")
        authorize(self._access, self._actor, collection, document_id=identity)

    def list_documents(self, collection):
        self._check(collection)
        return [d for d in allowed_documents(self._service, self._access, self._actor, collection)
                if self._scope_ids is None or d["document_id"] in self._scope_ids]

    def get(self, document_id, collection):
        self._check(collection, document_id)
        return self._service.store.get(document_id, collection)

    def source(self, chunk_id, collection):
        self._check(collection)
        source = self._service.store.source(chunk_id, collection)
        self._check(collection, source["document_id"])
        return source


class AuthorizedService:
    """后台工具只持有带权限检查的接口，每次调用重新检查授权。"""
    def __init__(self, service, access, actor, collection, scope_ids=None):
        self._service, self._access, self._actor, self._collection = service, access, actor, collection
        self.store = AuthorizedStore(service, access, actor, collection, scope_ids)
        self._lock = service._lock

    @property
    def api_endpoints(self):
        return self._service.api_endpoints

    @property
    def settings(self):
        return self._service.settings

    def search(self, question, collection="default", k=5, filters=None, mode="auto"):
        self.store._check(collection)
        filters = authorized_filter(self._service, self._access, self._actor, collection, filters)
        if self.store._scope_ids is not None:
            filters = replace(filters, document_ids=tuple(set(filters.document_ids).intersection(self.store._scope_ids)))
        return self._service.search(question, collection, k,
            filters, mode)
