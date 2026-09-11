# DLNA 音响控制系统
# 零第三方依赖：只用 Python 标准库（Web 层见 app/miniweb.py）
# 多架构：amd64 / arm64 / armv7（iStoreOS / 路由器 / NAS 均可）
#
# ★ 运行时必须用 host 网络模式，否则 SSDP 组播发现不到音响

FROM python:3.12-alpine

LABEL maintainer="dlna-speaker" \
      description="Dependency-free DLNA/UPnP control point for LAN speakers"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai \
    HTTP_PORT=5000 \
    PREFER_NET="192.168.1."

WORKDIR /app

# 时区数据：尽力安装，失败不阻断构建（无 tzdata 时回退到 TZ 环境变量的 POSIX 写法）
RUN apk add --no-cache tzdata >/dev/null 2>&1 || true

# 无需 pip install —— 全部使用标准库，构建秒级完成
COPY app/ ./app/

RUN mkdir -p /music

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=8s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('HTTP_PORT','5000')+'/api/health',timeout=5)" || exit 1

CMD ["python", "-u", "app/server.py"]
