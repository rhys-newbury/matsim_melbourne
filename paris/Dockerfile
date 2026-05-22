FROM ubuntu:24.04

LABEL org.opencontainers.image.description="""\
This image is used to run the eqasim pipeline \
"""

# Install system dependencies
RUN apt update && apt install -y git openjdk-25-jdk maven

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

USER 1000:1000

# Setup environment
COPY --chown=1000:1000 pyproject.toml uv.lock .python-version /eqasim/
RUN cd /eqasim && uv sync

RUN chown -R 1000:1000 /eqasim


COPY --chown=1000:1000 analysis /eqasim/analysis
COPY --chown=1000:1000 data /eqasim/data
COPY --chown=1000:1000 matsim /eqasim/matsim
COPY --chown=1000:1000 noise /eqasim/noise
COPY --chown=1000:1000 synthesis /eqasim/synthesis
COPY --chown=1000:1000 documentation /eqasim/documentation
COPY --chown=1000:1000 version.txt /eqasim
COPY --chown=1000:1000 config.yml /eqasim

RUN mkdir -p /tmp/eqasim-cache /tmp/eqasim-output

# Set up iterface
WORKDIR /eqasim
