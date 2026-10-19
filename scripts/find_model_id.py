"""在魔搭(Modelscope)上搜索 Qwen3-Embedding 模型的确切 ID。"""
import json

import requests


def find_paths(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("Path", "Name", "model_id") and isinstance(v, str) and "Embedding" in v:
                out.append(v)
            find_paths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_paths(v, out)


def main():
    for query in ("Qwen3-Embedding", "Qwen3-Embedding-1.7B", "Qwen3-Embedding-8B"):
        try:
            r = requests.get(
                "https://modelscope.cn/api/v1/models",
                params={"PageNumber": 1, "PageSize": 50, "Query": query},
                timeout=20,
            )
            d = r.json()
            found = []
            find_paths(d, found)
            print(f"查询 {query!r}: 找到 {len(found)} 个")
            for f in dict.fromkeys(found):
                print("   ", f)
            if not found:
                print("    (未解析到路径，原始响应前 300 字符:",
                      json.dumps(d, ensure_ascii=False)[:300], ")")
        except Exception as e:
            print(f"查询 {query!r} 失败: {e}")


if __name__ == "__main__":
    main()
