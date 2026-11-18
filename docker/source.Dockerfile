FROM python:3.12-alpine
WORKDIR /app
COPY scripts/source.py .
CMD ["python", "-u", "source.py"]
