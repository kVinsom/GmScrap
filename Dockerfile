# The multi-platform digest also pins the OS and bundled build tooling.
FROM python:3.14.10-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS dependencies
WORKDIR /build
COPY requirements.txt requirements-build.txt ./
RUN python -m venv --without-pip /opt/venv \
    && python -m pip --python /opt/venv install --no-cache-dir --only-binary=:all: -r requirements.txt \
    && python -m pip --python /opt/venv check
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements-build.txt
COPY pyproject.toml README.md LICENSE MANIFEST.in ./
COPY src/ ./src/
RUN python -m build --wheel --no-isolation --outdir /wheels \
    && python -m pip --python /opt/venv install --no-deps /wheels/*.whl \
    && python -m pip --python /opt/venv check \
    && /opt/venv/bin/gmscrap --version

FROM base AS runtime
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp
COPY --from=dependencies /opt/venv /opt/venv
COPY LICENSE ./LICENSE
USER 10001:10001
ENTRYPOINT ["gmscrap"]
CMD ["--help"]
