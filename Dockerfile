FROM node:20-slim AS build-web

ARG CI=true
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable
COPY ./web /web
WORKDIR /web

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

RUN pnpm run build


FROM ghcr.io/astral-sh/uv:python3.12-trixie

WORKDIR /app
ENV UV_LINK_MODE=copy
ENV UV_COMPILE_BYTECODE=1

RUN apt update && apt install -y libgl1 libglx-mesa0

COPY pyproject.toml /app/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --extra cuda

COPY ./llm2doc /app/llm2doc
COPY ./data/*.pdf /app/data/
COPY ./data/font /app/data/font
COPY --from=build-web /web/dist /app/web_static

EXPOSE 80
CMD ["uv", "run", "fastapi", "run", "llm2doc/server.py", "--port", "80"]
