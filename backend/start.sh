#!/bin/bash
# 启动后端服务
cd "$(dirname "$0")"
pip install -r requirements.txt 2>/dev/null
python main.py
