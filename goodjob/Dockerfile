FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/goodjob
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home goodjob
COPY --chown=goodjob:goodjob app ./app
USER goodjob
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
