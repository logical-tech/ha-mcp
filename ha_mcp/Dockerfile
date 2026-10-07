FROM python:3.13-slim
RUN pip install --no-cache-dir "mcp>=2,<3" httpx websockets
COPY server.py /server.py
CMD ["python", "-u", "/server.py"]
