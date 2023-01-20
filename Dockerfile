# Using the -slim image (debian based) instead of -alpine
# See https://pythonspeed.com/articles/alpine-docker-python/
FROM python:3.11.1-slim as base

ENV PYTHONDONTWRITEBYTECODE 1 \
    PYTHONFAULTHANDLER 1 \
    PYTHONBUFFERED 1 

WORKDIR /app

FROM base as deps

ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.3.2

# Install poetry and create a venv for the app
RUN pip install "poetry==$POETRY_VERSION"
RUN python -m venv /venv

# Use poetry to install dependencies (but not the app package)
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root

# It's reasonable to expect the app code to change more frequently than the dependencies,
# especially during development. So I'll build the app in its own stage.
FROM deps as builder
COPY . .
RUN poetry build && /venv/bin/pip install dist/*.whl

FROM base as runner
ENV PATH="/venv/bin:${PATH}" \
    VIRTUAL_ENV="/venv"

# Copy the app code from the virtualenv that we've built in the previous stages
COPY --from=builder /venv /venv

ENTRYPOINT ["critter-catcher", "--help"]