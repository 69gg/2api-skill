FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project

# 拷业务代码（不含 registrar 时可省略第二行；此处一并拷以便可选启用注册机）
COPY app ./app
COPY registrar ./registrar

EXPOSE 8088

# config.toml 与 account/ 通过 volume 挂载（见 docker-compose.yml）
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
