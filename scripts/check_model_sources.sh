#!/usr/bin/env bash
# 探测魔搭上 Qwen3-Embedding 各版本文件是否可下载
for id in Qwen/Qwen3-Embedding-1.7B Qwen/Qwen3-Embedding-0.6B Qwen/Qwen3-Embedding-4B Qwen/Qwen3-Embedding-8B; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --connect-timeout 8 -L "https://modelscope.cn/models/$id/resolve/master/config.json")
  echo "$code  $id"
done
