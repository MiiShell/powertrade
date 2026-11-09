FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /smoke
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY conftest.py test_*.py ./
# Runs as root (no capabilities) only to read Caddy's 0600 root CA from the shared volume.
CMD ["pytest", "-v", "-p", "no:cacheprovider"]
