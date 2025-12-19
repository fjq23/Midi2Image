FROM docker.1ms.run/python:3.12-bookworm

# Install build tools (Pillow may compile depending on wheels availability)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --no-cache-dir -r /app/requirements.txt

COPY . /app

EXPOSE 8012

CMD ["python", "web_app.py"]

