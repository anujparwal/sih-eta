FROM docker.io/library/python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /project
RUN useradd --create-home --uid 10001 simulator
COPY --chown=simulator:simulator simulator/ ./simulator/
COPY --chown=simulator:simulator data/ ./data/
USER simulator
CMD ["python", "-m", "simulator.simulate", "--interval", "5"]
