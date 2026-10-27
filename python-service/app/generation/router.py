"""小说生成 API（前缀 /api/gen），响应 {code, message, data}，code=0 成功。前端直接调用（同 /api/local）。"""
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import llm_client
from ..local import inference, llama, registry
from ..local.router import LocalError, ok
from . import chapter, defaults, facts as facts_mod, ideas, spec as spec_mod, store
from .backends import GenerationError

router = APIRouter(prefix="/api/gen", tags=["novel-generation"])
inference.set_generation_busy_check(lambda: chapter.active_job() is not None)


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (store.StoreError, registry.RegistryError, ideas.IdeaError, GenerationError, chapter.JobError,
            llama.LlamaError, RuntimeError) as e:
        raise LocalError(400, str(e)) from e


class ModelRef(BaseModel):
    # local = 本机模型（safetensors + LoRA 适配器）；api = 大模型（Java「模型配置」中启用的）；
    # gguf = 「llama.cpp」页正在运行的 GGUF 模型；remote = 远程 GPU 模型（预留）
    source: Literal["local", "api", "gguf", "remote"] = "local"
    baseId: Optional[str] = None
    adapterId: Optional[str] = None  # 本地 LoRA 适配器（须与 baseId 兼容）；None = 只用基础模型
    # 大模型：生成时由 Java 附带「模型配置」中启用的模型；这里只存展示用的名称（如 DeepSeek · deepseek-chat）
    apiName: Optional[str] = Field(default=None, max_length=100)


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


def _model(ref: ModelRef) -> dict:
    """校验适配器与基础模型兼容（与加载时同一套规则），返回要保存的模型配置。"""
    m = ref.model_dump()
    m["adapterId"] = m["adapterId"] or None
    if m["source"] == "remote":
        raise LocalError(400, "远程模型（远程 GPU 上的模型 + 适配器）暂未接入")
    if m["source"] == "local" and not m["baseId"]:
        raise LocalError(400, "请选择本地基础模型")
    if m["adapterId"]:
        if m["source"] != "local" or not m["baseId"]:
            raise LocalError(400, "LoRA 适配器只能用于本地基础模型")
        _guard(inference.check_adapter, m["adapterId"], m["baseId"])
    return m


@router.get("/novels")
def list_novels():
    return ok(store.list_novels())


@router.post("/novels")
def create_novel(req: CreateNovelReq):
    _check_window(req.contextWindow)
    return ok(store.create_novel(req.title, _model(req.model), req.contextWindow))


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
    # 大纲（AI 构思后由用户确认 / 编辑）：{logline, synopsis, chapters:[{index, title, goal, materials}], materials}
    outline: Optional[dict] = None
    clearOutline: bool = False
    arcSummary: Optional[str] = Field(default=None, max_length=5000)  # 前情概要（AI 合并生成，可手动修改）


@router.post("/novels/{novel_id}/update")
def update_novel(novel_id: str, req: UpdateNovelReq):
    if chapter.active_job() and chapter.active_job()["novelId"] == novel_id:
        raise LocalError(400, "本工作区正在生成章节，完成后再修改")
    fields = {}
    if req.title is not None:
        fields["title"] = req.title.strip() or "未命名小说"
    if req.model is not None:
        fields["model"] = _model(req.model)
    if req.contextWindow is not None:
        _check_window(req.contextWindow)
        fields["contextWindow"] = req.contextWindow
    if req.params is not None:
        cur = _guard(store.get_novel, novel_id)["params"]
        fields["params"] = cur | {k: v for k, v in req.params.items() if k in store.DEFAULT_PARAMS}
    if req.arcSummary is not None:
        fields["arcSummary"] = req.arcSummary.strip()
    if req.outline is not None or req.clearOutline:
        fields["outline"] = None if req.clearOutline else ideas.validate_outline(req.outline)
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
    """加载工作区所选的模型（+ 所选 LoRA 适配器；同一基础模型已驻留时只切换适配器）。"""
    novel = _guard(store.get_novel, novel_id)
    m = novel["model"]
    if m.get("source") == "gguf":
        raise LocalError(400, "GGUF 工作区用「llama.cpp」页启动的模型，不在这里加载")
    if m.get("source") != "local":
        raise LocalError(400, "大模型工作区不需要加载本地模型（润色时会自动加载所选的本地模型）")
    return ok(_guard(inference.load, m["baseId"], m.get("adapterId") or None, "auto"))


# ---------------------------------------------------------------- 章节

class PolishReq(BaseModel):
    """用本地基础模型（+ LoRA 适配器）润色。"""
    enabled: bool = True
    baseId: Optional[str] = None
    adapterId: Optional[str] = None


class ChapterReq(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    title: str = Field(default="", max_length=60)
    targetChars: int = Field(default=2000, ge=200, le=20000)
    polish: Optional[PolishReq] = None
    # 大模型配置（含 API Key）：只由 Java 的 /api/novel/gen/** 转发时附带，只在本次任务内存中使用
    api: Optional[llm_client.ModelConfig] = None


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
    """开始生成下一章。本地模型工作区由前端直接调用；大模型工作区经 Java 转发（附带 api 配置）。"""
    return ok(_guard(chapter.start, novel_id, req.model_dump()))


class IdeasReq(BaseModel):
    kind: Literal["title", "outline", "chapter", "fill", "direction", "chat"]
    hint: str = Field(default="", max_length=500)
    purpose: str = Field(default="", max_length=60)   # kind=direction：方向用在哪里（构思书名 / 补全角色…）
    chat: Optional[dict] = None   # kind=chat：{character: {name, card}, messages, scene?, userRole?}（见 ideas._chat）
    count: Optional[int] = Field(default=None, ge=1, le=40)
    materials: list[dict] = Field(default_factory=list, max_length=40)  # Java 从素材库取出的素材
    fill: Optional[dict] = None   # kind=fill：要填写的字段与位置（见 ideas._fill）
    spec: Optional[list] = None   # kind=fill / direction / chat：设定编辑器当前（可能未保存）的设定
    api: Optional[llm_client.ModelConfig] = None  # 用大模型：Java 附带的配置
    local: Optional[PolishReq] = None             # 用本地模型：{baseId, adapterId}（enabled 忽略）
    gguf: bool = False                            # 用「llama.cpp」页正在运行的 GGUF 模型


@router.post("/novels/{novel_id}/ideas")
def novel_ideas(novel_id: str, req: IdeasReq):
    """AI 构思（书名 / 大纲 / 下一章标题与目标），结合设定与素材；只返回建议，不保存。经 Java 转发。"""
    data = req.model_dump()
    if data.pop("gguf"):
        # 本机小模型：走大模型的调用方式，但单个文本字段同本地模型一样直接要正文（见 ideas._fill）
        data["api"], data["local"], data["gguf"] = _guard(llama.api_config), None, True
    return ok(_guard(ideas.generate, novel_id, data))


@router.post("/novels/{novel_id}/chapters/{index}/polish")
def polish_chapter(novel_id: str, index: int, req: PolishReq):
    """用本地模型（+ 适配器）润色已完成的章节（后台任务，进度见 /jobs/{jobId}）；原文保留，可恢复。"""
    return ok(_guard(chapter.start_polish, novel_id, index, req.model_dump()))


class EditChapterReq(BaseModel):
    title: Optional[str] = Field(default=None, max_length=60)
    goal: Optional[str] = Field(default=None, max_length=2000)
    text: Optional[str] = Field(default=None, max_length=200000)
    summary: Optional[str] = Field(default=None, max_length=2000)


@router.post("/novels/{novel_id}/chapters/{index}/update")
def edit_chapter(novel_id: str, index: int, req: EditChapterReq):
    """手动修改章节（AI 生成的标题 / 目标 / 正文 / 摘要都可以改）；只改传入的字段。"""
    return ok(_guard(chapter.edit_chapter, novel_id, index, req.model_dump()))


class RecheckReq(BaseModel):
    digest: bool = True    # 重新抽取本章摘要与故事事实（替换账本里本章的旧记录）
    review: bool = False   # 重新检查一致性
    api: Optional[llm_client.ModelConfig] = None  # 大模型工作区：经 Java 转发时附带


@router.post("/novels/{novel_id}/chapters/{index}/recheck")
def recheck_chapter(novel_id: str, index: int, req: RecheckReq):
    """已完成章节：重新提取事实 / 重新检查一致性（后台任务 kind=recheck，进度见 /jobs/{jobId}）。
    本地模型工作区由前端直接调用；大模型工作区经 Java 转发。"""
    return ok(_guard(chapter.start_recheck, novel_id, index, req.model_dump()))


class IgnoreReviewReq(BaseModel):
    ignored: bool = True


@router.post("/novels/{novel_id}/chapters/{index}/review/ignore")
def ignore_review(novel_id: str, index: int, req: IgnoreReviewReq):
    return ok(_guard(chapter.set_review_ignored, novel_id, index, req.ignored))


# ---------------------------------------------------------------- 故事账本

@router.get("/novels/{novel_id}/facts")
def get_facts(novel_id: str):
    """伏笔 / 角色状态 / 时间线（每章写完自动抽取，可手动修改）。"""
    _guard(store.get_novel, novel_id)
    return ok(_guard(store.get_facts, novel_id))


class FactsReq(BaseModel):
    facts: dict


@router.post("/novels/{novel_id}/facts/update")
def update_facts(novel_id: str, req: FactsReq):
    """保存手动修改后的整个账本（作者新建 / 修改的条目带 manual=true，AI 之后只追加历史、不改它）。"""
    job = chapter.active_job()
    if job and job["novelId"] == novel_id:
        raise LocalError(400, "本工作区正在生成或处理章节，完成后再修改账本")
    _guard(store.get_novel, novel_id)
    f = facts_mod.sanitize(req.facts)
    _guard(store.save_facts, novel_id, f)
    return ok(f)


@router.post("/novels/{novel_id}/chapters/{index}/polish/revert")
def revert_polish(novel_id: str, index: int):
    """恢复润色前的原文。"""
    return ok(_guard(chapter.revert_polish, novel_id, index))


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
