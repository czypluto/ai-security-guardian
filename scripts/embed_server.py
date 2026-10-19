"""本地嵌入服务 —— WeMM-Embedding-2B（transformers 直载 int8 GPU）。

对外只暴露 OpenAI 兼容的 `POST /v1/embeddings`，任何 OpenAI 兼容客户端都能直接用。
接口与铁路购票系统的嵌入服务保持一致（同一模型、同一协议），便于两处共用同一套讲解。

为什么不用 vLLM：
    vLLM 的价值在**多用户高并发**（continuous batching）。本项目的知识库是本地单人、
    低频调用，用不上吞吐优势，却要付出单独装 vLLM、启动等待 180s、额外占显存的代价。
    这里直接 transformers 加载——模型已在本地，秒级起服务。

运行（WSL 内）：
    /usr/bin/python3 -m uvicorn scripts.embed_server:app --host 0.0.0.0 --port 8099

环境变量：
    EMBED_MODEL_DIR   模型目录，默认 /home/cpluto/models/WeMM-Embedding-2B
    EMBED_OUTPUT_DIM  MRL 截断维度，默认 1024
    EMBED_DEVICE      cuda / cpu，默认 cuda
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, Union

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = os.getenv("EMBED_MODEL_DIR", "/home/cpluto/models/WeMM-Embedding-2B")
MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "wemm-embedding-2b")
OUTPUT_DIM = int(os.getenv("EMBED_OUTPUT_DIM", "1024"))
DEVICE = os.getenv("EMBED_DEVICE", "cuda")

_proc = None
_model = None


class EmbedRequest(BaseModel):
    model: Optional[str] = None
    input: Optional[Union[str, list[str]]] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _proc, _model
    from transformers import AutoModel, AutoProcessor, BitsAndBytesConfig

    if not os.path.isdir(MODEL_DIR):
        raise RuntimeError(f"嵌入模型目录不存在：{MODEL_DIR}")

    logger.info("加载 WeMM-Embedding-2B（int8，%s）：%s", DEVICE, MODEL_DIR)
    kwargs = {"trust_remote_code": True, "low_cpu_mem_usage": True}
    if DEVICE.startswith("cuda"):
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
        kwargs["device_map"] = "cuda:0"
    _proc = AutoProcessor.from_pretrained(MODEL_DIR, trust_remote_code=True)
    try:
        _model = AutoModel.from_pretrained(MODEL_DIR, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error("模型加载失败：%s", e)
        logger.error(
            "若报显存不足（CUDA out of memory）：本机很可能已有另一份嵌入服务占着 GPU。"
            "6GB 显存只够一份 WeMM-Embedding-2B（实测单份约占 3.8G）——"
            "先停掉另一份（如另一个项目的嵌入服务），或改用共用同一条服务。")
        raise
    _model.eval()
    logger.info("WeMM-Embedding-2B 就绪（int8，%s，输出 %d 维）", DEVICE, OUTPUT_DIM)
    yield
    _proc, _model = None, None


app = FastAPI(title="guardian-embed", lifespan=lifespan)


def _encode_text(text: str) -> list[float]:
    """官方推理路径：对话模板 → processor → model.embedding() → L2 归一化 → MRL 截断。"""
    import torch
    import torch.nn.functional as F

    messages = [{"role": "user", "content": [{"type": "text", "text": text}]}]
    prompt = _proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    inputs = _proc(text=prompt, return_tensors="pt")
    inputs = {k: (v.to(_model.device) if hasattr(v, "to") else v) for k, v in inputs.items()}
    with torch.inference_mode():
        emb = _model.embedding(**inputs).float()
    # MRL（Matryoshka）：前缀子向量本身就是可用表示，截断后仍保持语义
    emb = F.normalize(emb[..., :OUTPUT_DIM], dim=-1)
    return emb[0].cpu().tolist()


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME, "dir": MODEL_DIR,
            "dim": OUTPUT_DIM, "device": DEVICE}


@app.get("/v1/models")
async def models():
    """OpenAI 兼容的模型列表，便于沿用 OpenAI 生态客户端的就绪探测。"""
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model"}]}


@app.post("/v1/embeddings")
def embeddings(req: EmbedRequest):
    texts = [req.input] if isinstance(req.input, str) else (req.input or [])
    data = [{"index": i, "object": "embedding", "embedding": _encode_text(t)}
            for i, t in enumerate(texts)]
    return {"object": "list", "data": data, "model": req.model or MODEL_NAME}
