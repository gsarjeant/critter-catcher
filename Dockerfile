# Using the -slim image (debian based) instead of -alpine
# See https://pythonspeed.com/articles/alpine-docker-python/
FROM python:3.11.1-slim as base

ENV TZ="America/New_York"
ENV PYTHONDONTWRITEBYTECODE 1 \
    PYTHONFAULTHANDLER 1 \
    PYTHONBUFFERED 1 

# Running as PID 1 can cause problems with properly handling signals (which I'm trying to do)
# tini spawns a small init process that runs as PID 1 and properly proxies signals to the application process
# NOTE: This can also be done by passing --init to docker run, but installing it and making it part of the entrypoint
#       means people don't have to remember to do that.
#
# Good overview of tini here: https://github.com/krallin/tini/issues/8#issuecomment-146135930
RUN apt-get update && \
    apt-get install -yq --no-install-recommends \
    tini && \
    apt-get clean && \
    rm -rf /var/apt/lists/*
RUN addgroup --system --gid 1001 critter && \
    adduser --system --uid 1001 critter

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
RUN poetry install --no-root --without dev

# It's reasonable to expect the app code to change more frequently than the dependencies,
# especially during development. So I'll build the app in its own stage.
FROM deps as builder
COPY . .
RUN poetry build && /venv/bin/pip install dist/*.whl

# Create the final runtime image, configuring it to use the venv we just configured and discarding all the build deps
# (really just poetry and its dependenciesdt. for now.)
FROM base as runner
ENV PATH="/venv/bin:${PATH}" \
    VIRTUAL_ENV="/venv"

# Copy the app code from the virtualenv that we've built in the previous stages
COPY --from=builder /venv /venv

USER critter

ENTRYPOINT ["tini", "-v", "--", "critter-catcher"]
CMD ["--help"]