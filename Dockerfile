FROM python:3.12-slim

WORKDIR /app


COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser + system deps inside the image
RUN python -m playwright install --with-deps chromium


COPY . .

EXPOSE 8000

CMD ["uvicorn", "scraping:app", "--host", "0.0.0.0", "--port", "8000"]