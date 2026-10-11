# Local vertical-slice image. It does not expose an HTTP API or start workers.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["agos"]
CMD ["--help"]
