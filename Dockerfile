FROM python:3.12.11-slim
LABEL maintainer="zelenskaulia@gmail.com"

ENV PYTHONUNBUFFERED 1
WORKDIR /app
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt
COPY . .
