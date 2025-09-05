# api/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# copy api and cli_tool (assumes project root structure where you build from root and copy everything)
COPY . /app

RUN pip install --upgrade pip
RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

