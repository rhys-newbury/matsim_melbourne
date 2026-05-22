# syntax=docker/dockerfile:1.7

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    RENV_PATHS_LIBRARY=/opt/renv/library \
    RENV_PATHS_CACHE=/opt/renv/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates gnupg software-properties-common dirmngr wget lsb-release \
    locales build-essential gfortran cmake \
    libcurl4-openssl-dev libssl-dev libxml2-dev libudunits2-dev libuv1-dev \
    libgdal-dev libgeos-dev libproj-dev libsqlite3-dev \
    libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
    libpng-dev libjpeg-dev libtiff5-dev \
    && locale-gen en_US.UTF-8 \
    && wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc \
      | gpg --dearmor -o /usr/share/keyrings/cran-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/cran-archive-keyring.gpg] https://cloud.r-project.org/bin/linux/ubuntu noble-cran40/" \
      > /etc/apt/sources.list.d/cran-r.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends r-base r-base-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /opt/renv/library /opt/renv/cache

RUN Rscript -e "install.packages('renv', repos='https://cloud.r-project.org')"

COPY renv.lock ./

RUN --mount=type=cache,target=/opt/renv/cache \
    Rscript -e "\
renv::restore(project='/app', library='/opt/renv/library', prompt=FALSE, rebuild=FALSE); \
.libPaths('/opt/renv/library'); \
stopifnot(requireNamespace('dplyr', quietly=TRUE))"

COPY . .