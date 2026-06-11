FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建静态文件目录（以防万一）
RUN mkdir -p static

EXPOSE 8000

CMD ["python", "app.py"]
