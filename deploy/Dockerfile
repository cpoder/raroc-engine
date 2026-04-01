FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    scipy click rich fastapi uvicorn httpx \
    python-multipart openpyxl xlsxwriter mcp pydantic fpdf2

# Copy engine
COPY raroc_engine/ /app/raroc_engine/
COPY repository/ /app/repository/
COPY serve.py run_raroc.py sample_deals.csv METHODOLOGY.md /app/

# Premium data (mounted or baked in)
COPY premium_banks.json /app/premium_banks.json

EXPOSE 8000

CMD ["python3", "serve.py", "--host", "0.0.0.0", "--port", "8000"]
