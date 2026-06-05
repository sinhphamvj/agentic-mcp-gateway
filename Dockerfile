FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY . /app

RUN pip install uv
RUN uv sync --no-dev

EXPOSE 8001
CMD ["uv", "run", "amcpg", "serve", "--host", "0.0.0.0", "--port", "8001"]
