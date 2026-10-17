"""小说生成 API（前缀 /api/gen），响应 {code, message, data}，code=0 成功。前端直接调用（同 /api/local）。"""
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..local import inference
from ..local.router import LocalError, ok
from . import chapter, defaults, spec as spec_mod, store
from .backends import GenerationError

router = APIRouter(prefix="/api/gen", tags=["novel-generation"])
inference.set_generation_busy_check(lambda: chapter.active_job() is not None)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (store.StoreError, GenerationError, chapter.JobError, RuntimeError) as e:
        raise LocalError(400, str(e)) from e


class ModelRef(BaseModel):
    source: Literal["local", "remote"] = "local"
    baseId: Optional[str] = None
    remoteId: Optional[int] = None  # 预留：远程模型配置 id（暂未接入）


@router.get("/status")
def status():
    """默认模型是否就绪、当前加载的模型、进行中的生成任务。"""
    return ok({"defaultModel": defaults.status(), "inference": inference.status(), "activeJob": chapter.active_job(),
               "contextWindows": list(store.CONTEXT_WINDOWS)})


# ---------------------------------------------------------------- 工作区

class CreateNovelReq(BaseModel):
    title: str = Field(default="", max_length=100)
    model: ModelRef
    contextWindow: int = 8192


def _check_window(w: int) -> None:
    if w not in store.CONTEXT_WINDOWS:
        raise LocalError(400, f"上下文窗口只能是 {store.CONTEXT_WINDOWS}")


@router.get("/novels")
def list_novels():
    return ok(store.list_novels())


@router.post("/novels")
def create_novel(req: CreateNovelReq):
    _check_window(req.contextWindow)
    return ok(store.create_novel(req.title, req.model.model_dump(), req.contextWindow))


@router.get("/novels/{novel_id}")
def get_novel(novel_id: str):
    novel = _guard(store.get_novel, novel_id)
    return ok(novel | {"chapters": store.list_chapters(novel_id),
                       "defaultTargetChars": spec_mod.default_target_chars(novel["settings"].get("spec"))})


class UpdateNovelReq(BaseModel):
    title: Optional[str] = Field(default=None, max_length=100)
    model: Optional[ModelRef] = None
    contextWindow: Optional[int] = None
    params: Optional[dict] = None
    # 设定：config = 设定编辑器的完整配置 {categories, values}；spec = 前端 buildSpec() 结果（只含已确认的内容）
    settings: Optional[dict] = None


@router.post("/novels/{novel_id}/update")
def update_novel(novel_id: str, req: UpdateNovelReq):
    if chapter.active_job() and chapter.active_job()["novelId"] == novel_id:
        raise LocalError(400, "本工作区正在生成章节，完成后再修改")
    fields = {}
    if req.title is not None:
        fields["title"] = req.title.strip() or "未命名小说"
    if req.model is not None:
        fields["model"] = req.model.model_dump()
    if req.contextWindow is not None:
        _check_window(req.contextWindow)
        fields["contextWindow"] = req.contextWindow
    if req.params is not None:
        cur = _guard(store.get_novel, novel_id)["params"]
        fields["params"] = cur | {k: v for k, v in req.params.items() if k in store.DEFAULT_PARAMS}
    if req.settings is not None:
        fields["settings"] = {"config": req.settings.get("config"), "spec": req.settings.get("spec"),
                              "savedAt": store.now()}
    return ok(_guard(store.update_novel, novel_id, **fields))


@router.post("/novels/{novel_id}/delete")
def delete_novel(novel_id: str):
    job = chapter.active_job()
    if job and job["novelId"] == novel_id:
        raise LocalError(400, "本工作区正在生成章节，请先取消")
    _guard(store.delete_novel, novel_id)
    return ok()


@router.post("/novels/{novel_id}/model/load")
def load_model(novel_id: str):
    """加载工作区所选的模型（本阶段不使用 LoRA 适配器）。"""
    novel = _guard(store.get_novel, novel_id)
    m = novel["model"]
    if m.get("source") != "local":
        raise LocalError(400, "远程模型暂未接入")
    return ok(_guard(inference.load, m["baseId"], None, "auto"))


# ---------------------------------------------------------------- 章节

class ChapterReq(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=60)
    targetChars: int = Field(default=2000, ge=200, le=20000)


@router.get("/novels/{novel_id}/chapters/{index}")
def get_chapter(novel_id: str, index: int):
    return ok(_guard(store.get_chapter, novel_id, index))


@router.post("/novels/{novel_id}/chapters/{index}/delete")
def delete_chapter(novel_id: str, index: int):
    job = chapter.active_job()
    if job and job["novelId"] == novel_id:
        raise LocalError(400, "本工作区正在生成章节，请先取消")
    _guard(store.delete_last_chapter, novel_id, index)
    return ok()


@router.post("/novels/{novel_id}/preview")
def preview(novel_id: str, req: ChapterReq):
    """组装下一章第一段的上下文（不调用模型），返回分层 token 用量与完整提示词。只需 tokenizer，不必加载模型。"""
    return ok(_guard(chapter.preview, novel_id, req.model_dump()))


@router.post("/novels/{novel_id}/chapters")
def start_chapter(novel_id: str, req: ChapterReq):
    return ok(_guard(chapter.start, novel_id, req.model_dump()))


@router.get("/jobs/{job_id}")
def get_job(job_id: str):
    """任务状态 + 当前章节（正文实时增长、每次调用的 token 明细）。"""
    job = _guard(chapter.get_job, job_id)
    ch = None
    try:
        ch = store.get_chapter(job["novelId"], job["chapterIndex"])
    except store.StoreError:
        pass
    return ok(job | {"chapter": ch})


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    return ok(_guard(chapter.cancel, job_id))
