FROM restic/restic:0.19.1 AS restic
FROM python:3.12-slim
COPY --from=restic /usr/bin/restic /usr/local/bin/restic
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .
CMD ["python", "-u", "worker.py"]
