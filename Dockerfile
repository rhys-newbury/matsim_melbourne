FROM pytorch/pytorch:2.2.0-cuda11.8-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    RENV_PATHS_CACHE=/opt/renv/cache

RUN apt-get update && apt-get install -y --no-install-recommends \
    git sudo ca-certificates gnupg wget build-essential gfortran \
    libcurl4-openssl-dev libssl-dev libxml2-dev libudunits2-dev libuv1-dev \
    libgdal-dev libgeos-dev libproj-dev libsqlite3-dev \
    libfontconfig1-dev libfreetype6-dev libharfbuzz-dev libfribidi-dev \
    libpng-dev libjpeg-dev libtiff5-dev \
    openjdk-21-jdk maven \
 && mkdir -p /etc/sudoers.d \
 && rm -rf /var/lib/apt/lists/*

RUN wget -qO- https://cloud.r-project.org/bin/linux/ubuntu/marutter_pubkey.asc \
      | gpg --dearmor -o /usr/share/keyrings/cran-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cran-archive-keyring.gpg] https://cloud.r-project.org/bin/linux/ubuntu jammy-cran40/" \
      > /etc/apt/sources.list.d/cran-r.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends r-base r-base-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# -------------------------
# Python / ml_surrogates
# -------------------------
RUN pip install --no-cache-dir \
    pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv \
    -f https://data.pyg.org/whl/torch-2.2.0+cu118.html

RUN pip install --no-cache-dir \
    wandb scikit-learn torch_geometric pandas geopandas ipykernel \
    IProgress xgboost matplotlib

COPY ml_surrogates /app/ml_surrogates
WORKDIR /app/ml_surrogates
RUN pip install -e .

# -------------------------
# R / melbourne-demand
# -------------------------
WORKDIR /app/melbourne-demand

RUN R -q -e "install.packages('renv', repos='https://cloud.r-project.org')"

COPY melbourne-demand/renv.lock ./
COPY melbourne-demand/renv/activate.R renv/activate.R
COPY melbourne-demand/renv/settings.json renv/settings.json

RUN R -q -e "renv::restore(prompt = FALSE)"

COPY melbourne-demand /app/melbourne-demand

# -------------------------
# Java / melbourne-baseline
# -------------------------
WORKDIR /app/melbourne-baseline

COPY melbourne-baseline/pom.xml ./
RUN mvn -q -DskipTests dependency:go-offline

COPY melbourne-baseline /app/melbourne-baseline

RUN if [ -f scripts/bootstrap_baseline.sh ]; then \
      bash scripts/bootstrap_baseline.sh; \
    fi

# -------------------------
# User
# -------------------------
RUN groupadd --gid 1000 taco \
 && useradd --uid 1000 --gid 1000 -m taco -s /bin/bash \
 && echo "taco ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/taco \
 && chmod 0440 /etc/sudoers.d/taco \
 && chown -R taco:taco /app /opt/renv

USER taco

WORKDIR /app